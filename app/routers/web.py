"""Содержит веб-маршруты для страниц турнира, админки и пользовательских действий."""

import json
import math
import uuid
import re
from urllib.parse import urlencode
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.admin_session import (
    ADMIN_SESSION_COOKIE,
    create_admin_session_cookie,
    create_judge_login_token,
    is_admin_session,
)
from app.core.config import settings
from app.db.session import get_db
from app.models.chat import ChatMessage
from app.models.settings import (
    ArchiveEntry,
    ChatSetting,
    DonationLink,
    DonationMethod,
    Donor,
    PrizePoolEntry,
    RulesContent,
    SiteSetting,
    TournamentStage,
)
from app.models.tournament import GroupGameResult, GroupMember, PlayoffMatch, PlayoffParticipant, PlayoffStage, TournamentGroup
from app.models.user import Basket, User
from app.services.basket_allocator import allocate_basket
from app.services.i18n import get_lang, t
from app.services.rank import pick_basket
from app.services.steam import fetch_autochess_data, normalize_steam_id
from app.services.tournament import (
    apply_game_results,
    apply_playoff_match_results,
    create_auto_draw,
    create_manual_draw,
    create_manual_draw_from_layout,
    ManualDrawValidationError,
    generate_playoff_from_groups,
    finalize_limited_playoff_stage_if_ready,
    get_playoff_stages_with_data,
    override_playoff_match_winner,
    parse_manual_draw_user_ids,
    move_user_to_stage,
    promote_top_between_stages,
    promote_group_member_to_stage,
    replace_stage_player,
    sort_members_for_table,
    playoff_sort_key,
    start_playoff_stage,
    adjust_stage_points,
    get_stage_group_number_by_seed,
    get_public_stage_display_sequence,
    get_playoff_stage_sequence_keys,
    get_stage_group_label,
    shuffle_stage_2_participants,
    simulate_three_random_games_for_stage,
)
from app.services.tournament_view import (
    build_bracket_columns,
    resolve_current_stage_label,
)

from app.services.tournament_stage_config import (
    GROUP_STAGE_GAME_LIMIT,
    get_admin_playoff_stage_config,
    get_game_limit,
    get_promote_top_n,
    is_limited_stage,
)

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


ALLOWED_USER_UPDATE_FIELDS = {"nickname", "basket", "direct_invite_stage"}
ALLOWED_DIRECT_INVITE_STAGES = {None, *get_playoff_stage_sequence_keys()}
TOURNAMENT_STAGE_KEYS_ORDER = get_public_stage_display_sequence()
PLAYOFF_STAGE_KEYS_ORDER = TOURNAMENT_STAGE_KEYS_ORDER[1:]

CHAT_NICK_COLORS = ["#00d4ff", "#ff7a59", "#b084ff", "#2dd36f", "#ffd166", "#ff66c4", "#5ce1e6", "#f48c06", "#90be6d", "#4cc9f0"]
FORBIDDEN_CHAT_NICKS = {"@admin"}
CHAT_SENDER_TOKEN_RE = re.compile(r"^[0-9a-f]{32}$")


def build_stage_display_order(active_key: str, stage_order_keys: list[str]) -> list[str]:
    if active_key not in stage_order_keys:
        return stage_order_keys

    active_index = stage_order_keys.index(active_key)
    after_active = stage_order_keys[active_index + 1 :]
    before_active = list(reversed(stage_order_keys[:active_index]))
    return [active_key, *after_active, *before_active]


def get_stage_group_numbers(
    stage_key: str,
    stage_size: int | None = None,
    participants_count: int | None = None,
) -> list[int]:
    stage_group_count = {
        "stage_2": 4,
        "stage_1_4": 2,
        "stage_final": 1,
    }
    groups_count = stage_group_count.get(stage_key)
    if is_limited_stage(stage_key):
        size_groups = max((stage_size or 0) // 8, 0)
        if size_groups:
            groups_count = size_groups
        elif participants_count is not None:
            groups_count = max(math.ceil((participants_count or 0) / 8), 0)
    if groups_count is None:
        return []
    return list(range(1, groups_count + 1))


def get_active_playoff_stage(playoff_stages: list[PlayoffStage], stage_order_keys: list[str] | None = None) -> PlayoffStage | None:
    if stage_order_keys is None:
        return next((stage for stage in playoff_stages if stage.is_started), None)

    stage_by_key = {stage.key: stage for stage in playoff_stages}
    for stage_key in stage_order_keys:
        stage = stage_by_key.get(stage_key)
        if stage and stage.is_started:
            return stage
    return None


def get_default_playoff_stage_key(playoff_stages: list[PlayoffStage], stage_order_keys: list[str]) -> str | None:
    if not playoff_stages:
        return None

    stage_by_key = {stage.key: stage for stage in playoff_stages}
    return next((stage_key for stage_key in stage_order_keys if stage_key in stage_by_key), playoff_stages[0].key)


def build_playoff_stage_finish_status(
    stage: PlayoffStage,
    participants: list[PlayoffParticipant] | None = None,
    matches: list[PlayoffMatch] | None = None,
) -> tuple[list[dict[str, int | str]], bool]:
    stage_participants = participants if participants is not None else list(stage.participants)
    stage_matches = matches if matches is not None else list(stage.matches)
    group_numbers = sorted(
        {
            *{get_stage_group_number_by_seed(participant.seed) for participant in stage_participants},
            *{match.group_number for match in stage_matches},
        }
    )
    progress_items: list[dict[str, int | str]] = []
    for group_number in group_numbers:
        games_played = max(
            [max(match.game_number - 1, 0) for match in stage_matches if match.group_number == group_number],
            default=0,
        )
        progress_items.append(
            {
                "name": get_stage_group_label(stage.key, group_number),
                "games_played": games_played,
            }
        )

    if not progress_items:
        return [], False

    if is_limited_stage(stage.key):
        return progress_items, all(item["games_played"] >= GROUP_STAGE_GAME_LIMIT for item in progress_items)

    if stage.key == "stage_final":
        return progress_items, any(match.state == "finished" for match in stage_matches)

    return progress_items, False


def get_empty_active_stage_alert(playoff_stages: list[PlayoffStage]) -> str | None:
    stage_by_order = {stage.stage_order: stage for stage in playoff_stages}
    for stage in playoff_stages:
        if not stage.is_started or stage.participants:
            continue

        previous_stage = stage_by_order.get(stage.stage_order - 1)
        if previous_stage and is_limited_stage(previous_stage.key):
            return (
                f"Этап {stage.title} активен, но участников 0: "
                f"завершите {previous_stage.title} через Stage Finish (/admin/playoff/stage/finish)."
            )
        return f"Этап {stage.title} активен, но участников 0."

    return None


def _normalize_direct_invite_stage(raw_value: str | None) -> str | None:
    value = (raw_value or "").strip() or None
    if value not in ALLOWED_DIRECT_INVITE_STAGES:
        raise ValueError("invalid direct invite stage")
    return value


def _validate_user_update_payload(nickname: str, basket: str, direct_invite_stage: str | None) -> dict[str, str | None]:
    cleaned_nickname = nickname.strip()
    if not cleaned_nickname or len(cleaned_nickname) > 120:
        raise ValueError("invalid nickname")

    allowed_baskets = {item.value for item in Basket}
    if basket not in allowed_baskets:
        raise ValueError("invalid basket")

    normalized_stage = _normalize_direct_invite_stage(direct_invite_stage)
    return {
        "nickname": cleaned_nickname,
        "basket": basket,
        "direct_invite_stage": normalized_stage,
    }


def _display_nickname(user: User | None, fallback: str) -> str:
    if not user:
        return fallback
    game_nickname = (user.game_nickname or "").strip()
    if game_nickname:
        return f"{user.nickname}({game_nickname})"
    return user.nickname


def template_context(request: Request, **extra):
    lang = get_lang(request.cookies.get("lang"))
    context = {"request": request, "lang": lang, "tr": lambda key: t(lang, key)}
    context.update(extra)
    return context


def redirect_with_msg(url: str, msg_key: str, status_code: int = 303) -> RedirectResponse:
    separator = "&" if "?" in url else "?"
    return RedirectResponse(url=f"{url}{separator}msg={msg_key}", status_code=status_code)


def redirect_with_admin_msg(msg_key: str, details: str | None = None) -> RedirectResponse:
    params: dict[str, str] = {"msg": msg_key}
    if details:
        params["details"] = details
    return RedirectResponse(url=f"/admin?{urlencode(params)}", status_code=303)


def redirect_with_admin_users_msg(msg_key: str, details: str | None = None) -> RedirectResponse:
    params: dict[str, str] = {"msg": msg_key}
    if details:
        params["details"] = details
    return RedirectResponse(url=f"/admin/users?{urlencode(params)}", status_code=303)




async def _playoff_stage_exists(db: AsyncSession, stage_id: int) -> bool:
    """Проверяет, что этап плей-офф с указанным `stage_id` существует в БД."""
    return await db.scalar(select(PlayoffStage.id).where(PlayoffStage.id == stage_id)) is not None


async def _get_playoff_stage(db: AsyncSession, stage_id: int) -> PlayoffStage | None:
    return await db.scalar(select(PlayoffStage).where(PlayoffStage.id == stage_id))


async def get_registration_open(db: AsyncSession) -> bool:
    # Получаем флаг доступности регистрации из настроек.
    record = await db.scalar(select(SiteSetting).where(SiteSetting.key == "registration_open"))
    return (record.value == "1") if record else True


async def get_tournament_started(db: AsyncSession) -> bool:
    record = await db.scalar(select(SiteSetting).where(SiteSetting.key == "tournament_started"))
    return (record.value == "1") if record else False


async def get_draw_applied(db: AsyncSession) -> bool:
    record = await db.scalar(select(SiteSetting).where(SiteSetting.key == "draw_applied"))
    return (record.value == "1") if record else False


async def set_draw_applied(db: AsyncSession, value: bool) -> None:
    record = await db.scalar(select(SiteSetting).where(SiteSetting.key == "draw_applied"))
    if not record:
        record = SiteSetting(key="draw_applied", value="0")
        db.add(record)
    record.value = "1" if value else "0"


async def validate_group_draw_integrity(db: AsyncSession) -> tuple[bool, str | None]:
    groups = list((await db.scalars(select(TournamentGroup).where(TournamentGroup.stage == "group_stage"))).all())
    if not groups:
        return False, "draw_not_found"

    group_ids = [group.id for group in groups]
    members = list((await db.scalars(select(GroupMember).where(GroupMember.group_id.in_(group_ids)))).all())
    by_group: dict[int, list[GroupMember]] = {}
    all_user_ids: list[int] = []
    for member in members:
        by_group.setdefault(member.group_id, []).append(member)
        all_user_ids.append(member.user_id)

    if len(all_user_ids) != len(set(all_user_ids)):
        return False, "draw_duplicates_found"

    for group in groups:
        group_members = by_group.get(group.id, [])
        if not group_members:
            return False, "draw_empty_group"
        if len(group_members) != 8:
            return False, "draw_group_size_invalid"

    return True, None


async def get_group_stage_completion_status(db: AsyncSession) -> tuple[bool, str, dict[int, int]]:
    groups = list((await db.scalars(select(TournamentGroup).where(TournamentGroup.stage == "group_stage"))).all())
    if not groups:
        return False, "draw_not_created", {}

    group_ids = [group.id for group in groups]
    group_games_played_rows = (
        await db.execute(
            select(GroupMember.group_id, func.count(func.distinct(GroupGameResult.game_number)))
            .select_from(GroupMember)
            .outerjoin(GroupGameResult, GroupGameResult.group_id == GroupMember.group_id)
            .where(GroupMember.group_id.in_(group_ids))
            .group_by(GroupMember.group_id)
        )
    ).all()
    games_played_by_group = {int(group_id): int(games_count or 0) for group_id, games_count in group_games_played_rows}

    for group in groups:
        if games_played_by_group.get(group.id, 0) < 3:
            return False, "group_stage_not_completed", games_played_by_group

    return True, "group_stage_completed", games_played_by_group


async def get_chat_settings(db: AsyncSession) -> ChatSetting:
    row = await db.scalar(select(ChatSetting).where(ChatSetting.id == 1))
    if row:
        return row
    return ChatSetting(id=1, cooldown_seconds=10, max_length=1000, is_enabled=True)


async def get_or_create_chat_settings(db: AsyncSession) -> ChatSetting:
    row = await db.scalar(select(ChatSetting).where(ChatSetting.id == 1))
    if row:
        return row
    row = ChatSetting(id=1, cooldown_seconds=10, max_length=1000, is_enabled=True)
    db.add(row)
    await db.flush()
    return row


def validate_chat_message_length(message: str, max_length: int) -> None:
    if len(message) > max_length:
        raise ValueError("msg_message_too_long")


def normalize_chat_nick(temp_nick: str) -> str:
    cleaned = (temp_nick or "").strip()[:120]
    if not cleaned:
        raise ValueError("msg_operation_failed")
    if cleaned.lower() in FORBIDDEN_CHAT_NICKS:
        raise ValueError("msg_chat_nick_reserved")
    return cleaned


def normalize_chat_nick_color(color: str) -> str:
    normalized = (color or "").strip().lower()
    if normalized not in CHAT_NICK_COLORS:
        raise ValueError("msg_chat_color_forbidden")
    return normalized


def generate_chat_sender_token() -> str:
    return uuid.uuid4().hex


def resolve_chat_sender_token(chat_sender_cookie: str | None) -> tuple[str, bool]:
    chat_sender = (chat_sender_cookie or "").strip().lower()
    if CHAT_SENDER_TOKEN_RE.fullmatch(chat_sender):
        return chat_sender, False
    return generate_chat_sender_token(), True


def _build_chat_messages_payload(chat_messages: list[ChatMessage]) -> list[dict[str, str]]:
    default_nick_color = CHAT_NICK_COLORS[0]
    return [
        {
            "id": msg.id,
            "temp_nick": msg.temp_nick,
            "message": msg.message,
            "nick_color": msg.nick_color or default_nick_color,
            "is_admin": msg.temp_nick == "@Admin",
        }
        for msg in chat_messages
    ]


async def get_or_create_rules_content(db: AsyncSession) -> RulesContent:
    row = await db.scalar(select(RulesContent).where(RulesContent.id == 1))
    if row:
        return row
    row = RulesContent(id=1, body="")
    db.add(row)
    await db.flush()
    return row


@router.get("/set-lang/{lang}")
async def set_lang(lang: str):
    # Сохраняем выбранный язык в cookie.
    response = RedirectResponse(url="/", status_code=302)
    response.set_cookie("lang", "ru" if lang == "ru" else "en", max_age=60 * 60 * 24 * 365)
    return response


@router.get("/", response_class=HTMLResponse)
async def index(request: Request, db: AsyncSession = Depends(get_db)):
    # Рендерим главную страницу с формой и чатом.
    stages = (await db.scalars(select(TournamentStage).order_by(TournamentStage.id))).all()
    chat_messages = (await db.scalars(select(ChatMessage).order_by(desc(ChatMessage.id)).limit(20))).all()
    registration_open = await get_registration_open(db)
    tournament_started = await get_tournament_started(db)
    chat_settings = await get_chat_settings(db)
    return templates.TemplateResponse(
        request,
        "index.html",
        template_context(
            request,
            stages=stages,
            chat_messages=list(reversed(chat_messages)),
            chat_messages_payload=_build_chat_messages_payload(list(reversed(chat_messages))),
            chat_nick_colors=CHAT_NICK_COLORS,
            registration_open=registration_open,
            tournament_started=tournament_started,
            chat_settings=chat_settings,
        ),
    )


@router.post("/register")
async def register(
    request: Request,
    nickname: str = Form(...),
    steam_input: str = Form(...),
    telegram: str = Form(default=""),
    discord: str = Form(default=""),
    db: AsyncSession = Depends(get_db),
):
    """Регистрирует пользователя, если по steam_id запись в БД отсутствует."""
    if await get_tournament_started(db):
        return redirect_with_msg("/", "registration_closed")

    if not await get_registration_open(db):
        return redirect_with_msg("/", "registration_closed")

    steam_id = await normalize_steam_id(steam_input)
    if not steam_id:
        return redirect_with_msg("/", "msg_invalid_steam_id")

    exists = await db.scalar(select(User).where(User.steam_id == steam_id))
    if exists:
        return redirect_with_msg("/", "already_registered")

    profile = await fetch_autochess_data(steam_id)
    target_basket = pick_basket(profile["highest_rank"], profile["current_rank"])
    basket_counts_rows = (
        await db.execute(
            select(User.basket, func.count(User.id))
            .where(User.basket.isnot(None))
            .group_by(User.basket)
        )
    ).all()
    basket_counts = {basket_name: basket_count for basket_name, basket_count in basket_counts_rows}
    basket = allocate_basket(target_basket=target_basket, basket_counts=basket_counts)

    user = User(
        nickname=nickname,
        steam_input=steam_input,
        steam_id=steam_id,
        game_nickname=profile["game_nickname"],
        current_rank=profile["current_rank"],
        highest_rank=profile["highest_rank"],
        telegram=telegram or None,
        discord=discord or None,
        basket=basket,
        extra_data=json.dumps(profile["raw"], ensure_ascii=False),
    )
    db.add(user)
    await db.commit()
    return redirect_with_msg("/", "registered_ok")


@router.post("/register/preview")
async def register_preview(
    request: Request,
    steam_input: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    """Проверяет Steam-ввод и возвращает данные профиля для предпросмотра регистрации."""
    lang = get_lang(request.cookies.get("lang"))

    if await get_tournament_started(db):
        return JSONResponse({"ok": False, "error": t(lang, "registration_closed")}, status_code=403)

    if not await get_registration_open(db):
        return JSONResponse({"ok": False, "error": t(lang, "registration_closed")}, status_code=403)

    steam_id = await normalize_steam_id(steam_input)
    if not steam_id:
        return JSONResponse({"ok": False, "error": t(lang, "msg_invalid_steam_id")}, status_code=400)

    exists = await db.scalar(select(User).where(User.steam_id == steam_id))
    if exists:
        return JSONResponse({"ok": False, "error": t(lang, "already_registered")}, status_code=409)

    try:
        profile = await fetch_autochess_data(steam_id)
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)

    return {
        "ok": True,
        "steam_id": steam_id,
        "game_nickname": profile["game_nickname"],
        "current_rank": profile["current_rank"],
        "highest_rank": profile["highest_rank"],
    }


@router.post("/chat/send")
async def send_chat(
    request: Request,
    temp_nick: str = Form(...),
    nick_color: str = Form(default="#00d4ff"),
    message: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    # Сохраняем сообщение чата с ограничением, настраиваемым в админке.
    chat_settings = await get_chat_settings(db)
    if not chat_settings.is_enabled:
        return redirect_with_msg("/", "msg_chat_disabled")

    try:
        validate_chat_message_length(message=message, max_length=chat_settings.max_length)
    except ValueError as exc:
        return redirect_with_msg("/", str(exc))

    try:
        safe_nick = normalize_chat_nick(temp_nick)
        safe_color = normalize_chat_nick_color(nick_color)
    except ValueError as exc:
        return redirect_with_msg("/", str(exc))

    ip = request.client.host if request.client else "unknown"
    chat_sender, should_set_chat_sender_cookie = resolve_chat_sender_token(request.cookies.get("chat_sender"))
    last_msg = await db.scalar(
        select(ChatMessage)
        .where(ChatMessage.sender_token == chat_sender)
        .order_by(desc(ChatMessage.created_at))
        .limit(1)
    )
    if last_msg and datetime.utcnow() - last_msg.created_at < timedelta(seconds=chat_settings.cooldown_seconds):
        return redirect_with_msg("/", "msg_cooldown_active")

    db.add(ChatMessage(temp_nick=safe_nick, nick_color=safe_color, message=message, ip_address=ip, sender_token=chat_sender))
    await db.commit()
    redirect = RedirectResponse(url="/#chat", status_code=303)
    if should_set_chat_sender_cookie:
        redirect.set_cookie("chat_sender", chat_sender, max_age=60 * 60 * 24 * 365, samesite="lax")
    return redirect


@router.get("/chat/messages")
async def chat_messages_api(db: AsyncSession = Depends(get_db)):
    chat_messages = (await db.scalars(select(ChatMessage).order_by(desc(ChatMessage.id)).limit(20))).all()
    payload = _build_chat_messages_payload(list(reversed(chat_messages)))
    return {"messages": payload}


@router.get("/participants", response_class=HTMLResponse)
async def participants(
    request: Request,
    basket: str = Query(Basket.QUEEN.value),
    view: str = Query("baskets"),
    db: AsyncSession = Depends(get_db),
):
    # Показываем участников по паре корзин: основной состав + резерв.
    basket_pairs = [
        (Basket.QUEEN.value, Basket.QUEEN_RESERVE.value),
        (Basket.KING.value, Basket.KING_RESERVE.value),
        (Basket.ROOK.value, Basket.ROOK_RESERVE.value),
        (Basket.BISHOP.value, Basket.BISHOP_RESERVE.value),
        (Basket.LOW_RANK.value, Basket.LOW_RANK_RESERVE.value),
    ]
    basket_to_pair = {basket_name: pair for pair in basket_pairs for basket_name in pair}
    selected_pair = basket_to_pair.get(basket, basket_pairs[0])
    main_basket, reserve_basket = selected_pair

    direct_invite_users: list[User] = []

    if view == "direct_invites":
        invited_users = (
            await db.scalars(
                select(User)
                .where(
                    User.basket == Basket.INVITED.value,
                    User.direct_invite_stage == "stage_2",
                )
                .order_by(User.created_at)
            )
        ).all()
        direct_invite_users = list(invited_users)
        main_users = []
        reserve_users = []
    else:
        view = "baskets"
        main_users = (
            await db.scalars(select(User).where(User.basket == main_basket).order_by(User.created_at))
        ).all()
        reserve_users = (
            await db.scalars(select(User).where(User.basket == reserve_basket).order_by(User.created_at))
        ).all()

    is_empty = (
        not direct_invite_users
        if view == "direct_invites"
        else (not main_users and not reserve_users)
    )

    return templates.TemplateResponse(
        request,
        "participants.html",
        template_context(
            request,
            basket=main_basket,
            view=view,
            basket_pairs=basket_pairs,
            main_users=main_users,
            reserve_users=reserve_users,
            direct_invite_users=direct_invite_users,
            is_empty=is_empty,
        ),
    )


@router.get("/tournament", response_class=HTMLResponse)
async def tournament_page(request: Request, db: AsyncSession = Depends(get_db)):
    # Отдаем единую турнирную сетку со всеми этапами.
    tournament_started = await get_tournament_started(db)

    groups = list(
        (
            await db.scalars(
                select(TournamentGroup)
                .where(TournamentGroup.stage == "group_stage")
                .options(selectinload(TournamentGroup.members).selectinload(GroupMember.user))
                .order_by(TournamentGroup.name)
            )
        ).all()
    )
    playoff_stages = await get_playoff_stages_with_data(db) if tournament_started else []

    direct_invite_ids = list(
        (
            await db.scalars(
                select(User.id)
                .where(User.direct_invite_stage == "stage_2")
                .order_by(User.created_at)
            )
        ).all()
    )

    users = list((await db.scalars(select(User))).all())
    user_by_id = {user.id: user for user in users}
    stage_columns = build_bracket_columns(groups, playoff_stages, user_by_id, direct_invite_ids)

    lang = get_lang(request.cookies.get("lang"))
    current_stage_display = resolve_current_stage_label(lang, playoff_stages, tournament_started)
    stage_order_keys = TOURNAMENT_STAGE_KEYS_ORDER
    active_key = "group_stage"
    if tournament_started:
        active_playoff = get_active_playoff_stage(playoff_stages, PLAYOFF_STAGE_KEYS_ORDER)
        if active_playoff:
            active_key = active_playoff.key
    ordered_keys = build_stage_display_order(active_key, stage_order_keys)
    columns_by_key = {column["key"]: column for column in stage_columns}
    ordered_stage_columns = [columns_by_key[key] for key in ordered_keys if key in columns_by_key]
    playoff_empty_active_stage_alert = get_empty_active_stage_alert(playoff_stages)

    return templates.TemplateResponse(
        request,
        "tournament.html",
        template_context(
            request,
            groups=groups,
            playoff_stages=playoff_stages,
            stage_columns=stage_columns,
            ordered_stage_columns=ordered_stage_columns,
            current_stage_display=current_stage_display,
            show_groups=tournament_started,
            playoff_empty_active_stage_alert=playoff_empty_active_stage_alert,
        ),
    )


@router.get("/donate", response_class=HTMLResponse)
async def donate_page(request: Request, db: AsyncSession = Depends(get_db)):
    # Отдаем страницу донатов.
    donation_links = (await db.scalars(select(DonationLink).where(DonationLink.is_active.is_(True)).order_by(DonationLink.sort_order, DonationLink.id))).all()
    donation_methods = (await db.scalars(select(DonationMethod).where(DonationMethod.is_active.is_(True)).order_by(DonationMethod.method_type, DonationMethod.sort_order, DonationMethod.id))).all()
    prize_pool_entries = (await db.scalars(select(PrizePoolEntry).order_by(PrizePoolEntry.sort_order, PrizePoolEntry.id))).all()
    donors = (await db.scalars(select(Donor).order_by(Donor.sort_order, Donor.id))).all()
    return templates.TemplateResponse(
        request,
        "donate.html",
        template_context(
            request,
            donation_links=donation_links,
            donation_methods=donation_methods,
            prize_pool_entries=prize_pool_entries,
            donors=donors,
        ),
    )


@router.get("/rules", response_class=HTMLResponse)
async def rules_page(request: Request, db: AsyncSession = Depends(get_db)):
    # Отдаем страницу правил.
    rules_content = await get_or_create_rules_content(db)
    await db.commit()
    return templates.TemplateResponse(request, "rules.html", template_context(request, rules_content=rules_content))


@router.get("/archive", response_class=HTMLResponse)
async def archive_page(request: Request, db: AsyncSession = Depends(get_db)):
    # Отдаем страницу архива.
    archive_entries = (await db.scalars(select(ArchiveEntry).where(ArchiveEntry.is_published.is_(True)).order_by(ArchiveEntry.sort_order, ArchiveEntry.id))).all()
    return templates.TemplateResponse(request, "archive.html", template_context(request, archive_entries=archive_entries))


@router.get("/admin/login", response_class=HTMLResponse)
async def admin_login_page(request: Request):
    if is_admin_session(request.cookies.get(ADMIN_SESSION_COOKIE)):
        return RedirectResponse(url="/admin", status_code=303)
    return templates.TemplateResponse(request, "admin_login.html", template_context(request))


@router.post("/admin/login")
async def admin_login(request: Request, admin_key: str = Form(...)):
    if admin_key != settings.admin_key:
        return redirect_with_msg("/admin/login", "msg_admin_login_failed")
    response = RedirectResponse(url="/admin", status_code=303)
    response.set_cookie(
        ADMIN_SESSION_COOKIE,
        create_admin_session_cookie(),
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 12,
    )
    return response


@router.get("/admin/logout")
@router.post("/admin/logout")
async def admin_logout():
    response = RedirectResponse(url="/admin/login", status_code=303)
    response.delete_cookie(ADMIN_SESSION_COOKIE)
    return response


@router.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request, db: AsyncSession = Depends(get_db)):
    judge_setting = await db.scalar(select(SiteSetting).where(SiteSetting.key == "judge_login_token"))
    judge_login_token = (judge_setting.value if judge_setting else "")
    judge_login_url = ""
    if judge_login_token:
        judge_login_url = str(request.url_for("admin_page")).rstrip("/") + f"?judge_token={judge_login_token}"

    manual_draw_users = (
        await db.scalars(
            select(User)
            .where(User.basket != Basket.INVITED.value)
            .order_by(User.nickname.asc(), User.created_at.desc())
    )
    ).all()
    user_rows = (await db.execute(select(User.id, User.nickname))).all()
    users_by_id = {user_id: nickname for user_id, nickname in user_rows}
    stages = (await db.scalars(select(TournamentStage).order_by(TournamentStage.id))).all()
    playoff_stages = await get_playoff_stages_with_data(db)
    active_playoff_stage = get_active_playoff_stage(playoff_stages)

    def _is_stage_finished(stage: PlayoffStage) -> bool:
        participants_group_numbers = {
            get_stage_group_number_by_seed(participant.seed)
            for participant in stage.participants
        }
        if not participants_group_numbers:
            return False

        for group_number in participants_group_numbers:
            group_matches = [match for match in stage.matches if match.group_number == group_number]
            if not group_matches:
                return False
            if not any(match.state == "finished" for match in group_matches):
                return False
        return True

    playoff_stage_by_key = {stage.key: stage for stage in playoff_stages}
    stage_progression_keys = PLAYOFF_STAGE_KEYS_ORDER
    tournament_started = await get_tournament_started(db)
    group_stage_groups = list(
        (
            await db.scalars(
                select(TournamentGroup)
                .where(TournamentGroup.stage == "group_stage")
                .options(selectinload(TournamentGroup.members).selectinload(GroupMember.user))
                .order_by(TournamentGroup.name)
            )
        ).all()
    )
    draw_exists = bool(group_stage_groups)
    groups_count = len(group_stage_groups)
    draw_applied = await get_draw_applied(db)
    is_draw_valid, invalid_draw_reason = await validate_group_draw_integrity(db)
    if is_draw_valid:
        invalid_draw_reason = None
    group_stage_finished = bool(playoff_stages)
    active_stage_key = None
    if not tournament_started:
        active_stage_key = None
    elif not group_stage_finished:
        active_stage_key = "group_stage"
    else:
        for stage_key in stage_progression_keys:
            stage = playoff_stage_by_key.get(stage_key)
            if not stage:
                continue
            if stage.is_started and not _is_stage_finished(stage):
                active_stage_key = stage_key
                break

        if active_stage_key is None:
            # Не перескакиваем на следующую стадию до явного запуска через Stage Finish.
            # Показываем первую незавершённую стадию только среди уже стартовавших.
            for stage_key in stage_progression_keys:
                stage = playoff_stage_by_key.get(stage_key)
                if stage and stage.is_started and not _is_stage_finished(stage):
                    active_stage_key = stage_key
                    break

        if active_stage_key is None and playoff_stages:
            started_stage = get_active_playoff_stage(playoff_stages, stage_progression_keys)
            active_stage_key = started_stage.key if started_stage else get_default_playoff_stage_key(playoff_stages, stage_progression_keys)

    show_group_stage_controls = active_stage_key == "group_stage"
    groups = group_stage_groups if show_group_stage_controls else []
    draw_groups = group_stage_groups
    group_stage_finish_ready, group_stage_finish_status, group_stage_games_played = await get_group_stage_completion_status(db)
    group_stage_games_summary = [
        {
            "name": group.name,
            "games_played": group_stage_games_played.get(group.id, 0),
        }
        for group in group_stage_groups
    ]
    group_user_choices = {
        group.id: [
            {
                "user_id": member.user_id,
                "nickname": (member.user.nickname if member.user else users_by_id.get(member.user_id, f"#{member.user_id}")),
            }
            for member in sorted(group.members, key=lambda item: item.seat)
        ]
        for group in groups
    }
    group_stage_table_members = {
        group.id: [
            {
                "user_id": member.user_id,
                "nickname": (member.user.nickname if member.user else users_by_id.get(member.user_id, f"#{member.user_id}")),
                "total_points": member.total_points or 0,
                "first_places": member.first_places or 0,
                "top2_4_finishes": max((member.top4_finishes or 0) - (member.first_places or 0), 0),
                "eighth_places": member.eighth_places or 0,
            }
            for member in sort_members_for_table(list(group.members))
        ]
        for group in groups
    }
    playoff_stage_participants = {
        stage.id: [
            {
                "user_id": participant.user_id,
                "nickname": users_by_id.get(participant.user_id, f"#{participant.user_id}"),
                "points": participant.points,
                "seed": participant.seed,
                "group_number": get_stage_group_number_by_seed(participant.seed),
                "group_label": get_stage_group_label(stage.key, get_stage_group_number_by_seed(participant.seed)),
                "games_played": next(
                    (
                        max(match.game_number - 1, 0)
                        for match in stage.matches
                        if match.group_number == get_stage_group_number_by_seed(participant.seed)
                    ),
                    0,
                ),
                "game_limit": get_game_limit(stage.key) or "special",
            }
            for participant in sorted(
                stage.participants,
                key=lambda p: (get_stage_group_number_by_seed(p.seed), p.seed, -p.points, p.user_id),
            )
        ]
        for stage in playoff_stages
    }
    playoff_stage_groups: dict[int, list[dict[str, object]]] = {}
    for stage in playoff_stages:
        stage_group_numbers = (
            get_stage_group_numbers(stage.key, stage.stage_size, len(stage.participants))
            or sorted(
                {
                    *{get_stage_group_number_by_seed(item.seed) for item in stage.participants},
                    *{match.group_number for match in stage.matches},
                }
            )
        )
        groups_payload: list[dict[str, object]] = []
        for group_number in stage_group_numbers:
            group_matches = [match for match in stage.matches if match.group_number == group_number]
            active_match = max(group_matches, key=lambda match: match.game_number, default=None)
            groups_payload.append(
                {
                    "group_number": group_number,
                    "group_label": get_stage_group_label(stage.key, group_number),
                    "games_played": next(
                        (max(match.game_number - 1, 0) for match in stage.matches if match.group_number == group_number),
                        0,
                    ),
                    "current_game": next(
                        (max(match.game_number, 1) for match in stage.matches if match.group_number == group_number),
                        1,
                    ),
                    "game_limit": get_game_limit(stage.key) or "special",
                    "lobby_password": active_match.lobby_password if active_match else "0000",
                    "schedule_text": active_match.schedule_text if active_match else "TBD",
                    "participants": [
                        {
                            "user_id": participant.user_id,
                            "nickname": users_by_id.get(participant.user_id, f"#{participant.user_id}"),
                            "points": participant.points,
                            "is_winner_eligible": (participant.points or 0) >= 22,
                            "total_points": participant.points or 0,
                            "first_places": participant.wins or 0,
                            "top2_4_finishes": max((participant.top4_finishes or 0) - (participant.wins or 0), 0),
                            "eighth_places": getattr(participant, "eighth_places", 0) or 0,
                            "group_number": group_number,
                            "group_label": get_stage_group_label(stage.key, group_number),
                        }
                        for participant in sorted(
                            [
                                item
                                for item in stage.participants
                                if get_stage_group_number_by_seed(item.seed) == group_number
                            ],
                            key=playoff_sort_key,
                            reverse=True,
                        )
                    ],
                }
            )
        playoff_stage_groups[stage.id] = groups_payload
    current_playoff_stage = playoff_stage_by_key.get(active_stage_key) if active_stage_key else None
    current_playoff_stage_config = (
        get_admin_playoff_stage_config(current_playoff_stage.key) if current_playoff_stage else None
    )
    current_stage_groups = playoff_stage_groups.get(current_playoff_stage.id, []) if current_playoff_stage else []
    current_stage_participants = playoff_stage_participants.get(current_playoff_stage.id, []) if current_playoff_stage else []
    playoff_stage_finish_progress: list[dict[str, int | str]] = []
    playoff_stage_finish_ready = False
    playoff_stage_finish_progress_limit: int | str = GROUP_STAGE_GAME_LIMIT
    if current_playoff_stage:
        playoff_stage_finish_progress, playoff_stage_finish_ready = build_playoff_stage_finish_status(current_playoff_stage)
        playoff_stage_finish_progress_limit = GROUP_STAGE_GAME_LIMIT if is_limited_stage(current_playoff_stage.key) else "∞"
    playoff_empty_active_stage_alert = get_empty_active_stage_alert(playoff_stages)
    registration_setting = await db.scalar(select(SiteSetting).where(SiteSetting.key == "registration_open"))
    registration_open = (registration_setting.value == "1") if registration_setting else True
    tournament_started_setting = await db.scalar(select(SiteSetting).where(SiteSetting.key == "tournament_started"))
    tournament_started = (tournament_started_setting.value == "1") if tournament_started_setting else False
    donation_links = (await db.scalars(select(DonationLink).order_by(DonationLink.sort_order, DonationLink.id))).all()
    donation_methods = (await db.scalars(select(DonationMethod).order_by(DonationMethod.method_type, DonationMethod.sort_order, DonationMethod.id))).all()
    prize_pool_entries = (await db.scalars(select(PrizePoolEntry).order_by(PrizePoolEntry.sort_order, PrizePoolEntry.id))).all()
    donors = (await db.scalars(select(Donor).order_by(Donor.sort_order, Donor.id))).all()
    rules_content = await get_or_create_rules_content(db)
    archive_entries = (await db.scalars(select(ArchiveEntry).order_by(ArchiveEntry.sort_order, ArchiveEntry.id))).all()
    chat_settings = await get_or_create_chat_settings(db)
    chat_messages = (
        await db.scalars(select(ChatMessage).order_by(desc(ChatMessage.id)).limit(50))
    ).all()
    await db.commit()
    return templates.TemplateResponse(
        request,
        "admin.html",
        template_context(
            request,
            stages=stages,
            groups=groups,
            draw_groups=draw_groups,
            playoff_stages=playoff_stages,
            score_hint="user_id1,user_id2,...,user_id8",
            registration_open=registration_open,
            tournament_started=tournament_started,
            draw_applied=draw_applied,
            draw_exists=draw_exists,
            groups_count=groups_count,
            invalid_draw_reason=invalid_draw_reason,
            donation_links=donation_links,
            donation_methods=donation_methods,
            prize_pool_entries=prize_pool_entries,
            donors=donors,
            rules_content=rules_content,
            archive_entries=archive_entries,
            chat_settings=chat_settings,
            chat_messages=chat_messages,
            judge_login_url=judge_login_url,
            manual_draw_users=manual_draw_users,
            group_user_choices=group_user_choices,
            group_stage_table_members=group_stage_table_members,
            playoff_stage_participants=playoff_stage_participants,
            playoff_stage_groups=playoff_stage_groups,
            active_playoff_stage=active_playoff_stage,
            active_stage_key=active_stage_key,
            current_playoff_stage=current_playoff_stage,
            current_playoff_stage_config=current_playoff_stage_config,
            current_stage_groups=current_stage_groups,
            current_stage_participants=current_stage_participants,
            playoff_stage_finish_progress=playoff_stage_finish_progress,
            playoff_stage_finish_ready=playoff_stage_finish_ready,
            playoff_stage_finish_progress_limit=playoff_stage_finish_progress_limit,
            show_group_stage_controls=show_group_stage_controls,
            group_stage_game_limit=GROUP_STAGE_GAME_LIMIT,
            group_stage_finish_ready=group_stage_finish_ready,
            group_stage_finish_status=group_stage_finish_status,
            group_stage_games_summary=group_stage_games_summary,
            playoff_empty_active_stage_alert=playoff_empty_active_stage_alert,
        ),
    )


@router.get("/admin/users", response_class=HTMLResponse)
async def admin_users_page(request: Request, db: AsyncSession = Depends(get_db)):
    users = (await db.scalars(select(User).order_by(desc(User.created_at)).limit(300))).all()
    allowed_direct_invite_stages = [
        "stage_2",
        "stage_final",
    ]

    group_points_rows = (await db.execute(select(GroupMember.user_id, func.max(GroupMember.total_points)).group_by(GroupMember.user_id))).all()
    playoff_points_rows = (await db.execute(select(PlayoffParticipant.user_id, func.max(PlayoffParticipant.points)).group_by(PlayoffParticipant.user_id))).all()
    points_by_user: dict[int, int] = {int(user_id): int(points or 0) for user_id, points in group_points_rows}
    for user_id, points in playoff_points_rows:
        normalized_user_id = int(user_id)
        points_by_user[normalized_user_id] = max(points_by_user.get(normalized_user_id, 0), int(points or 0))

    draw_applied = await get_draw_applied(db)
    tournament_started = await get_tournament_started(db)
    show_group_sections = draw_applied and tournament_started

    users_by_id: dict[int, User] = {user.id: user for user in users}
    group_sections: list[dict[str, object]] = []
    grouped_user_ids: set[int] = set()

    if show_group_sections:
        stage_groups = (
            await db.scalars(
                select(TournamentGroup)
                .where(TournamentGroup.stage == "group_stage")
                .options(selectinload(TournamentGroup.members).selectinload(GroupMember.user))
                .order_by(TournamentGroup.name)
            )
        ).all()
        for group in stage_groups:
            members = sorted(group.members, key=lambda member: (member.seat, member.id))
            section_users = [member.user for member in members if member.user and member.user.id in users_by_id]
            group_sections.append({"title": f"Группа {group.name}", "users": section_users, "group_id": group.id})
            grouped_user_ids.update(user.id for user in section_users)

        extra_users = [user for user in users if user.id not in grouped_user_ids]
        if extra_users:
            group_sections.append({"title": "Вне групп", "users": extra_users, "group_id": None})

    if not group_sections:
        group_sections.append({"title": "Список участников", "users": users, "group_id": None})

    return templates.TemplateResponse(
        request,
        "admin_users.html",
        template_context(
            request,
            users=users,
            basket_values=[basket.value for basket in Basket],
            points_by_user=points_by_user,
            allowed_direct_invite_stages=allowed_direct_invite_stages,
            group_sections=group_sections,
            show_group_sections=show_group_sections,
        ),
    )


async def _update_user_allowed_fields(
    db: AsyncSession,
    *,
    user_id: int,
    nickname: str,
    basket: str,
    direct_invite_stage: str | None,
    manual_points: int | None = None,
) -> RedirectResponse:
    user = await db.get(User, user_id)
    if not user:
        return redirect_with_admin_users_msg("msg_operation_failed")

    try:
        validated_data = _validate_user_update_payload(
            nickname=nickname,
            basket=basket,
            direct_invite_stage=direct_invite_stage,
        )
    except ValueError:
        return redirect_with_admin_users_msg("msg_operation_failed")

    for field_name, field_value in validated_data.items():
        if field_name not in ALLOWED_USER_UPDATE_FIELDS:
            continue
        setattr(user, field_name, field_value)

    if manual_points is not None:
        normalized_points = max(0, int(manual_points))
        group_members = list((await db.scalars(select(GroupMember).where(GroupMember.user_id == user_id))).all())
        for member in group_members:
            member.total_points = normalized_points

        playoff_participants = list((await db.scalars(select(PlayoffParticipant).where(PlayoffParticipant.user_id == user_id))).all())
        for participant in playoff_participants:
            participant.points = normalized_points

    await db.commit()
    return redirect_with_admin_users_msg("msg_status_ok")


@router.get("/admin/chat", response_class=HTMLResponse)
async def admin_chat_page(request: Request, db: AsyncSession = Depends(get_db)):
    chat_settings = await get_or_create_chat_settings(db)
    chat_messages = (
        await db.scalars(select(ChatMessage).order_by(desc(ChatMessage.id)).limit(100))
    ).all()
    return templates.TemplateResponse(
        request,
        "admin_chat.html",
        template_context(
            request,
            chat_settings=chat_settings,
            chat_messages=chat_messages,
        ),
    )


@router.get("/admin/content", response_class=HTMLResponse)
async def admin_content_page(request: Request, db: AsyncSession = Depends(get_db)):
    rules_content = await get_or_create_rules_content(db)
    donation_links = (await db.scalars(select(DonationLink).order_by(DonationLink.sort_order, DonationLink.id))).all()
    donation_methods = (await db.scalars(select(DonationMethod).order_by(DonationMethod.sort_order, DonationMethod.id))).all()
    prize_pool_entries = (await db.scalars(select(PrizePoolEntry).order_by(PrizePoolEntry.sort_order, PrizePoolEntry.id))).all()
    donors = (await db.scalars(select(Donor).order_by(Donor.sort_order, Donor.id))).all()
    archive_entries = (await db.scalars(select(ArchiveEntry).order_by(ArchiveEntry.sort_order, ArchiveEntry.id))).all()
    return templates.TemplateResponse(
        request,
        "admin_content.html",
        template_context(
            request,
            rules_content=rules_content,
            donation_links=donation_links,
            donation_methods=donation_methods,
            prize_pool_entries=prize_pool_entries,
            donors=donors,
            archive_entries=archive_entries,
        ),
    )


@router.get("/admin/emergency", response_class=HTMLResponse)
async def admin_emergency_page(request: Request, db: AsyncSession = Depends(get_db)):
    manual_draw_users = (
        await db.scalars(
            select(User)
            .where(User.basket != Basket.INVITED.value)
            .order_by(User.nickname.asc(), User.created_at.desc())
        )
    ).all()
    playoff_stages = await get_playoff_stages_with_data(db)
    return templates.TemplateResponse(
        request,
        "admin_emergency.html",
        template_context(
            request,
            playoff_stages=playoff_stages,
            manual_draw_users=manual_draw_users,
        ),
    )


@router.post("/admin/user/update")
async def admin_update_user(
    user_id: int = Form(...),
    nickname: str = Form(...),
    basket: str = Form(...),
    direct_invite_stage: str | None = Form(default=None),
    manual_points: int | None = Form(default=None),
    db: AsyncSession = Depends(get_db),
):
    # Атомарно обновляем разрешенные поля пользователя из админ-панели.
    return await _update_user_allowed_fields(
        db,
        user_id=user_id,
        nickname=nickname,
        basket=basket,
        direct_invite_stage=direct_invite_stage,
        manual_points=manual_points,
    )


@router.post("/admin/user/basket")
async def admin_update_user_basket(
    user_id: int = Form(...),
    basket: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    # Сохраняем обратную совместимость: обновление корзины делегируется общей логике.
    user = await db.get(User, user_id)
    if not user:
        return redirect_with_admin_users_msg("msg_operation_failed")
    return await _update_user_allowed_fields(
        db,
        user_id=user_id,
        nickname=user.nickname,
        basket=basket,
        direct_invite_stage=user.direct_invite_stage,
        manual_points=None,
    )


@router.post("/admin/stage")
async def admin_update_stage(
    key: str = Form(...),
    title_ru: str = Form(...),
    title_en: str = Form(...),
    date_text: str = Form(...),
    is_active: bool = Form(default=False),
    db: AsyncSession = Depends(get_db),
):
    # Обновляем этапы турнира из админ-панели.
    row = await db.scalar(select(TournamentStage).where(TournamentStage.key == key))
    if not row:
        row = TournamentStage(key=key, title_ru=title_ru, title_en=title_en)
        db.add(row)
    row.title_ru = title_ru
    row.title_en = title_en
    row.date_text = date_text
    row.is_active = is_active
    await db.commit()
    return redirect_with_admin_msg("msg_status_ok")


@router.post("/admin/registration")
async def admin_registration_toggle(
    registration_open: bool = Form(default=False),
    db: AsyncSession = Depends(get_db),
):
    # Переключаем состояние регистрации вручную.
    row = await db.scalar(select(SiteSetting).where(SiteSetting.key == "registration_open"))
    if not row:
        row = SiteSetting(key="registration_open", value="1")
        db.add(row)
    row.value = "1" if registration_open else "0"
    await db.commit()
    return redirect_with_admin_msg("msg_status_ok")


@router.post("/admin/tournament/start")
async def admin_start_tournament(db: AsyncSession = Depends(get_db)):
    groups_count = await db.scalar(
        select(func.count(TournamentGroup.id)).where(TournamentGroup.stage == "group_stage")
    )
    if not groups_count:
        return redirect_with_admin_msg("msg_operation_failed", details="draw_not_created")

    draw_applied = await get_draw_applied(db)
    if not draw_applied:
        return redirect_with_admin_msg("msg_operation_failed", details="draw_not_applied")

    is_draw_valid, draw_issue = await validate_group_draw_integrity(db)
    if not is_draw_valid:
        return redirect_with_admin_msg("msg_operation_failed", details=f"invalid_draw:{draw_issue}")

    tournament_started_row = await db.scalar(select(SiteSetting).where(SiteSetting.key == "tournament_started"))
    if not tournament_started_row:
        tournament_started_row = SiteSetting(key="tournament_started", value="0")
        db.add(tournament_started_row)
    tournament_started_row.value = "1"

    registration_open_row = await db.scalar(select(SiteSetting).where(SiteSetting.key == "registration_open"))
    if not registration_open_row:
        registration_open_row = SiteSetting(key="registration_open", value="1")
        db.add(registration_open_row)
    registration_open_row.value = "0"

    await db.commit()
    return redirect_with_admin_msg("msg_status_ok")


@router.post("/admin/invite")
async def admin_invite_user(
    steam_input: str = Form(...),
    nickname: str = Form(...),
    telegram: str = Form(default=""),
    discord: str = Form(default=""),
    invite_type: str = Form(default="regular"),
    db: AsyncSession = Depends(get_db),
):
    # Добавляем участника вручную в корзину invited.
    steam_id = await normalize_steam_id(steam_input)
    if not steam_id:
        return redirect_with_admin_msg("msg_invalid_steam_id")

    exists = await db.scalar(select(User).where(User.steam_id == steam_id))
    if exists:
        return redirect_with_admin_msg("msg_user_exists")

    profile = await fetch_autochess_data(steam_id)
    direct_invite_stage = "stage_2" if invite_type == "stage_2" else None
    if direct_invite_stage:
        direct_invite_count = await db.scalar(
            select(func.count(User.id)).where(User.direct_invite_stage == direct_invite_stage)
        )
        if (direct_invite_count or 0) >= 11:
            return redirect_with_admin_msg("msg_operation_failed")
    user = User(
        nickname=nickname,
        steam_input=steam_input,
        steam_id=steam_id,
        game_nickname=profile["game_nickname"],
        current_rank=profile["current_rank"],
        highest_rank=profile["highest_rank"],
        telegram=telegram or None,
        discord=discord or None,
        basket=Basket.INVITED.value,
        direct_invite_stage=direct_invite_stage,
        extra_data=json.dumps(profile["raw"], ensure_ascii=False),
    )
    db.add(user)
    await db.commit()
    return redirect_with_admin_msg("msg_invited_added")


@router.post("/admin/draw/auto")
async def admin_auto_draw(db: AsyncSession = Depends(get_db)):
    # Запускаем автоматическую жеребьевку группового этапа.
    ok, message = await create_auto_draw(db)
    if ok:
        await set_draw_applied(db, False)
        await db.commit()
    return redirect_with_admin_msg("msg_status_ok" if ok else "msg_status_warn", details=None if ok else message)




@router.post("/admin/draw/manual")
async def admin_manual_draw(
    group_count: int = Form(default=1),
    user_ids: str = Form(default=""),
    user_ids_list: list[str] | None = Form(default=None, alias="user_ids[]"),
    layout_json: str = Form(default=""),
    db: AsyncSession = Depends(get_db),
):
    try:
        if layout_json.strip():
            raw_layout = json.loads(layout_json)
            await create_manual_draw_from_layout(db, raw_layout)
        else:
            parsed_user_ids = parse_manual_draw_user_ids(user_ids_list if user_ids_list else user_ids)
            await create_manual_draw(
                db,
                group_count=group_count,
                user_ids=parsed_user_ids,
            )
        await set_draw_applied(db, False)
        await db.commit()
        return redirect_with_admin_msg("msg_status_ok")
    except ManualDrawValidationError as exc:
        return redirect_with_admin_msg("msg_operation_failed", details=exc.details)
    except json.JSONDecodeError:
        return redirect_with_admin_msg("msg_operation_failed", details="invalid_layout")
    except ValueError:
        return redirect_with_admin_msg("msg_operation_failed", details="invalid_layout")
    except Exception:  # noqa: BLE001
        return redirect_with_admin_msg("msg_operation_failed")

@router.post("/admin/group/password")
async def admin_group_password(
    group_id: int = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    # Обновляем пароль лобби конкретной группы.
    group = await db.scalar(select(TournamentGroup).where(TournamentGroup.id == group_id))
    if not group:
        return redirect_with_admin_msg("msg_group_not_found")

    normalized_password = (password or "").strip()
    if not re.fullmatch(r"^[0-9]{4}$", normalized_password):
        return redirect_with_admin_msg("msg_invalid_lobby_password")

    group.lobby_password = normalized_password
    await db.commit()
    return redirect_with_admin_msg("msg_lobby_password_updated")


@router.post("/admin/group/schedule")
async def admin_group_schedule(
    group_id: int = Form(...),
    schedule_text: str = Form(default=""),
    scheduled_at: str = Form(default=""),
    db: AsyncSession = Depends(get_db),
):
    group = await db.scalar(select(TournamentGroup).where(TournamentGroup.id == group_id))
    if not group:
        return redirect_with_admin_msg("msg_group_not_found")

    parsed_scheduled_at = None
    if scheduled_at.strip():
        try:
            parsed_scheduled_at = datetime.fromisoformat(scheduled_at.strip())
        except ValueError:
            parsed_scheduled_at = None

    group.scheduled_at = parsed_scheduled_at
    group.schedule_text = schedule_text.strip() or "TBD"
    await db.commit()
    return redirect_with_admin_msg("msg_status_ok")


@router.post("/admin/playoff/group/password")
async def admin_playoff_group_password(
    stage_id: int = Form(...),
    group_number: int = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    stage = await _get_playoff_stage(db, stage_id)
    if not stage:
        return redirect_with_admin_msg("msg_invalid_playoff_stage")

    match = await db.scalar(
        select(PlayoffMatch)
        .where(PlayoffMatch.stage_id == stage_id, PlayoffMatch.group_number == group_number)
    )
    if not match:
        return redirect_with_admin_msg("msg_operation_failed")

    stage_config = get_admin_playoff_stage_config(stage.key)
    if stage_config.game_limit is not None and match.game_number > stage_config.game_limit:
        return redirect_with_admin_msg("msg_operation_failed", details="group_games_not_completed")

    normalized_password = (password or "").strip()
    if not re.fullmatch(r"^[0-9]{4}$", normalized_password):
        return redirect_with_admin_msg("msg_invalid_lobby_password")

    match.lobby_password = normalized_password
    await db.commit()
    return redirect_with_admin_msg("msg_lobby_password_updated")


@router.post("/admin/playoff/group/schedule")
async def admin_playoff_group_schedule(
    stage_id: int = Form(...),
    group_number: int = Form(...),
    schedule_text: str = Form(default=""),
    scheduled_at: str = Form(default=""),
    db: AsyncSession = Depends(get_db),
):
    stage = await _get_playoff_stage(db, stage_id)
    if not stage:
        return redirect_with_admin_msg("msg_invalid_playoff_stage")

    match = await db.scalar(
        select(PlayoffMatch)
        .where(PlayoffMatch.stage_id == stage_id, PlayoffMatch.group_number == group_number)
    )
    if not match:
        return redirect_with_admin_msg("msg_operation_failed")

    stage_config = get_admin_playoff_stage_config(stage.key)
    if stage_config.game_limit is not None and match.game_number > stage_config.game_limit:
        return redirect_with_admin_msg("msg_operation_failed", details="group_games_not_completed")

    parsed_scheduled_at = None
    if scheduled_at.strip():
        try:
            parsed_scheduled_at = datetime.fromisoformat(scheduled_at.strip())
        except ValueError:
            parsed_scheduled_at = None

    match.scheduled_at = parsed_scheduled_at
    match.schedule_text = schedule_text.strip() or "TBD"
    await db.commit()
    return redirect_with_admin_msg("msg_status_ok")


@router.post("/admin/draw/apply")
async def admin_apply_draw(db: AsyncSession = Depends(get_db)):
    groups_count = await db.scalar(
        select(func.count(TournamentGroup.id)).where(TournamentGroup.stage == "group_stage")
    )
    if not groups_count:
        return redirect_with_admin_msg("msg_operation_failed", details="draw_not_created")

    is_valid, details = await validate_group_draw_integrity(db)
    if not is_valid:
        return redirect_with_admin_msg("msg_operation_failed", details=f"invalid_draw:{details}")
    await set_draw_applied(db, True)
    await db.commit()
    return redirect_with_admin_msg("msg_status_ok", details=f"draw_applied_groups:{groups_count}")


@router.post("/admin/group/promote-manual")
async def admin_promote_group_member_manual(
    group_id: int = Form(...),
    user_id: int = Form(...),
    target_stage_id: int = Form(...),
    db: AsyncSession = Depends(get_db),
):
    if not await _playoff_stage_exists(db, target_stage_id):
        return redirect_with_admin_msg("msg_invalid_playoff_stage")
    try:
        await promote_group_member_to_stage(db, group_id, user_id, target_stage_id)
        return redirect_with_admin_msg("msg_player_moved")
    except Exception as exc:  # noqa: BLE001
        return redirect_with_admin_msg("msg_operation_failed")


@router.post("/admin/group/score")
async def admin_group_score(
    group_id: int = Form(...),
    user_ids: list[str] = Form(..., alias="user_ids[]"),
    places: list[str] = Form(..., alias="places[]"),
    db: AsyncSession = Depends(get_db),
):
    """Принимает распределение мест в игре и начисляет очки участникам выбранной группы."""
    try:
        if len(user_ids) != len(places):
            raise ValueError("Некорректное количество полей")

        placements_map: dict[int, int] = {}
        for raw_user_id, raw_place in zip(user_ids, places):
            user_id = int(raw_user_id)
            place = int(raw_place)
            if place < 1 or place > 8:
                raise ValueError("Место должно быть в диапазоне 1..8")
            if user_id in placements_map:
                raise ValueError("Дублирующийся участник")
            placements_map[user_id] = place

        if len(placements_map) != 8:
            raise ValueError("Нужно передать 8 участников")

        unique_places = set(placements_map.values())
        if unique_places != set(range(1, 9)):
            raise ValueError("Места должны быть уникальны и покрывать диапазон 1..8")

        ordered_user_ids = [
            user_id
            for user_id, place in sorted(placements_map.items(), key=lambda item: item[1])
        ]
        await apply_game_results(db, group_id, ordered_user_ids)
        return redirect_with_admin_msg("msg_game_saved")
    except Exception as exc:  # noqa: BLE001
        return redirect_with_admin_msg("msg_operation_failed")


@router.post("/admin/group-stage/finish")
async def admin_finish_group_stage(db: AsyncSession = Depends(get_db)):
    is_completed, status, _ = await get_group_stage_completion_status(db)
    if not is_completed:
        return redirect_with_admin_msg("msg_operation_failed", details=status)

    generated, details = await generate_playoff_from_groups(db)
    if not generated:
        return redirect_with_admin_msg("msg_operation_failed", details=details)

    group_stage = await db.scalar(select(TournamentStage).where(TournamentStage.key == "group_stage"))
    if group_stage:
        group_stage.is_active = False

    stage_2 = await db.scalar(select(TournamentStage).where(TournamentStage.key == "stage_2"))
    if stage_2:
        stage_2.is_active = True

    await db.commit()
    return redirect_with_admin_msg("msg_status_ok", details="group_stage_finished")


@router.post("/admin/playoff/generate")
async def admin_generate_playoff(db: AsyncSession = Depends(get_db)):
    return redirect_with_admin_msg("msg_operation_failed", details="use_group_finish_flow")


@router.post("/admin/playoff/start")
async def admin_start_playoff(
    stage_id: int = Form(...),
    db: AsyncSession = Depends(get_db),
):
    return redirect_with_admin_msg("msg_operation_failed", details="use_group_finish_flow")


@router.post("/admin/playoff/promote")
async def admin_promote_playoff(
    stage_id: int = Form(...),
    top_n: int = Form(...),
    db: AsyncSession = Depends(get_db),
):
    return redirect_with_admin_msg("msg_operation_failed", details="use_group_finish_flow")


@router.post("/admin/playoff/stage-2/shuffle")
async def admin_shuffle_stage_2(db: AsyncSession = Depends(get_db)):
    try:
        await shuffle_stage_2_participants(db)
        return redirect_with_admin_msg("msg_status_ok", details="stage_2_shuffled")
    except Exception:  # noqa: BLE001
        return redirect_with_admin_msg("msg_operation_failed", details="stage_2_shuffle_forbidden")




@router.post("/admin/playoff/debug/simulate-3-games")
async def admin_debug_simulate_three_random_playoff_games(
    stage_id: int = Form(...),
    db: AsyncSession = Depends(get_db),
):
    """Отладочно симулирует 3 случайные игры для каждой полной группы (8 игроков) в этапе плей-офф.

    Поддерживаются только лимитированные стадии плей-офф: ``stage_2`` и
    ``stage_1_4``. Для остальных стадий сервисный вызов не вносит изменений.

    Возвращаемые ошибки на уровне редиректа:
    - ``msg_invalid_playoff_stage`` — если этап с переданным ``stage_id`` не найден;
    - ``msg_operation_failed`` c ``details=debug_simulate_3_games_failed`` — если во время
      симуляции произошла ошибка в сервисном слое.
    """
    stage = await _get_playoff_stage(db, stage_id)
    if not stage:
        return redirect_with_admin_msg("msg_invalid_playoff_stage")
    stage_config = get_admin_playoff_stage_config(stage.key)
    if not stage_config.can_debug_simulate:
        return redirect_with_admin_msg("msg_operation_failed", details="stage_action_not_allowed")

    try:
        await simulate_three_random_games_for_stage(db, stage_id)
        return redirect_with_admin_msg("msg_status_ok", details="debug_simulate_3_games_done")
    except Exception:  # noqa: BLE001
        return redirect_with_admin_msg("msg_operation_failed", details="debug_simulate_3_games_failed")

@router.post("/admin/playoff/move")
async def admin_move_playoff_player(
    from_stage_id: int = Form(...),
    to_stage_id: int = Form(...),
    user_id: int = Form(...),
    db: AsyncSession = Depends(get_db),
):
    if not await _playoff_stage_exists(db, from_stage_id) or not await _playoff_stage_exists(db, to_stage_id):
        return redirect_with_admin_msg("msg_invalid_playoff_stage")
    try:
        await move_user_to_stage(db, from_stage_id, to_stage_id, user_id)
        return redirect_with_admin_msg("msg_player_moved")
    except Exception as exc:  # noqa: BLE001
        return redirect_with_admin_msg("msg_operation_failed")


@router.post("/admin/playoff/replace")
async def admin_replace_playoff_player(
    stage_id: int = Form(...),
    from_user_id: int = Form(...),
    to_user_id: int = Form(...),
    db: AsyncSession = Depends(get_db),
):
    if not await _playoff_stage_exists(db, stage_id):
        return redirect_with_admin_msg("msg_invalid_playoff_stage")
    try:
        await replace_stage_player(db, stage_id, from_user_id, to_user_id)
        return redirect_with_admin_msg("msg_player_replaced")
    except Exception as exc:  # noqa: BLE001
        return redirect_with_admin_msg("msg_operation_failed")


@router.post("/admin/playoff/points")
async def admin_adjust_playoff_points(
    stage_id: int = Form(...),
    user_id: int = Form(...),
    points_delta: int = Form(...),
    db: AsyncSession = Depends(get_db),
):
    if not await _playoff_stage_exists(db, stage_id):
        return redirect_with_admin_msg("msg_invalid_playoff_stage")
    try:
        await adjust_stage_points(db, stage_id, user_id, points_delta)
        return redirect_with_admin_msg("msg_points_adjusted")
    except Exception as exc:  # noqa: BLE001
        return redirect_with_admin_msg("msg_operation_failed")


@router.post("/admin/playoff/score")
async def admin_playoff_score(
    stage_id: int = Form(...),
    group_number: int = Form(default=1),
    placements: str = Form(default=""),
    placements_list: list[str] | None = Form(default=None, alias="placements[]"),
    db: AsyncSession = Depends(get_db),
):
    stage = await _get_playoff_stage(db, stage_id)
    if not stage:
        return redirect_with_admin_msg("msg_invalid_playoff_stage")
    stage_config = get_admin_playoff_stage_config(stage.key)
    if stage_config.game_limit is None and not stage_config.is_final:
        return redirect_with_admin_msg("msg_operation_failed", details="stage_action_not_allowed")
    try:
        if placements_list:
            ordered_user_ids = [int(part) for part in placements_list]
        else:
            ordered_user_ids = [int(part.strip()) for part in placements.split(",") if part.strip()]
        await apply_playoff_match_results(db, stage_id, ordered_user_ids, group_number=group_number)
        return redirect_with_admin_msg("msg_playoff_game_saved")
    except Exception as exc:  # noqa: BLE001
        return redirect_with_admin_msg("msg_operation_failed")


@router.post("/admin/playoff/group/finish")
async def admin_finish_playoff_group(
    stage_id: int = Form(...),
    group_number: int = Form(...),
    db: AsyncSession = Depends(get_db),
):
    stage = await _get_playoff_stage(db, stage_id)
    if not stage:
        return redirect_with_admin_msg("msg_invalid_playoff_stage")
    stage_config = get_admin_playoff_stage_config(stage.key)
    if stage_config.game_limit is None and not stage_config.is_final:
        return redirect_with_admin_msg("msg_operation_failed", details="stage_action_not_allowed")

    participants = list((await db.scalars(select(PlayoffParticipant).where(PlayoffParticipant.stage_id == stage_id))).all())
    group_participants = [p for p in participants if get_stage_group_number_by_seed(p.seed) == group_number]
    if not group_participants:
        return redirect_with_admin_msg("msg_operation_failed")

    match = await db.scalar(select(PlayoffMatch).where(PlayoffMatch.stage_id == stage_id, PlayoffMatch.group_number == group_number))
    if not match:
        return redirect_with_admin_msg("msg_operation_failed")

    if is_limited_stage(stage.key) and match.game_number <= GROUP_STAGE_GAME_LIMIT:
        return redirect_with_admin_msg("msg_operation_failed", details="group_games_not_completed")

    ranked = sorted(group_participants, key=playoff_sort_key, reverse=True)
    promote_n = get_promote_top_n(stage.key)
    promoted_ids = {p.user_id for p in ranked[:promote_n]}
    for participant in group_participants:
        participant.is_eliminated = participant.user_id not in promoted_ids
    match.state = "finished"
    await db.commit()

    active_group_numbers = sorted({get_stage_group_number_by_seed(participant.seed) for participant in participants})
    stage_finished = True
    for active_group_number in active_group_numbers:
        active_group_match = await db.scalar(
            select(PlayoffMatch).where(PlayoffMatch.stage_id == stage.id, PlayoffMatch.group_number == active_group_number)
        )
        if not active_group_match or active_group_match.state != "finished":
            stage_finished = False
            break
    if stage_finished and is_limited_stage(stage.key):
        return redirect_with_admin_msg("msg_status_ok", details="use_stage_finish")

    return redirect_with_admin_msg("msg_status_ok")


@router.post("/admin/playoff/stage/finish")
async def admin_finish_playoff_stage(
    stage_id: int = Form(...),
    db: AsyncSession = Depends(get_db),
):
    stage = await _get_playoff_stage(db, stage_id)
    if not stage:
        return redirect_with_admin_msg("msg_invalid_playoff_stage")

    if is_limited_stage(stage.key):
        try:
            finalized = await finalize_limited_playoff_stage_if_ready(db, stage.id)
        except ValueError as exc:
            details = str(exc) or "group_games_not_completed"
            return redirect_with_admin_msg("msg_operation_failed", details=details)
        except Exception:
            return redirect_with_admin_msg("msg_operation_failed")
        if not finalized:
            return redirect_with_admin_msg("msg_status_ok")
    else:
        participants = list((await db.scalars(select(PlayoffParticipant).where(PlayoffParticipant.stage_id == stage_id))).all())
        matches = list((await db.scalars(select(PlayoffMatch).where(PlayoffMatch.stage_id == stage_id))).all())
        _, is_ready = build_playoff_stage_finish_status(stage, participants, matches)
        if not is_ready:
            return redirect_with_admin_msg("msg_operation_failed", details="group_games_not_completed")
        for match in matches:
            if match.group_number == 1:
                match.state = "finished"
        await db.commit()

    return redirect_with_admin_msg("msg_status_ok")


@router.post("/admin/playoff/results/batch")
async def admin_playoff_results_batch(
    stage_id: int = Form(...),
    group_number: int = Form(...),
    user_ids: list[str] = Form(..., alias="user_ids[]"),
    places: list[str] = Form(..., alias="places[]"),
    db: AsyncSession = Depends(get_db),
):
    stage = await _get_playoff_stage(db, stage_id)
    if not stage:
        return redirect_with_admin_msg("msg_invalid_playoff_stage")
    stage_config = get_admin_playoff_stage_config(stage.key)
    if stage_config.game_limit is None and not stage_config.is_final:
        return redirect_with_admin_msg("msg_operation_failed", details="stage_action_not_allowed")
    try:
        if len(user_ids) != len(places):
            raise ValueError("Некорректное количество полей")

        placements_map: dict[int, int] = {}
        for raw_user_id, raw_place in zip(user_ids, places):
            user_id = int(raw_user_id)
            place = int(raw_place)
            if place < 1 or place > 8:
                raise ValueError("Место должно быть в диапазоне 1..8")
            if user_id in placements_map:
                raise ValueError("Дублирующийся участник")
            placements_map[user_id] = place

        if len(placements_map) != 8:
            raise ValueError("Нужно передать 8 участников")

        unique_places = set(placements_map.values())
        if unique_places != set(range(1, 9)):
            raise ValueError("Места должны быть уникальны и покрывать диапазон 1..8")

        ordered_user_ids = [
            user_id
            for user_id, place in sorted(placements_map.items(), key=lambda item: item[1])
        ]
        await apply_playoff_match_results(db, stage_id, ordered_user_ids, group_number=group_number)
        return redirect_with_admin_msg("msg_playoff_game_saved")
    except Exception as exc:  # noqa: BLE001
        return redirect_with_admin_msg("msg_operation_failed")




@router.post("/admin/playoff/override")
async def admin_playoff_override(
    stage_id: int = Form(...),
    group_number: int = Form(default=1),
    winner_user_id: int = Form(...),
    note: str = Form(default=""),
    db: AsyncSession = Depends(get_db),
):
    stage = await _get_playoff_stage(db, stage_id)
    if not stage:
        return redirect_with_admin_msg("msg_invalid_playoff_stage")
    stage_config = get_admin_playoff_stage_config(stage.key)
    if not stage_config.is_final:
        return redirect_with_admin_msg("msg_operation_failed", details="stage_action_not_allowed")

    winner_participant = await db.scalar(
        select(PlayoffParticipant).where(
            PlayoffParticipant.stage_id == stage_id,
            PlayoffParticipant.user_id == winner_user_id,
        )
    )
    if not winner_participant or (winner_participant.points or 0) < 22:
        return redirect_with_admin_msg("msg_operation_failed", details="winner_points_below_threshold")

    try:
        await override_playoff_match_winner(db, stage_id, group_number, winner_user_id, note=note)
        return redirect_with_admin_msg("msg_status_ok")
    except Exception:  # noqa: BLE001
        return redirect_with_admin_msg("msg_operation_failed")

@router.post("/admin/donation-links")
async def admin_save_donation_links(
    items: str = Form(default=""),
    db: AsyncSession = Depends(get_db),
):
    await db.execute(DonationLink.__table__.delete())
    for idx, line in enumerate([item.strip() for item in items.splitlines() if item.strip()]):
        parts = [part.strip() for part in line.split("|")]
        if len(parts) < 2:
            continue
        db.add(DonationLink(title=parts[0], url=parts[1], is_active=(parts[2] != "0") if len(parts) > 2 else True, sort_order=idx))
    await db.commit()
    return redirect_with_admin_msg("msg_donation_links_saved")


@router.post("/admin/donation-methods")
async def admin_save_donation_methods(
    items: str = Form(default=""),
    db: AsyncSession = Depends(get_db),
):
    await db.execute(DonationMethod.__table__.delete())
    for idx, line in enumerate([item.strip() for item in items.splitlines() if item.strip()]):
        parts = [part.strip() for part in line.split("|")]
        if len(parts) < 3:
            continue
        db.add(DonationMethod(method_type=parts[0], label=parts[1], details=parts[2], is_active=(parts[3] != "0") if len(parts) > 3 else True, sort_order=idx))
    await db.commit()
    return redirect_with_admin_msg("msg_donation_methods_saved")


@router.post("/admin/prize-pool")
async def admin_save_prize_pool(
    items: str = Form(default=""),
    db: AsyncSession = Depends(get_db),
):
    await db.execute(PrizePoolEntry.__table__.delete())
    for idx, line in enumerate([item.strip() for item in items.splitlines() if item.strip()]):
        parts = [part.strip() for part in line.split("|")]
        if len(parts) < 2:
            continue
        db.add(PrizePoolEntry(place_label=parts[0], reward=parts[1], sort_order=idx))
    await db.commit()
    return redirect_with_admin_msg("msg_prize_pool_saved")


@router.post("/admin/donors")
async def admin_save_donors(
    items: str = Form(default=""),
    db: AsyncSession = Depends(get_db),
):
    await db.execute(Donor.__table__.delete())
    for idx, line in enumerate([item.strip() for item in items.splitlines() if item.strip()]):
        parts = [part.strip() for part in line.split("|")]
        if not parts:
            continue
        name = parts[0]
        amount = parts[1] if len(parts) > 1 else ""
        message = parts[2] if len(parts) > 2 else ""
        db.add(Donor(name=name, amount=amount, message=message, sort_order=idx))
    await db.commit()
    return redirect_with_admin_msg("msg_donors_saved")


@router.post("/admin/rules")
async def admin_save_rules(
    body: str = Form(default=""),
    db: AsyncSession = Depends(get_db),
):
    row = await get_or_create_rules_content(db)
    row.body = body
    await db.commit()
    return redirect_with_admin_msg("msg_rules_saved")


@router.post("/admin/archive")
async def admin_save_archive(
    items: str = Form(default=""),
    db: AsyncSession = Depends(get_db),
):
    await db.execute(ArchiveEntry.__table__.delete())
    for idx, line in enumerate([item.strip() for item in items.splitlines() if item.strip()]):
        parts = [part.strip() for part in line.split("|")]
        if not parts:
            continue
        title = parts[0]
        season = parts[1] if len(parts) > 1 else ""
        summary = parts[2] if len(parts) > 2 else ""
        link_url = parts[3] if len(parts) > 3 else ""
        champion_name = parts[4] if len(parts) > 4 else ""
        bracket_payload = parts[5] if len(parts) > 5 else ""
        is_published = parts[6] != "0" if len(parts) > 6 else True
        db.add(
            ArchiveEntry(
                title=title,
                season=season,
                summary=summary,
                link_url=link_url,
                champion_name=champion_name,
                bracket_payload=bracket_payload,
                is_published=is_published,
                sort_order=idx,
            )
        )
    await db.commit()
    return redirect_with_admin_msg("msg_archive_saved")


@router.post("/admin/judge-link/regenerate")
async def admin_regenerate_judge_link(db: AsyncSession = Depends(get_db)):
    token = create_judge_login_token()
    row = await db.scalar(select(SiteSetting).where(SiteSetting.key == "judge_login_token"))
    if not row:
        row = SiteSetting(key="judge_login_token", value=token)
        db.add(row)
    else:
        row.value = token
    await db.commit()
    return redirect_with_admin_msg("msg_status_ok")


@router.post("/admin/chat-settings")
async def admin_save_chat_settings(
    cooldown_seconds: int = Form(...),
    max_length: int = Form(...),
    is_enabled: bool = Form(default=False),
    db: AsyncSession = Depends(get_db),
):
    row = await get_or_create_chat_settings(db)
    row.cooldown_seconds = max(0, cooldown_seconds)
    row.max_length = max(1, max_length)
    row.is_enabled = is_enabled
    await db.commit()
    return redirect_with_admin_msg("msg_chat_settings_saved")


@router.post("/admin/chat/send")
async def admin_send_chat_message(
    request: Request,
    message: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    if not is_admin_session(request.cookies.get(ADMIN_SESSION_COOKIE)):
        return RedirectResponse(url="/admin/login", status_code=303)

    chat_settings = await get_chat_settings(db)
    try:
        validate_chat_message_length(message=message, max_length=chat_settings.max_length)
    except ValueError as exc:
        return redirect_with_admin_msg(str(exc))

    db.add(ChatMessage(temp_nick="@Admin", nick_color="#ff0000", message=message, ip_address="admin", sender_token="admin"))
    await db.commit()
    return redirect_with_admin_msg("msg_admin_chat_message_saved")


@router.post("/admin/chat/message/update")
async def admin_update_chat_message(
    message_id: int = Form(...),
    temp_nick: str = Form(...),
    message: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    chat_message = await db.get(ChatMessage, message_id)
    if not chat_message:
        return redirect_with_admin_msg("msg_admin_chat_message_not_found")

    chat_settings = await get_chat_settings(db)
    try:
        validate_chat_message_length(message=message, max_length=chat_settings.max_length)
    except ValueError as exc:
        return redirect_with_admin_msg(str(exc))

    chat_message.temp_nick = temp_nick[:120]
    chat_message.message = message
    await db.commit()
    return redirect_with_admin_msg("msg_admin_chat_message_saved")


@router.post("/admin/chat/message/delete")
async def admin_delete_chat_message(
    message_id: int = Form(...),
    db: AsyncSession = Depends(get_db),
):
    chat_message = await db.get(ChatMessage, message_id)
    if not chat_message:
        return redirect_with_admin_msg("msg_admin_chat_message_not_found")

    await db.delete(chat_message)
    await db.commit()
    return redirect_with_admin_msg("msg_admin_chat_message_deleted")
