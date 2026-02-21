import json
import re
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.admin_session import ADMIN_SESSION_COOKIE, create_admin_session_cookie, is_admin_session
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
from app.models.tournament import GroupManualTieBreak, GroupMember, TournamentGroup
from app.models.user import Basket, User
from app.services.basket_allocator import allocate_basket
from app.services.i18n import get_lang, t
from app.services.rank import pick_basket
from app.services.steam import fetch_autochess_data, normalize_steam_id
from app.services.tournament import (
    add_group_member,
    apply_coin_toss_tie_break,
    apply_game_results,
    apply_manual_tie_break,
    apply_playoff_match_results,
    create_auto_draw,
    create_manual_group,
    generate_playoff_from_groups,
    get_playoff_stages_with_data,
    get_fully_tied_member_groups,
    move_group_member,
    move_user_to_stage,
    promote_top_between_stages,
    remove_group_member,
    replace_stage_player,
    sort_members_for_table,
    start_playoff_stage,
    swap_group_members,
    adjust_stage_points,
)

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def template_context(request: Request, **extra):
    lang = get_lang(request.cookies.get("lang"))
    context = {"request": request, "lang": lang, "tr": lambda key: t(lang, key)}
    context.update(extra)
    return context


def redirect_with_msg(url: str, msg_key: str, status_code: int = 303) -> RedirectResponse:
    separator = "&" if "?" in url else "?"
    return RedirectResponse(url=f"{url}{separator}msg={msg_key}", status_code=status_code)


def redirect_with_admin_msg(msg_key: str) -> RedirectResponse:
    return RedirectResponse(url=f"/admin?msg={msg_key}", status_code=303)


async def get_registration_open(db: AsyncSession) -> bool:
    # Получаем флаг доступности регистрации из настроек.
    record = await db.scalar(select(SiteSetting).where(SiteSetting.key == "registration_open"))
    return (record.value == "1") if record else True


async def get_tournament_started(db: AsyncSession) -> bool:
    record = await db.scalar(select(SiteSetting).where(SiteSetting.key == "tournament_started"))
    return (record.value == "1") if record else False


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
        "index.html",
        template_context(
            request,
            stages=stages,
            chat_messages=list(reversed(chat_messages)),
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
    message: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    # Сохраняем сообщение чата с ограничением, настраиваемым в админке.
    chat_settings = await get_chat_settings(db)
    if not chat_settings.is_enabled:
        return redirect_with_msg("/", "msg_chat_disabled")

    if len(message) > chat_settings.max_length:
        return redirect_with_msg("/", "msg_message_too_long")

    ip = request.client.host if request.client else "unknown"
    last_msg = await db.scalar(
        select(ChatMessage)
        .where(ChatMessage.ip_address == ip)
        .order_by(desc(ChatMessage.created_at))
        .limit(1)
    )
    if last_msg and datetime.utcnow() - last_msg.created_at < timedelta(seconds=chat_settings.cooldown_seconds):
        return redirect_with_msg("/", "msg_cooldown_active")

    db.add(ChatMessage(temp_nick=temp_nick[:120], message=message, ip_address=ip))
    await db.commit()
    return RedirectResponse(url="/#chat", status_code=303)


@router.get("/participants", response_class=HTMLResponse)
async def participants(request: Request, basket: str = Query(Basket.QUEEN.value), db: AsyncSession = Depends(get_db)):
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

    main_users = (
        await db.scalars(select(User).where(User.basket == main_basket).order_by(User.created_at))
    ).all()
    reserve_users = (
        await db.scalars(select(User).where(User.basket == reserve_basket).order_by(User.created_at))
    ).all()

    return templates.TemplateResponse(
        "participants.html",
        template_context(
            request,
            basket=main_basket,
            basket_pairs=basket_pairs,
            main_users=main_users,
            reserve_users=reserve_users,
            is_empty=not main_users and not reserve_users,
        ),
    )


@router.get("/tournament", response_class=HTMLResponse)
async def tournament_page(request: Request, db: AsyncSession = Depends(get_db)):
    # Отдаем турнирную таблицу с текущими группами и playoff-расписанием.
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
    manual_tie_breaks = (
        await db.scalars(
            select(GroupManualTieBreak).where(GroupManualTieBreak.group_id.in_([group.id for group in groups]))
        )
    ).all()
    manual_tie_break_map: dict[int, dict[int, int]] = {}
    for tie_break in manual_tie_breaks:
        manual_tie_break_map.setdefault(tie_break.group_id, {})[tie_break.user_id] = tie_break.priority

    standings = {
        group.id: sort_members_for_table(group.members, manual_tie_break_map.get(group.id))
        for group in groups
    }
    playoff_stages = await get_playoff_stages_with_data(db)
    lang = get_lang(request.cookies.get("lang"))
    current_stage_label = t(lang, "tournament_group_stage")
    active_playoff = next((stage for stage in playoff_stages if stage.is_started), None)
    if active_playoff:
        current_stage_label = active_playoff.title
    elif playoff_stages:
        current_stage_label = playoff_stages[0].title
    playoff_standings = {
        stage.id: sorted(stage.participants, key=lambda p: (p.points, p.wins, p.top4_finishes, -p.last_place, -p.user_id), reverse=True)
        for stage in playoff_stages
    }
    return templates.TemplateResponse(
        "tournament.html",
        template_context(
            request,
            groups=groups,
            standings=standings,
            playoff_stages=playoff_stages,
            playoff_standings=playoff_standings,
            current_stage_label=current_stage_label,
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
    return templates.TemplateResponse("rules.html", template_context(request, rules_content=rules_content))


@router.get("/archive", response_class=HTMLResponse)
async def archive_page(request: Request, db: AsyncSession = Depends(get_db)):
    # Отдаем страницу архива.
    archive_entries = (await db.scalars(select(ArchiveEntry).order_by(ArchiveEntry.sort_order, ArchiveEntry.id))).all()
    return templates.TemplateResponse("archive.html", template_context(request, archive_entries=archive_entries))


@router.get("/admin/login", response_class=HTMLResponse)
async def admin_login_page(request: Request):
    if is_admin_session(request.cookies.get(ADMIN_SESSION_COOKIE)):
        return RedirectResponse(url="/admin", status_code=303)
    return templates.TemplateResponse("admin_login.html", template_context(request))


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
    users = (await db.scalars(select(User).order_by(desc(User.created_at)).limit(300))).all()
    stages = (await db.scalars(select(TournamentStage).order_by(TournamentStage.id))).all()
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
    manual_tie_breaks = (
        await db.scalars(
            select(GroupManualTieBreak).where(GroupManualTieBreak.group_id.in_([group.id for group in groups]))
        )
    ).all()
    manual_tie_break_map: dict[int, dict[int, int]] = {}
    for tie_break in manual_tie_breaks:
        manual_tie_break_map.setdefault(tie_break.group_id, {})[tie_break.user_id] = tie_break.priority

    coin_toss_candidates: dict[int, list[str]] = {}
    for group in groups:
        ranked_members = sort_members_for_table(group.members, manual_tie_break_map.get(group.id))
        tied_groups = get_fully_tied_member_groups(ranked_members)
        if tied_groups:
            coin_toss_candidates[group.id] = [
                ",".join(str(member.user_id) for member in tied_group)
                for tied_group in tied_groups
            ]
    playoff_stages = await get_playoff_stages_with_data(db)
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
    await db.commit()
    return templates.TemplateResponse(
        "admin.html",
        template_context(
            request,
            users=users,
            stages=stages,
            groups=groups,
            playoff_stages=playoff_stages,
            score_hint="user_id1,user_id2,...,user_id8",
            registration_open=registration_open,
            tournament_started=tournament_started,
            donation_links=donation_links,
            donation_methods=donation_methods,
            prize_pool_entries=prize_pool_entries,
            donors=donors,
            rules_content=rules_content,
            archive_entries=archive_entries,
            chat_settings=chat_settings,
            coin_toss_candidates=coin_toss_candidates,
            basket_values=[basket.value for basket in Basket],
        ),
    )


@router.post("/admin/user/basket")
async def admin_update_user_basket(
    user_id: int = Form(...),
    basket: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    # Обновляем корзину пользователя из админ-панели.
    user = await db.get(User, user_id)
    if not user:
        return redirect_with_admin_msg("msg_operation_failed")

    allowed_values = {item.value for item in Basket}
    if basket not in allowed_values:
        return redirect_with_admin_msg("msg_operation_failed")

    user.basket = basket
    await db.commit()
    return redirect_with_admin_msg("msg_status_ok")


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
        extra_data=json.dumps(profile["raw"], ensure_ascii=False),
    )
    db.add(user)
    await db.commit()
    return redirect_with_admin_msg("msg_invited_added")


@router.post("/admin/draw/auto")
async def admin_auto_draw(db: AsyncSession = Depends(get_db)):
    # Запускаем автоматическую жеребьевку группового этапа.
    ok, message = await create_auto_draw(db)
    return redirect_with_admin_msg("msg_status_ok" if ok else "msg_status_warn")


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


@router.post("/admin/group/create")
async def admin_group_create(
    name: str = Form(...),
    lobby_password: str = Form(default="0000"),
    db: AsyncSession = Depends(get_db),
):
    try:
        await create_manual_group(db, name=name, lobby_password=lobby_password)
        return redirect_with_admin_msg("msg_status_ok")
    except Exception as exc:  # noqa: BLE001
        return redirect_with_admin_msg("msg_operation_failed")


@router.post("/admin/group/member/add")
async def admin_group_member_add(
    group_id: int = Form(...),
    user_id: int = Form(...),
    db: AsyncSession = Depends(get_db),
):
    try:
        await add_group_member(db, group_id=group_id, user_id=user_id)
        return redirect_with_admin_msg("msg_status_ok")
    except Exception as exc:  # noqa: BLE001
        return redirect_with_admin_msg("msg_operation_failed")


@router.post("/admin/group/member/remove")
async def admin_group_member_remove(
    group_id: int = Form(...),
    user_id: int = Form(...),
    db: AsyncSession = Depends(get_db),
):
    try:
        await remove_group_member(db, group_id=group_id, user_id=user_id)
        return redirect_with_admin_msg("msg_status_ok")
    except Exception as exc:  # noqa: BLE001
        return redirect_with_admin_msg("msg_operation_failed")


@router.post("/admin/group/member/move")
async def admin_group_member_move(
    from_group_id: int = Form(...),
    to_group_id: int = Form(...),
    user_id: int = Form(...),
    db: AsyncSession = Depends(get_db),
):
    try:
        await move_group_member(db, from_group_id=from_group_id, to_group_id=to_group_id, user_id=user_id)
        return redirect_with_admin_msg("msg_status_ok")
    except Exception as exc:  # noqa: BLE001
        return redirect_with_admin_msg("msg_operation_failed")


@router.post("/admin/group/member/swap")
async def admin_group_member_swap(
    first_group_id: int = Form(...),
    first_user_id: int = Form(...),
    second_group_id: int = Form(...),
    second_user_id: int = Form(...),
    db: AsyncSession = Depends(get_db),
):
    try:
        await swap_group_members(
            db,
            first_group_id=first_group_id,
            first_user_id=first_user_id,
            second_group_id=second_group_id,
            second_user_id=second_user_id,
        )
        return redirect_with_admin_msg("msg_status_ok")
    except Exception as exc:  # noqa: BLE001
        return redirect_with_admin_msg("msg_operation_failed")


@router.post("/admin/group/score")
async def admin_group_score(
    group_id: int = Form(...),
    placements: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    """Принимает порядок мест в игре и начисляет очки участникам выбранной группы."""
    try:
        ordered_user_ids = [int(part.strip()) for part in placements.split(",") if part.strip()]
        await apply_game_results(db, group_id, ordered_user_ids)
        return redirect_with_admin_msg("msg_game_saved")
    except Exception as exc:  # noqa: BLE001
        return redirect_with_admin_msg("msg_operation_failed")


@router.post("/admin/group/tie-break")
async def admin_group_tie_break(
    group_id: int = Form(...),
    tied_user_ids: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    # Применяем ручную "монетку" для спорных кейсов и фиксируем результат в БД.
    try:
        ordered_user_ids = [int(part.strip()) for part in tied_user_ids.split(",") if part.strip()]
        await apply_manual_tie_break(db, group_id, ordered_user_ids)
        return redirect_with_admin_msg("msg_manual_tie_break_saved")
    except Exception as exc:  # noqa: BLE001
        return redirect_with_admin_msg("msg_operation_failed")


@router.post("/admin/group/coin-toss")
async def admin_group_coin_toss(
    group_id: int = Form(...),
    tied_user_ids: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    # Применяем coin toss только для полностью равных игроков и сохраняем результат в БД.
    try:
        ordered_user_ids = [int(part.strip()) for part in tied_user_ids.split(",") if part.strip()]
        await apply_coin_toss_tie_break(db, group_id, ordered_user_ids)
        return redirect_with_admin_msg("msg_manual_tie_break_saved")
    except Exception as exc:  # noqa: BLE001
        return redirect_with_admin_msg("msg_operation_failed")


@router.post("/admin/playoff/generate")
async def admin_generate_playoff(
    db: AsyncSession = Depends(get_db),
):
    ok, message = await generate_playoff_from_groups(db)
    return redirect_with_admin_msg("msg_status_ok" if ok else "msg_status_warn")


@router.post("/admin/playoff/start")
async def admin_start_playoff(
    stage_id: int = Form(...),
    db: AsyncSession = Depends(get_db),
):
    try:
        await start_playoff_stage(db, stage_id)
        return redirect_with_admin_msg("msg_playoff_stage_started")
    except Exception as exc:  # noqa: BLE001
        return redirect_with_admin_msg("msg_operation_failed")


@router.post("/admin/playoff/promote")
async def admin_promote_playoff(
    stage_id: int = Form(...),
    top_n: int = Form(...),
    db: AsyncSession = Depends(get_db),
):
    try:
        await promote_top_between_stages(db, stage_id, top_n)
        return redirect_with_admin_msg("msg_players_promoted")
    except Exception as exc:  # noqa: BLE001
        return redirect_with_admin_msg("msg_operation_failed")


@router.post("/admin/playoff/move")
async def admin_move_playoff_player(
    from_stage_id: int = Form(...),
    to_stage_id: int = Form(...),
    user_id: int = Form(...),
    db: AsyncSession = Depends(get_db),
):
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
    try:
        await adjust_stage_points(db, stage_id, user_id, points_delta)
        return redirect_with_admin_msg("msg_points_adjusted")
    except Exception as exc:  # noqa: BLE001
        return redirect_with_admin_msg("msg_operation_failed")


@router.post("/admin/playoff/score")
async def admin_playoff_score(
    stage_id: int = Form(...),
    group_number: int = Form(default=1),
    placements: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    try:
        ordered_user_ids = [int(part.strip()) for part in placements.split(",") if part.strip()]
        await apply_playoff_match_results(db, stage_id, ordered_user_ids, group_number=group_number)
        return redirect_with_admin_msg("msg_playoff_game_saved")
    except Exception as exc:  # noqa: BLE001
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
        db.add(ArchiveEntry(title=title, season=season, summary=summary, link_url=link_url, sort_order=idx))
    await db.commit()
    return redirect_with_admin_msg("msg_archive_saved")


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
