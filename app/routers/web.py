import json
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.db.session import get_db
from app.models.chat import ChatMessage
from app.models.settings import SiteSetting, TournamentStage
from app.models.tournament import GroupManualTieBreak, GroupMember, TournamentGroup
from app.models.user import Basket, User
from app.services.basket_allocator import allocate_basket
from app.services.i18n import get_lang, t
from app.services.rank import pick_basket
from app.services.steam import fetch_autochess_data, normalize_steam_id
from app.services.tournament import (
    apply_game_results,
    apply_manual_tie_break,
    create_auto_draw,
    generate_playoff_from_groups,
    get_playoff_stages_with_data,
    move_user_to_stage,
    promote_top_between_stages,
    replace_stage_player,
    sort_members_for_table,
    start_playoff_stage,
    adjust_stage_points,
    apply_playoff_match_results,
)

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


async def get_registration_open(db: AsyncSession) -> bool:
    # Получаем флаг доступности регистрации из настроек.
    record = await db.scalar(select(SiteSetting).where(SiteSetting.key == "registration_open"))
    return (record.value == "1") if record else True


@router.get("/set-lang/{lang}")
async def set_lang(lang: str):
    # Сохраняем выбранный язык в cookie.
    response = RedirectResponse(url="/", status_code=302)
    response.set_cookie("lang", "ru" if lang == "ru" else "en", max_age=60 * 60 * 24 * 365)
    return response


@router.get("/", response_class=HTMLResponse)
async def index(request: Request, db: AsyncSession = Depends(get_db)):
    # Рендерим главную страницу с формой и чатом.
    lang = get_lang(request.cookies.get("lang"))
    stages = (await db.scalars(select(TournamentStage).order_by(TournamentStage.id))).all()
    chat_messages = (await db.scalars(select(ChatMessage).order_by(desc(ChatMessage.id)).limit(20))).all()
    registration_open = await get_registration_open(db)
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "lang": lang,
            "tr": lambda key: t(lang, key),
            "stages": stages,
            "chat_messages": list(reversed(chat_messages)),
            "registration_open": registration_open,
        },
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
    lang = get_lang(request.cookies.get("lang"))
    if not await get_registration_open(db):
        return RedirectResponse(url=f"/?msg={t(lang, 'registration_closed')}", status_code=303)

    steam_id = await normalize_steam_id(steam_input)
    if not steam_id:
        return RedirectResponse(url="/?msg=Invalid Steam ID", status_code=303)

    exists = await db.scalar(select(User).where(User.steam_id == steam_id))
    if exists:
        return RedirectResponse(url=f"/?msg={t(lang, 'already_registered')}", status_code=303)

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
    return RedirectResponse(url=f"/?msg={t(lang, 'registered_ok')}", status_code=303)


@router.post("/register/preview")
async def register_preview(
    steam_input: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    """Проверяет Steam-ввод и возвращает данные профиля для предпросмотра регистрации."""
    if not await get_registration_open(db):
        return JSONResponse({"ok": False, "error": "Registration is closed"}, status_code=403)

    steam_id = await normalize_steam_id(steam_input)
    if not steam_id:
        return JSONResponse({"ok": False, "error": "Invalid Steam ID"}, status_code=400)

    exists = await db.scalar(select(User).where(User.steam_id == steam_id))
    if exists:
        return JSONResponse({"ok": False, "error": "User already registered"}, status_code=409)

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
    # Сохраняем сообщение чата с ограничением в 10 секунд.
    if len(message) > 1000:
        return RedirectResponse(url="/?msg=Message too long", status_code=303)

    ip = request.client.host if request.client else "unknown"
    last_msg = await db.scalar(
        select(ChatMessage)
        .where(ChatMessage.ip_address == ip)
        .order_by(desc(ChatMessage.created_at))
        .limit(1)
    )
    if last_msg and datetime.utcnow() - last_msg.created_at < timedelta(seconds=10):
        return RedirectResponse(url="/?msg=Cooldown 10 sec", status_code=303)

    db.add(ChatMessage(temp_nick=temp_nick[:120], message=message, ip_address=ip))
    await db.commit()
    return RedirectResponse(url="/#chat", status_code=303)


@router.get("/participants", response_class=HTMLResponse)
async def participants(request: Request, basket: str = Query(Basket.QUEEN.value), db: AsyncSession = Depends(get_db)):
    # Показываем участников по выбранной корзине.
    lang = get_lang(request.cookies.get("lang"))
    users = (await db.scalars(select(User).where(User.basket == basket).order_by(User.created_at))).all()
    return templates.TemplateResponse("participants.html", {"request": request, "users": users, "basket": basket, "lang": lang})


@router.get("/tournament", response_class=HTMLResponse)
async def tournament_page(request: Request, db: AsyncSession = Depends(get_db)):
    # Отдаем турнирную таблицу с текущими группами.
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
    playoff_standings = {
        stage.id: sorted(stage.participants, key=lambda p: (p.points, p.wins, p.top4_finishes, -p.last_place, -p.user_id), reverse=True)
        for stage in playoff_stages
    }
    return templates.TemplateResponse(
        "tournament.html",
        {"request": request, "groups": groups, "standings": standings, "playoff_stages": playoff_stages, "playoff_standings": playoff_standings},
    )


@router.get("/donate", response_class=HTMLResponse)
async def donate_page(request: Request):
    # Отдаем страницу донатов.
    return templates.TemplateResponse("donate.html", {"request": request})


@router.get("/rules", response_class=HTMLResponse)
async def rules_page(request: Request):
    # Отдаем страницу правил.
    return templates.TemplateResponse("rules.html", {"request": request})


@router.get("/archive", response_class=HTMLResponse)
async def archive_page(request: Request):
    # Отдаем страницу архива.
    return templates.TemplateResponse("archive.html", {"request": request})


@router.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request, admin_key: str = Query(default=""), db: AsyncSession = Depends(get_db)):
    # Показываем админку только по секретному ключу из .env.
    if admin_key != settings.admin_key:
        return HTMLResponse("Forbidden", status_code=403)
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
    playoff_stages = await get_playoff_stages_with_data(db)
    return templates.TemplateResponse(
        "admin.html",
        {
            "request": request,
            "users": users,
            "stages": stages,
            "groups": groups,
            "playoff_stages": playoff_stages,
            "admin_key": admin_key,
            "score_hint": "Формат: user_id1,user_id2,...,user_id8 (от 1 места к 8 месту)",
        },
    )


@router.post("/admin/stage")
async def admin_update_stage(
    key: str = Form(...),
    title_ru: str = Form(...),
    title_en: str = Form(...),
    date_text: str = Form(...),
    is_active: bool = Form(default=False),
    admin_key: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    # Обновляем этапы турнира из админ-панели.
    if admin_key != settings.admin_key:
        return HTMLResponse("Forbidden", status_code=403)
    row = await db.scalar(select(TournamentStage).where(TournamentStage.key == key))
    if not row:
        row = TournamentStage(key=key, title_ru=title_ru, title_en=title_en)
        db.add(row)
    row.title_ru = title_ru
    row.title_en = title_en
    row.date_text = date_text
    row.is_active = is_active
    await db.commit()
    return RedirectResponse(url=f"/admin?admin_key={admin_key}", status_code=303)


@router.post("/admin/registration")
async def admin_registration_toggle(
    registration_open: bool = Form(default=False),
    admin_key: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    # Переключаем состояние регистрации вручную.
    if admin_key != settings.admin_key:
        return HTMLResponse("Forbidden", status_code=403)
    row = await db.scalar(select(SiteSetting).where(SiteSetting.key == "registration_open"))
    if not row:
        row = SiteSetting(key="registration_open", value="1")
        db.add(row)
    row.value = "1" if registration_open else "0"
    await db.commit()
    return RedirectResponse(url=f"/admin?admin_key={admin_key}", status_code=303)


@router.post("/admin/invite")
async def admin_invite_user(
    steam_input: str = Form(...),
    nickname: str = Form(...),
    telegram: str = Form(default=""),
    discord: str = Form(default=""),
    admin_key: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    # Добавляем участника вручную в корзину invited.
    if admin_key != settings.admin_key:
        return HTMLResponse("Forbidden", status_code=403)
    steam_id = await normalize_steam_id(steam_input)
    if not steam_id:
        return RedirectResponse(url=f"/admin?admin_key={admin_key}&msg=Invalid Steam ID", status_code=303)

    exists = await db.scalar(select(User).where(User.steam_id == steam_id))
    if exists:
        return RedirectResponse(url=f"/admin?admin_key={admin_key}&msg=User already exists", status_code=303)

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
    return RedirectResponse(url=f"/admin?admin_key={admin_key}&msg=Invited added", status_code=303)


@router.post("/admin/draw/auto")
async def admin_auto_draw(admin_key: str = Form(...), db: AsyncSession = Depends(get_db)):
    # Запускаем автоматическую жеребьевку группового этапа.
    if admin_key != settings.admin_key:
        return HTMLResponse("Forbidden", status_code=403)
    ok, message = await create_auto_draw(db)
    status = "ok" if ok else "warn"
    return RedirectResponse(url=f"/admin?admin_key={admin_key}&msg={status}:{message}", status_code=303)


@router.post("/admin/group/password")
async def admin_group_password(
    group_id: int = Form(...),
    password: str = Form(...),
    admin_key: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    # Обновляем пароль лобби конкретной группы.
    if admin_key != settings.admin_key:
        return HTMLResponse("Forbidden", status_code=403)
    group = await db.scalar(select(TournamentGroup).where(TournamentGroup.id == group_id))
    if not group:
        return RedirectResponse(url=f"/admin?admin_key={admin_key}&msg=Group not found", status_code=303)
    group.lobby_password = (password or "0000")[:4].rjust(4, "0")
    await db.commit()
    return RedirectResponse(url=f"/admin?admin_key={admin_key}&msg=Lobby password updated", status_code=303)


@router.post("/admin/group/score")
async def admin_group_score(
    group_id: int = Form(...),
    placements: str = Form(...),
    admin_key: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    """Принимает порядок мест в игре и начисляет очки участникам выбранной группы."""
    if admin_key != settings.admin_key:
        return HTMLResponse("Forbidden", status_code=403)
    try:
        ordered_user_ids = [int(part.strip()) for part in placements.split(",") if part.strip()]
        await apply_game_results(db, group_id, ordered_user_ids)
        return RedirectResponse(url=f"/admin?admin_key={admin_key}&msg=Game saved", status_code=303)
    except Exception as exc:  # noqa: BLE001
        return RedirectResponse(url=f"/admin?admin_key={admin_key}&msg=Error: {exc}", status_code=303)


@router.post("/admin/group/tie-break")
async def admin_group_tie_break(
    group_id: int = Form(...),
    tied_user_ids: str = Form(...),
    admin_key: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    # Применяем ручную "монетку" для спорных кейсов и фиксируем результат в БД.
    if admin_key != settings.admin_key:
        return HTMLResponse("Forbidden", status_code=403)
    try:
        ordered_user_ids = [int(part.strip()) for part in tied_user_ids.split(",") if part.strip()]
        await apply_manual_tie_break(db, group_id, ordered_user_ids)
        return RedirectResponse(url=f"/admin?admin_key={admin_key}&msg=Manual tie-break saved", status_code=303)
    except Exception as exc:  # noqa: BLE001
        return RedirectResponse(url=f"/admin?admin_key={admin_key}&msg=Error: {exc}", status_code=303)


@router.post("/admin/playoff/generate")
async def admin_generate_playoff(
    admin_key: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    if admin_key != settings.admin_key:
        return HTMLResponse("Forbidden", status_code=403)
    ok, message = await generate_playoff_from_groups(db)
    status = "ok" if ok else "warn"
    return RedirectResponse(url=f"/admin?admin_key={admin_key}&msg={status}:{message}", status_code=303)


@router.post("/admin/playoff/start")
async def admin_start_playoff(
    stage_id: int = Form(...),
    admin_key: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    if admin_key != settings.admin_key:
        return HTMLResponse("Forbidden", status_code=403)
    try:
        await start_playoff_stage(db, stage_id)
        return RedirectResponse(url=f"/admin?admin_key={admin_key}&msg=Playoff stage started", status_code=303)
    except Exception as exc:  # noqa: BLE001
        return RedirectResponse(url=f"/admin?admin_key={admin_key}&msg=Error: {exc}", status_code=303)


@router.post("/admin/playoff/promote")
async def admin_promote_playoff(
    stage_id: int = Form(...),
    top_n: int = Form(...),
    admin_key: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    if admin_key != settings.admin_key:
        return HTMLResponse("Forbidden", status_code=403)
    try:
        await promote_top_between_stages(db, stage_id, top_n)
        return RedirectResponse(url=f"/admin?admin_key={admin_key}&msg=Players promoted", status_code=303)
    except Exception as exc:  # noqa: BLE001
        return RedirectResponse(url=f"/admin?admin_key={admin_key}&msg=Error: {exc}", status_code=303)


@router.post("/admin/playoff/move")
async def admin_move_playoff_player(
    from_stage_id: int = Form(...),
    to_stage_id: int = Form(...),
    user_id: int = Form(...),
    admin_key: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    if admin_key != settings.admin_key:
        return HTMLResponse("Forbidden", status_code=403)
    try:
        await move_user_to_stage(db, from_stage_id, to_stage_id, user_id)
        return RedirectResponse(url=f"/admin?admin_key={admin_key}&msg=Player moved", status_code=303)
    except Exception as exc:  # noqa: BLE001
        return RedirectResponse(url=f"/admin?admin_key={admin_key}&msg=Error: {exc}", status_code=303)


@router.post("/admin/playoff/replace")
async def admin_replace_playoff_player(
    stage_id: int = Form(...),
    from_user_id: int = Form(...),
    to_user_id: int = Form(...),
    admin_key: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    if admin_key != settings.admin_key:
        return HTMLResponse("Forbidden", status_code=403)
    try:
        await replace_stage_player(db, stage_id, from_user_id, to_user_id)
        return RedirectResponse(url=f"/admin?admin_key={admin_key}&msg=Player replaced", status_code=303)
    except Exception as exc:  # noqa: BLE001
        return RedirectResponse(url=f"/admin?admin_key={admin_key}&msg=Error: {exc}", status_code=303)


@router.post("/admin/playoff/points")
async def admin_adjust_playoff_points(
    stage_id: int = Form(...),
    user_id: int = Form(...),
    points_delta: int = Form(...),
    admin_key: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    if admin_key != settings.admin_key:
        return HTMLResponse("Forbidden", status_code=403)
    try:
        await adjust_stage_points(db, stage_id, user_id, points_delta)
        return RedirectResponse(url=f"/admin?admin_key={admin_key}&msg=Points adjusted", status_code=303)
    except Exception as exc:  # noqa: BLE001
        return RedirectResponse(url=f"/admin?admin_key={admin_key}&msg=Error: {exc}", status_code=303)


@router.post("/admin/playoff/score")
async def admin_playoff_score(
    stage_id: int = Form(...),
    placements: str = Form(...),
    admin_key: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    if admin_key != settings.admin_key:
        return HTMLResponse("Forbidden", status_code=403)
    try:
        ordered_user_ids = [int(part.strip()) for part in placements.split(",") if part.strip()]
        await apply_playoff_match_results(db, stage_id, ordered_user_ids)
        return RedirectResponse(url=f"/admin?admin_key={admin_key}&msg=Playoff game saved", status_code=303)
    except Exception as exc:  # noqa: BLE001
        return RedirectResponse(url=f"/admin?admin_key={admin_key}&msg=Error: {exc}", status_code=303)
