"""Содержит веб-маршруты для страниц турнира, админки и пользовательских действий."""

import asyncio
import json
import logging
import math
import uuid
import re
from html import escape, unescape
from html.parser import HTMLParser
from urllib.parse import quote, unquote, urlencode
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, Form, Query, Request
from pydantic import BaseModel
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import Integer, case, delete, desc, func, select, update
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
    CryptoWallet,
    DonationLink,
    DonationMethod,
    Donor,
    PrizePoolEntry,
    RulesContent,
    SiteSetting,
    TournamentStage,
)
from app.models.tournament import (
    EmergencyOperationLog,
    GroupGameResult,
    GroupManualTieBreak,
    GroupMember,
    PlayoffMatch,
    PlayoffParticipant,
    PlayoffStage,
    TournamentGroup,
)
from app.models.tournament_archive import TournamentArchive
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
    finalize_tournament_with_winner,
    get_playoff_stages_with_data,
    get_current_tournament_profile_key,
    get_current_tournament_profile_spec,
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
    snapshot_tournament_archive,
    reset_tournament_cycle_after_finish,
)
from app.services.tournament_view import (
    _apply_stage_highlight_rules,
    build_bracket_columns,
    build_tournament_tree_vm,
    resolve_current_stage_label,
)

from app.services.tournament_stage_config import (
    get_tournament_profile_spec,
    FINAL_STAGE_SCORING_MODES,
    GROUP_STAGE_GAME_LIMIT,
    LEGACY_STAGE_KEY_ALIASES,
    TOURNAMENT_PROFILE_SPECS,
    normalize_tournament_profile_key,
    can_submit_stage_results,
    get_admin_playoff_stage_config,
    get_game_limit,
    get_promote_top_n,
    get_stage_group_count,
    get_stage_group_size,
    is_final_stage,
    is_final_stage_key,
    is_limited_stage,
    normalize_stage_key,
)

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

DONATE_HIGHLIGHT_AMOUNT_SETTING_KEY = "donate_highlight_amount"
DONATE_SUPPORT_AUTHOR_VISIBLE_SETTING_KEY = "donate_support_author_visible"
RUB_PER_USD_RATE = Decimal("79")


ALLOWED_USER_UPDATE_FIELDS = {"basket", "direct_invite_stage"}
ALLOWED_DIRECT_INVITE_STAGES = {None, *get_playoff_stage_sequence_keys()}
TOURNAMENT_STAGE_KEYS_ORDER = get_public_stage_display_sequence()
PLAYOFF_STAGE_KEYS_ORDER = TOURNAMENT_STAGE_KEYS_ORDER[1:]
BASKET_PAIRS = [
    (Basket.QUEEN.value, Basket.QUEEN_RESERVE.value),
    (Basket.KING.value, Basket.KING_RESERVE.value),
    (Basket.ROOK.value, Basket.ROOK_RESERVE.value),
    (Basket.BISHOP.value, Basket.BISHOP_RESERVE.value),
    (Basket.LOW_RANK.value, Basket.LOW_RANK_RESERVE.value),
]
EXPECTED_32_PLAYER_STAGE_ORDER_PAIRS = [
    (0, "stage_2"),
    (1, "stage_1_4"),
    (2, "stage_final"),
]


CHAT_NICK_COLORS = ["#00d4ff", "#ff7a59", "#b084ff", "#2dd36f", "#ffd166", "#ff66c4", "#5ce1e6", "#f48c06", "#90be6d", "#4cc9f0"]
FORBIDDEN_CHAT_NICKS = {"@admin"}
CHAT_SENDER_TOKEN_RE = re.compile(r"^[0-9a-f]{32}$")


def parse_donor_amount(amount_raw: str) -> Decimal:
    cleaned = (amount_raw or "").replace("\xa0", " ").strip()
    match = re.search(r"-?\d[\d\s.,]*", cleaned)
    if not match:
        return Decimal("0")
    numeric = match.group(0).replace(" ", "").replace(",", ".")
    if numeric.count(".") > 1:
        integer, fractional = numeric.rsplit(".", 1)
        numeric = integer.replace(".", "") + "." + fractional
    try:
        return Decimal(numeric)
    except InvalidOperation:
        return Decimal("0")


def format_money_amount(amount: Decimal) -> str:
    return f"{int(amount)}" if amount == amount.to_integral() else f"{amount:.2f}"


def to_rub_and_usd_display_amounts(total_rub_amount: Decimal) -> tuple[str, str]:
    usd_amount = total_rub_amount / RUB_PER_USD_RATE
    return format_money_amount(total_rub_amount), format_money_amount(usd_amount)


class ChatEventBroker:
    """Публикует события чата и позволяет подписчикам ждать появления новых сообщений."""

    def __init__(self) -> None:
        self._version = 0
        self._condition = asyncio.Condition()

    async def publish(self) -> None:
        async with self._condition:
            self._version += 1
            self._condition.notify_all()

    async def wait_for_update(self, last_seen_version: int) -> int:
        async with self._condition:
            while self._version <= last_seen_version:
                await self._condition.wait()
            return self._version


chat_event_broker = ChatEventBroker()
logger = logging.getLogger(__name__)


ALLOWED_CONTENT_HTML_TAGS = {
    "p",
    "br",
    "strong",
    "b",
    "em",
    "i",
    "u",
    "s",
    "blockquote",
    "ul",
    "ol",
    "li",
    "a",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "code",
    "pre",
    "table",
    "thead",
    "tbody",
    "tr",
    "th",
    "td",
    "span",
    "img",
    "figure",
    "figcaption",
}
ALLOWED_CONTENT_HTML_ATTRS = {
    "a": {"href", "title", "target", "rel"},
    "p": {"style"},
    "h1": {"style"},
    "h2": {"style"},
    "h3": {"style"},
    "h4": {"style"},
    "h5": {"style"},
    "h6": {"style"},
    "ul": {"style"},
    "ol": {"style"},
    "li": {"style"},
    "span": {"style"},
    "table": {"style"},
    "thead": {"style"},
    "tbody": {"style"},
    "tr": {"style"},
    "th": {"style", "colspan", "rowspan"},
    "td": {"style", "colspan", "rowspan"},
    "img": {"src", "alt", "title", "width", "height"},
}
ALLOWED_LINK_SCHEMES = ("http://", "https://", "mailto:", "#", "/")
ALLOWED_IMAGE_SCHEMES = ("http://", "https://", "data:image/")
ALLOWED_STYLE_PROPS = {"color", "background-color", "text-align"}


class _ContentHtmlSanitizer(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []

    def _sanitize_attrs(self, tag: str, attrs: list[tuple[str, str | None]]) -> str:
        allowed_attrs = ALLOWED_CONTENT_HTML_ATTRS.get(tag, set())
        if not allowed_attrs:
            return ""

        rendered_attrs: list[str] = []
        for key, raw_value in attrs:
            if key not in allowed_attrs:
                continue
            value = (raw_value or "").strip()
            if not value:
                continue
            if key == "href":
                if not value.startswith(ALLOWED_LINK_SCHEMES):
                    continue
            if key == "src":
                if not value.startswith(ALLOWED_IMAGE_SCHEMES):
                    continue
            if key == "target":
                if value not in {"_blank", "_self"}:
                    continue
            if key == "rel":
                value = " ".join(item for item in value.split() if item in {"noopener", "noreferrer", "nofollow"})
                if not value:
                    continue
            if key in {"width", "height", "colspan", "rowspan"}:
                if not value.isdigit():
                    continue
            if key == "style":
                safe_styles: list[str] = []
                for declaration in value.split(";"):
                    if ":" not in declaration:
                        continue
                    prop, raw_prop_value = declaration.split(":", 1)
                    prop = prop.strip().lower()
                    prop_value = raw_prop_value.strip()
                    if prop not in ALLOWED_STYLE_PROPS:
                        continue
                    if not prop_value:
                        continue
                    if any(token in prop_value.lower() for token in ("javascript:", "expression(", "url(")):
                        continue
                    safe_styles.append(f"{prop}: {prop_value}")
                if not safe_styles:
                    continue
                value = "; ".join(safe_styles)

            rendered_attrs.append(f' {key}="{escape(value, quote=True)}"')
        return "".join(rendered_attrs)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in ALLOWED_CONTENT_HTML_TAGS:
            return
        self._chunks.append(f"<{tag}{self._sanitize_attrs(tag, attrs)}>")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in ALLOWED_CONTENT_HTML_TAGS:
            return
        self._chunks.append(f"<{tag}{self._sanitize_attrs(tag, attrs)}>")

    def handle_endtag(self, tag: str) -> None:
        if tag in ALLOWED_CONTENT_HTML_TAGS:
            self._chunks.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        self._chunks.append(escape(data))

    def handle_entityref(self, name: str) -> None:
        self._chunks.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self._chunks.append(f"&#{name};")

    def get_html(self) -> str:
        return "".join(self._chunks)


def sanitize_content_html(raw_html: str | None) -> str:
    if not raw_html:
        return ""
    sanitizer = _ContentHtmlSanitizer()
    sanitizer.feed(raw_html)
    sanitizer.close()
    return sanitizer.get_html()


def _strip_html_tags(raw: str) -> str:
    text = re.sub(r"<[^>]+>", "", raw)
    return unescape(text).strip()


def parse_visual_editor_rows(payload: str) -> list[list[str]]:
    source = (payload or "").strip()
    if not source:
        return []

    data = _safe_json_loads(source)
    if isinstance(data, list):
        rows: list[list[str]] = []
        for item in data:
            if isinstance(item, list):
                rows.append([str(cell).strip() for cell in item])
            elif isinstance(item, dict):
                rows.append([str(value).strip() for value in item.values()])
        if rows:
            return rows

    if "<" in source and ">" in source:
        tr_blocks = re.findall(r"<tr[^>]*>(.*?)</tr>", source, flags=re.IGNORECASE | re.DOTALL)
        if tr_blocks:
            rows = []
            for block in tr_blocks:
                cells = re.findall(r"<(?:td|th)[^>]*>(.*?)</(?:td|th)>", block, flags=re.IGNORECASE | re.DOTALL)
                if cells:
                    rows.append([_strip_html_tags(cell) for cell in cells])
            if rows:
                return rows

        li_blocks = re.findall(r"<li[^>]*>(.*?)</li>", source, flags=re.IGNORECASE | re.DOTALL)
        if li_blocks:
            return [[_strip_html_tags(item)] for item in li_blocks if _strip_html_tags(item)]

        normalized_html = re.sub(r"<br\s*/?>", "\n", source, flags=re.IGNORECASE)
        normalized_html = re.sub(r"</(?:p|div|h\d)>", "\n", normalized_html, flags=re.IGNORECASE)
        source = _strip_html_tags(normalized_html)

    return [[part.strip() for part in line.split("|")] for line in source.splitlines() if line.strip()]


def _safe_json_loads(payload: str | None) -> dict | list | None:
    if not payload:
        return None
    try:
        data = json.loads(payload)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return data if isinstance(data, (dict, list)) else None


def _build_archive_bracket_columns(payload: str | None) -> tuple[list[dict[str, object]], str | None]:
    data = _safe_json_loads(payload)
    if data is None:
        return [], "Сетка недоступна: архив сохранен в устаревшем или текстовом формате."

    if isinstance(data, list) and data and all(isinstance(stage, dict) and "participants" in stage for stage in data):
        columns: list[dict[str, object]] = []
        for stage in data:
            participants = stage.get("participants") if isinstance(stage.get("participants"), list) else []
            matches = stage.get("matches") if isinstance(stage.get("matches"), list) else []
            participants_by_group: dict[int, list[dict[str, object]]] = {}
            participant_name_by_user_id: dict[int, str] = {}
            for participant in participants:
                if not isinstance(participant, dict):
                    continue
                user_id = participant.get("user_id")
                seed = participant.get("seed")
                if not isinstance(seed, int):
                    continue
                group_number = get_stage_group_number_by_seed(seed)
                participants_by_group.setdefault(group_number, []).append(participant)
                if isinstance(user_id, int):
                    participant_name_by_user_id[user_id] = str(participant.get("nickname") or f"#{user_id}")

            stage_matches: list[dict[str, object]] = []
            if matches:
                sorted_matches = sorted(
                    [item for item in matches if isinstance(item, dict)],
                    key=lambda item: (item.get("group_number") or 0, item.get("match_number") or 0),
                )
                for match in sorted_matches:
                    group_number = match.get("group_number")
                    if not isinstance(group_number, int):
                        continue
                    group_participants = sorted(
                        participants_by_group.get(group_number, []),
                        key=lambda item: item.get("seed") or 0,
                    )
                    winner_user_id = match.get("winner_user_id")
                    stage_matches.append(
                        {
                            "label": get_stage_group_label(str(stage.get("key") or "stage_2"), group_number),
                            "status": str(match.get("state") or "pending"),
                            "participants": [
                                {
                                    "nickname": str(item.get("nickname") or f"#{item.get('user_id') or '?'}"),
                                    "points": item.get("points") or 0,
                                    "is_winner": isinstance(winner_user_id, int) and item.get("user_id") == winner_user_id,
                                }
                                for item in group_participants
                            ],
                            "winner_name": participant_name_by_user_id.get(winner_user_id, "") if isinstance(winner_user_id, int) else "",
                        }
                    )
            else:
                for group_number in sorted(participants_by_group.keys()):
                    stage_matches.append(
                        {
                            "label": get_stage_group_label(str(stage.get("key") or "stage_2"), group_number),
                            "status": "pending",
                            "participants": [
                                {
                                    "nickname": str(item.get("nickname") or f"#{item.get('user_id') or '?'}"),
                                    "points": item.get("points") or 0,
                                    "is_winner": False,
                                }
                                for item in sorted(participants_by_group[group_number], key=lambda item: item.get("seed") or 0)
                            ],
                            "winner_name": "",
                        }
                    )

            columns.append(
                {
                    "title": str(stage.get("title") or stage.get("key") or "Этап"),
                    "matches": stage_matches,
                }
            )

        if columns:
            return columns, None

    if isinstance(data, dict) and isinstance(data.get("rounds"), list):
        columns = []
        for round_item in data["rounds"]:
            if not isinstance(round_item, dict):
                continue
            round_matches = []
            for match in round_item.get("matches", []):
                if not isinstance(match, dict):
                    continue
                players = [str(player) for player in match.get("players", []) if str(player).strip()]
                winner = str(match.get("winner") or "")
                round_matches.append(
                    {
                        "label": str(match.get("label") or "Матч"),
                        "status": str(match.get("status") or "finished"),
                        "participants": [
                            {"nickname": player, "points": "", "is_winner": bool(winner and player == winner)}
                            for player in players
                        ],
                        "winner_name": winner,
                    }
                )
            columns.append({"title": str(round_item.get("title") or "Раунд"), "matches": round_matches})
        if columns:
            return columns, None

    if isinstance(data, list):
        return [], f"Сетка сохранена в альтернативном формате (элементов: {len(data)})."
    if isinstance(data, dict):
        return [], f"Сетка сохранена в альтернативном формате (полей: {len(data.keys())})."
    return [], "Сетка недоступна: формат архива не поддерживается."




def _apply_archive_stage_highlight(stage_key: str, participants: list[dict[str, object]]) -> list[dict[str, object]]:
    if stage_key == "stage_1":
        stage_key = "group_stage"
    elif stage_key == "stage_3":
        stage_key = "stage_1_4"

    normalized_stage_key = normalize_stage_key(stage_key)
    for participant in participants:
        participant["is_tournament_winner"] = bool(participant.get("is_winner"))

    ranked_participants = sorted(
        participants,
        key=lambda participant: int(participant.get("points") or 0),
        reverse=True,
    )

    return _apply_stage_highlight_rules(
        normalized_stage_key,
        ranked_participants,
        allow_live_candidate_highlight=False,
    )

def _build_archive_tree_vm(columns: list[dict[str, object]]) -> dict[str, object]:
    stage_keys = ["group_stage", "stage_2", "stage_1_4", "stage_final"]
    stages: list[dict[str, object]] = []
    for idx, column in enumerate(columns):
        matches = column.get("matches") if isinstance(column.get("matches"), list) else []
        stage_key = stage_keys[idx] if idx < len(stage_keys) else f"stage_{idx}"
        stages.append(
            {
                "key": stage_key,
                "title": str(column.get("title") or f"Stage {idx + 1}"),
                "level": idx,
                "matches": [
                    {
                        "match_id": f"{stage_key}:{match_idx}",
                        "label": str(match.get("label") or match_idx),
                        "status": str(match.get("status") or "pending"),
                        "participants": _apply_archive_stage_highlight(
                            stage_key, list(match.get("participants") or [])
                        ),
                        "schedule_text": "TBD",
                        "lobby_password": "TBD",
                        "incoming_sources": [],
                    }
                    for match_idx, match in enumerate(matches, start=1)
                    if isinstance(match, dict)
                ],
            }
        )
    return {"stages": stages}


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
    groups_count = get_stage_group_count(stage_key)
    if is_limited_stage(stage_key):
        group_size = get_stage_group_size(stage_key)
        size_groups = max((stage_size or 0) // group_size, 0)
        if size_groups:
            groups_count = size_groups
        elif participants_count is not None:
            groups_count = max(math.ceil((participants_count or 0) / group_size), 0)
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

    if is_final_stage(stage.key, stage_size=stage.stage_size, scoring_mode=stage.scoring_mode):
        return progress_items, any(match.state == "finished" for match in stage_matches)

    return progress_items, False


def is_playoff_stage_finished(stage: PlayoffStage) -> bool:
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


def get_admin_active_playoff_stage_key(playoff_stages: list[PlayoffStage], stage_progression_keys: list[str]) -> str | None:
    if not playoff_stages:
        return None

    playoff_stage_by_key = {stage.key: stage for stage in playoff_stages}

    for stage_key in stage_progression_keys:
        stage = playoff_stage_by_key.get(stage_key)
        if stage and stage.is_started and not is_playoff_stage_finished(stage):
            return stage_key

    started_stages_in_progression = [
        playoff_stage_by_key[stage_key]
        for stage_key in stage_progression_keys
        if stage_key in playoff_stage_by_key and playoff_stage_by_key[stage_key].is_started
    ]
    for stage in started_stages_in_progression:
        if is_stage_allowed_for_manual_winner(stage):
            return stage.key

    if started_stages_in_progression:
        return max(started_stages_in_progression, key=lambda item: item.stage_order if item.stage_order is not None else -1).key

    return get_default_playoff_stage_key(playoff_stages, stage_progression_keys)

def can_submit_playoff_stage_results(stage: PlayoffStage) -> bool:
    return get_playoff_stage_submit_status(stage)["can_submit"]


def is_stage_allowed_for_manual_winner(stage: PlayoffStage | None) -> bool:
    if not stage:
        return False
    return is_final_stage(
        stage.key,
        stage_size=stage.stage_size,
        scoring_mode=stage.scoring_mode,
    )


def get_playoff_stage_submit_status(stage: PlayoffStage) -> dict[str, bool | str]:
    if can_submit_stage_results(stage.key, stage_size=stage.stage_size, scoring_mode=stage.scoring_mode):
        return {"can_submit": True, "reason": ""}

    normalized_stage_key = normalize_stage_key(stage.key)
    if normalized_stage_key not in set(get_playoff_stage_sequence_keys()):
        return {"can_submit": False, "reason": "stage_key_unrecognized"}

    scoring_mode = (stage.scoring_mode or "").strip().lower()
    if scoring_mode not in FINAL_STAGE_SCORING_MODES:
        return {"can_submit": False, "reason": "stage_scoring_mode_not_final"}

    try:
        stage_size = int(stage.stage_size) if stage.stage_size is not None else None
    except (TypeError, ValueError):
        stage_size = None
    if stage_size != 8:
        return {"can_submit": False, "reason": "stage_size_not_final"}

    return {"can_submit": False, "reason": "stage_not_limited_and_not_final"}




def can_change_playoff_group_meta(stage: PlayoffStage, match: PlayoffMatch) -> bool:
    stage_config = get_admin_playoff_stage_config(stage.key)
    if stage_config.game_limit is None:
        return True
    return match.game_number <= stage_config.game_limit


async def can_submit_playoff_stage_results_with_db(db: AsyncSession, stage: PlayoffStage) -> bool:
    """Разрешает запись результатов для лимитированных/финальных стадий и для фактического последнего этапа.

    Последний этап определяется по отсутствию следующей стадии с ``stage_order + 1``.
    Это защищает админку от исторически неконсистентных ключей стадии (например,
    когда в БД финал имеет нестандартный ``key``, но это реально последняя стадия).
    """
    if can_submit_playoff_stage_results(stage):
        return True

    next_stage = await db.scalar(select(PlayoffStage).where(PlayoffStage.stage_order == stage.stage_order + 1))
    return next_stage is None


def get_empty_active_stage_alert(playoff_stages: list[PlayoffStage]) -> str | None:
    stage_by_order = {
        stage_order: stage
        for stage in playoff_stages
        if (stage_order := getattr(stage, "stage_order", None)) is not None
    }
    for stage in playoff_stages:
        if not getattr(stage, "is_started", False) or getattr(stage, "participants", None):
            continue

        stage_order = getattr(stage, "stage_order", None)
        previous_stage = stage_by_order.get(stage_order - 1) if stage_order is not None else None
        if previous_stage and is_limited_stage(getattr(previous_stage, "key", "")):
            return (
                f"Этап {getattr(stage, 'title', '-')} активен, но участников 0: "
                f"завершите {getattr(previous_stage, 'title', '-')} через Stage Finish (/admin/playoff/stage/finish)."
            )
        return f"Этап {getattr(stage, 'title', '-')} активен, но участников 0."

    return None


def get_playoff_stage_integrity_alert(playoff_stages: list[PlayoffStage]) -> str | None:
    if not playoff_stages:
        return None

    known_stage_keys = set(get_playoff_stage_sequence_keys())
    stage_order_key_pairs = {(stage.stage_order, normalize_stage_key(stage.key)) for stage in playoff_stages}
    expected_pairs = set(EXPECTED_32_PLAYER_STAGE_ORDER_PAIRS)
    issues: list[dict[str, str]] = []
    legacy_stage_aliases = set(LEGACY_STAGE_KEY_ALIASES)

    for stage in playoff_stages:
        raw_key = (stage.key or "").strip().lower()
        normalized_key = normalize_stage_key(stage.key)
        if normalized_key in known_stage_keys:
            if raw_key in legacy_stage_aliases and raw_key != normalized_key:
                issues.append(
                    {
                        "kind": "legacy_alias",
                        "message": f"Этап id={stage.id} использует legacy alias key='{stage.key}'.",
                    }
                )
            continue

        issues.append(
            {
                "kind": "unknown_key",
                "message": f"Этап id={stage.id} имеет неизвестный key='{stage.key}' (alias не распознан).",
            }
        )

    has_32_player_stage = any(int(stage.stage_size or 0) == 32 for stage in playoff_stages)
    if has_32_player_stage:
        missing_pairs = expected_pairs - stage_order_key_pairs
        if missing_pairs:
            missing_pairs_text = ", ".join([f"({order}, {key})" for order, key in sorted(missing_pairs)])
            issues.append(
                {
                    "kind": "missing_required_pairs",
                    "message": "Для 32-игрокового сценария отсутствуют обязательные пары (stage_order, key): "
                    f"[{missing_pairs_text}]",
                }
            )

        extra_pairs = stage_order_key_pairs - expected_pairs
        if extra_pairs:
            extra_pairs_text = ", ".join([f"({order}, {key})" for order, key in sorted(extra_pairs)])
            issues.append(
                {
                    "kind": "extra_pairs",
                    "message": "Для 32-игрокового сценария найдены лишние playoff-стадии (stage_order, key): "
                    f"[{extra_pairs_text}]",
                }
            )

    if has_32_player_stage and stage_order_key_pairs != expected_pairs:
        current_pairs = ", ".join([f"({stage.stage_order}, {normalize_stage_key(stage.key)})" for stage in playoff_stages])
        expected_pairs_text = ", ".join([f"({order}, {key})" for order, key in EXPECTED_32_PLAYER_STAGE_ORDER_PAIRS])
        issues.append(
            {
                "kind": "pairs_mismatch_summary",
                "message": "Для 32-игрокового сценария нарушены пары (stage_order, key): "
                f"ожидается [{expected_pairs_text}], сейчас [{current_pairs}].",
            }
        )

    final_stage = next((stage for stage in playoff_stages if normalize_stage_key(stage.key) == "stage_final"), None)
    if final_stage is None:
        final_stage = next((stage for stage in playoff_stages if stage.stage_order == EXPECTED_32_PLAYER_STAGE_ORDER_PAIRS[-1][0]), None)
    if final_stage:
        if int(final_stage.stage_size or 0) != 8:
            issues.append(
                {
                    "kind": "invalid_final_size",
                    "message": f"Финальная стадия id={final_stage.id} должна иметь stage_size=8, сейчас {final_stage.stage_size}.",
                }
            )

        scoring_mode = (final_stage.scoring_mode or "").strip().lower()
        if scoring_mode != "final_22_top1":
            issues.append(
                {
                    "kind": "invalid_final_scoring",
                    "message": "Для финальной стадии предпочтителен scoring_mode='final_22_top1' "
                    f"(сейчас '{final_stage.scoring_mode or '∅'}').",
                }
            )

    if not issues:
        return None
    issue_messages = [issue["message"] for issue in issues]
    return "⚠️ Проверка целостности playoff_stages: " + " ".join(issue_messages)


def _normalize_direct_invite_stage(raw_value: str | None) -> str | None:
    value = (raw_value or "").strip() or None
    if value not in ALLOWED_DIRECT_INVITE_STAGES:
        raise ValueError("invalid direct invite stage")
    return value


def _validate_user_update_payload(basket: str, direct_invite_stage: str | None) -> dict[str, str | None]:
    allowed_baskets = {item.value for item in Basket}
    if basket not in allowed_baskets:
        raise ValueError("invalid basket")

    normalized_stage = _normalize_direct_invite_stage(direct_invite_stage)
    return {
        "basket": basket,
        "direct_invite_stage": normalized_stage,
    }


def _display_nickname(user: User | None, fallback: str) -> str:
    if not user:
        return fallback

    fallback_name = (fallback or "").strip() or "-"
    game_nickname = (user.game_nickname or "").strip()
    profile_nickname = (user.nickname or "").strip()
    base_name = game_nickname or profile_nickname or fallback_name

    highest_rank = (user.highest_rank or "").strip() or "-"
    return f"{base_name} ({highest_rank})"


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


def redirect_with_admin_emergency_msg(msg_key: str, details: str | None = None) -> RedirectResponse:
    params: dict[str, str] = {"msg": msg_key}
    if details:
        params["details"] = details
    return RedirectResponse(url=f"/admin/emergency?{urlencode(params)}", status_code=303)


def _parse_user_id_list(raw_user_ids: str) -> list[int]:
    normalized = [part.strip() for part in (raw_user_ids or "").split(",") if part.strip()]
    user_ids: list[int] = []
    for value in normalized:
        user_id = int(value)
        if user_id in user_ids:
            raise ValueError("duplicate_user")
        user_ids.append(user_id)
    if not user_ids:
        raise ValueError("empty_user_ids")
    return user_ids


async def _is_tournament_finished(db: AsyncSession) -> bool:
    setting = await db.scalar(select(SiteSetting).where(SiteSetting.key == "tournament_finished"))
    return bool(isinstance(setting, SiteSetting) and setting.value == "1")


async def _check_emergency_safety_lock(db: AsyncSession, *, confirm_final: bool) -> tuple[bool, str | None]:
    if await _is_tournament_finished(db) and not confirm_final:
        return False, "final_locked_require_confirmation"
    return True, None


async def _log_emergency_action(
    db: AsyncSession,
    *,
    request: Request,
    action_type: str,
    dry_run: bool,
    target_stage_id: int | None,
    details: dict[str, object],
) -> None:
    admin_name = request.cookies.get(ADMIN_SESSION_COOKIE, "admin")[:120] or "admin"
    db.add(
        EmergencyOperationLog(
            admin_name=admin_name,
            action_type=action_type,
            dry_run=dry_run,
            target_stage_id=target_stage_id,
            details_json=json.dumps(details, ensure_ascii=False),
        )
    )


async def _render_admin_emergency_page(
    request: Request,
    db: AsyncSession,
    *,
    preview_title: str | None = None,
    preview_payload: dict[str, object] | None = None,
):
    judge_setting = await db.scalar(select(SiteSetting).where(SiteSetting.key == "judge_login_token"))
    judge_login_token = (judge_setting.value if judge_setting else "")
    judge_login_url = ""
    if judge_login_token:
        judge_login_url = str(request.url_for("admin_page")).rstrip("/") + f"?judge_token={judge_login_token}"
    registration_open = await get_registration_open(db)
    technical_works_enabled = await get_technical_works_enabled(db)

    manual_draw_users = (
        await db.scalars(
            select(User)
            .where(User.basket != Basket.INVITED.value)
            .order_by(User.nickname.asc(), User.created_at.desc())
        )
    ).all()
    playoff_stages = await get_playoff_stages_with_data(db)
    emergency_logs = (
        await db.scalars(select(EmergencyOperationLog).order_by(EmergencyOperationLog.created_at.desc(), EmergencyOperationLog.id.desc()).limit(30))
    ).all()
    return templates.TemplateResponse(
        request,
        "admin_emergency.html",
        template_context(
            request,
            playoff_stages=playoff_stages,
            manual_draw_users=manual_draw_users,
            emergency_logs=emergency_logs,
            preview_title=preview_title,
            preview_payload=preview_payload,
            registration_open=registration_open,
            technical_works_enabled=technical_works_enabled,
            judge_login_url=judge_login_url,
        ),
    )


async def _playoff_stage_exists(db: AsyncSession, stage_id: int) -> bool:
    """Проверяет, что этап плей-офф с указанным `stage_id` существует в БД."""
    return await db.scalar(select(PlayoffStage.id).where(PlayoffStage.id == stage_id)) is not None


async def _get_playoff_stage(db: AsyncSession, stage_id: int) -> PlayoffStage | None:
    return await db.scalar(select(PlayoffStage).where(PlayoffStage.id == stage_id))


async def get_registration_open(db: AsyncSession) -> bool:
    # Получаем флаг доступности регистрации из настроек.
    record = await db.scalar(select(SiteSetting).where(SiteSetting.key == "registration_open"))
    return (record.value == "1") if record else True


async def get_technical_works_enabled(db: AsyncSession) -> bool:
    record = await db.scalar(select(SiteSetting).where(SiteSetting.key == "technical_works_enabled"))
    return bool(record and record.value == "1")


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


async def validate_group_draw_integrity(db: AsyncSession, *, profile_key: str | None = None) -> tuple[bool, str | None]:
    profile_spec = get_tournament_profile_spec(profile_key)
    expected_groups_count = int(profile_spec["stage_1_groups_count"])
    expected_group_size = 8
    expected_participants = expected_groups_count * expected_group_size

    groups = list((await db.scalars(select(TournamentGroup).where(TournamentGroup.stage == "group_stage"))).all())
    if not groups:
        return False, "draw_not_found"
    if len(groups) != expected_groups_count:
        return False, "draw_profile_groups_mismatch"

    group_ids = [group.id for group in groups]
    members = list((await db.scalars(select(GroupMember).where(GroupMember.group_id.in_(group_ids)))).all())
    by_group: dict[int, list[GroupMember]] = {}
    all_user_ids: list[int] = []
    for member in members:
        by_group.setdefault(member.group_id, []).append(member)
        all_user_ids.append(member.user_id)

    if len(all_user_ids) != len(set(all_user_ids)):
        return False, "draw_duplicates_found"
    if len(all_user_ids) != expected_participants:
        return False, "draw_profile_participants_mismatch"

    for group in groups:
        group_members = by_group.get(group.id, [])
        if not group_members:
            return False, "draw_empty_group"
        if len(group_members) != expected_group_size:
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


def resolve_chat_nick_color(color_cookie: str | None) -> str:
    try:
        return normalize_chat_nick_color(color_cookie or "")
    except ValueError:
        return CHAT_NICK_COLORS[0]


def generate_chat_sender_token() -> str:
    return uuid.uuid4().hex


def resolve_chat_sender_token(chat_sender_cookie: str | None) -> tuple[str, bool]:
    chat_sender = (chat_sender_cookie or "").strip().lower()
    if CHAT_SENDER_TOKEN_RE.fullmatch(chat_sender):
        return chat_sender, False
    return generate_chat_sender_token(), True


def _build_chat_messages_payload(chat_messages: list[ChatMessage]) -> list[dict[str, str | int | bool]]:
    default_nick_color = CHAT_NICK_COLORS[0]
    return [
        {
            "id": msg.id,
            "temp_nick": msg.temp_nick,
            "message": msg.message,
            "nick_color": msg.nick_color or default_nick_color,
            "is_admin": msg.temp_nick == "@Admin",
            "created_at_display": msg.created_at.strftime("%d.%m.%y %H:%M:%S"),
        }
        for msg in chat_messages
    ]


class ContentLocalePayload(BaseModel):
    rules_body: str


def localized_attr(entity: object, base_name: str, lang: str) -> str:
    value = getattr(entity, f"{base_name}_{lang}", "") or ""
    if value:
        return str(value)
    return str(getattr(entity, f"{base_name}_ru", "") or "")


def dump_admin_content_for_lang(
    lang: str,
    rules_content: RulesContent,
) -> ContentLocalePayload:
    return ContentLocalePayload(
        rules_body=localized_attr(rules_content, "body", lang),
    )


async def get_or_create_rules_content(db: AsyncSession) -> RulesContent:
    row = await db.scalar(select(RulesContent).where(RulesContent.id == 1))
    if row:
        return row
    row = RulesContent(id=1, body_ru="", body_en="")
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
    lang = get_lang(request.cookies.get("lang"))
    chat_messages = (await db.scalars(select(ChatMessage).order_by(desc(ChatMessage.id)).limit(20))).all()
    registration_open = await get_registration_open(db)
    tournament_started = await get_tournament_started(db)
    chat_settings = await get_chat_settings(db)
    donors = (await db.scalars(select(Donor.amount))).all()
    total_sponsors_amount = parse_donor_amount("0")
    for donor_amount in donors:
        total_sponsors_amount += parse_donor_amount(str(donor_amount))

    total_sponsors_amount_rub, total_sponsors_amount_usd = to_rub_and_usd_display_amounts(total_sponsors_amount)
    prize_pool_wave_enabled = total_sponsors_amount >= Decimal("1000")
    return templates.TemplateResponse(
        request,
        "index.html",
        template_context(
            request,
            lang=lang,
            chat_messages=list(reversed(chat_messages)),
            chat_messages_payload=_build_chat_messages_payload(list(reversed(chat_messages))),
            chat_nick_colors=CHAT_NICK_COLORS,
            registration_open=registration_open,
            tournament_started=tournament_started,
            chat_settings=chat_settings,
            total_sponsors_amount_rub=total_sponsors_amount_rub,
            total_sponsors_amount_usd=total_sponsors_amount_usd,
            prize_pool_wave_enabled=prize_pool_wave_enabled,
            chat_saved_nick=unquote((request.cookies.get("chat_nick") or "")).strip()[:120],
            chat_saved_nick_color=resolve_chat_nick_color(request.cookies.get("chat_nick_color")),
        ),
    )


@router.post("/register")
async def register(
    request: Request,
    steam_input: str = Form(...),
    nickname: str = Form(...),
    telegram: str = Form(default=""),
    rules_ack: str | None = Form(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Регистрирует пользователя, если по steam_id запись в БД отсутствует."""
    if await get_tournament_started(db):
        return redirect_with_msg("/", "registration_closed")

    if not await get_registration_open(db):
        return redirect_with_msg("/", "registration_closed")

    if rules_ack not in {"1", "on", "true"}:
        return redirect_with_msg("/", "msg_rules_ack_required")

    cleaned_nickname = nickname.strip()
    if not cleaned_nickname or len(cleaned_nickname) > 120:
        return redirect_with_msg("/", "msg_invalid_request")

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
        nickname=cleaned_nickname,
        steam_input=steam_input,
        steam_id=steam_id,
        game_nickname=profile["game_nickname"],
        current_rank=profile["current_rank"],
        highest_rank=profile["highest_rank"],
        telegram=telegram or None,
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
    await chat_event_broker.publish()
    redirect = RedirectResponse(url="/#chat", status_code=303)
    redirect.set_cookie("chat_nick", quote(safe_nick, safe=""), max_age=60 * 60 * 24 * 365, samesite="lax")
    redirect.set_cookie("chat_nick_color", safe_color, max_age=60 * 60 * 24 * 365, samesite="lax")
    if should_set_chat_sender_cookie:
        redirect.set_cookie("chat_sender", chat_sender, max_age=60 * 60 * 24 * 365, samesite="lax")
    return redirect


@router.get("/chat/messages")
async def chat_messages_api(db: AsyncSession = Depends(get_db)):
    chat_messages = (await db.scalars(select(ChatMessage).order_by(desc(ChatMessage.id)).limit(20))).all()
    payload = _build_chat_messages_payload(list(reversed(chat_messages)))
    return {"messages": payload}


@router.get("/chat/stream")
async def chat_stream(request: Request):
    async def event_stream():
        last_seen_version = -1
        while True:
            if await request.is_disconnected():
                break

            try:
                last_seen_version = await asyncio.wait_for(chat_event_broker.wait_for_update(last_seen_version), timeout=25)
                yield "event: chat_update\ndata: {}\n\n"
            except asyncio.TimeoutError:
                yield "event: ping\ndata: {}\n\n"

    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
    }
    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=headers)


@router.get("/participants", response_class=HTMLResponse)
async def participants(
    request: Request,
    basket: str = Query(Basket.QUEEN.value),
    rank_priority: str | None = Query(None),
    view: str = Query("baskets"),
    db: AsyncSession = Depends(get_db),
):
    # Показываем участников единым списком с приоритетом выбранного ранга.
    rank_tabs = [
        {"main_basket": Basket.QUEEN.value, "reserve_basket": Basket.QUEEN_RESERVE.value, "label": "Queen"},
        {"main_basket": Basket.KING.value, "reserve_basket": Basket.KING_RESERVE.value, "label": "King"},
        {"main_basket": Basket.ROOK.value, "reserve_basket": Basket.ROOK_RESERVE.value, "label": "Rook"},
        {"main_basket": Basket.BISHOP.value, "reserve_basket": Basket.BISHOP_RESERVE.value, "label": "Bishop"},
        {"main_basket": Basket.LOW_RANK.value, "reserve_basket": Basket.LOW_RANK_RESERVE.value, "label": "Low Rank"},
    ]
    basket_pairs = BASKET_PAIRS
    base_rank_order = [
        Basket.QUEEN.value,
        Basket.KING.value,
        Basket.ROOK.value,
        Basket.BISHOP.value,
        Basket.LOW_RANK.value,
    ]
    allowed_priorities = set(base_rank_order)

    selected_priority = rank_priority or basket
    if selected_priority not in allowed_priorities:
        selected_priority = Basket.QUEEN.value

    ordered_base_ranks = [selected_priority, *[rank for rank in base_rank_order if rank != selected_priority]]
    basket_order: list[str] = []
    for rank_name in ordered_base_ranks:
        for main_basket, reserve_basket in basket_pairs:
            if rank_name == main_basket:
                basket_order.extend([main_basket, reserve_basket])
                break
    basket_order_map = {basket_name: index for index, basket_name in enumerate(basket_order)}
    basket_order_case = case(
        *( (User.basket == basket_name, index) for basket_name, index in basket_order_map.items() ),
        else_=len(basket_order_map),
    )

    queen_rank_numeric = case(
        (User.highest_rank.like("Queen#%"), func.cast(func.substr(User.highest_rank, 7), Integer)),
        else_=None,
    )
    queen_pair_order_case = case(
        (User.basket.in_([Basket.QUEEN.value, Basket.QUEEN_RESERVE.value]), func.coalesce(queen_rank_numeric, 999999)),
        else_=999999,
    )

    direct_invite_users: list[User] = []
    users: list[User] = []

    if view == "direct_invites":
        invited_users = (
            await db.scalars(
                select(User)
                .where(
                    User.direct_invite_stage == "stage_2",
                )
                .order_by(User.created_at)
            )
        ).all()
        direct_invite_users = list(invited_users)
    else:
        view = "baskets"
        users = (
            await db.scalars(
                select(User).order_by(
                    basket_order_case,
                    queen_pair_order_case,
                    User.created_at,
                    User.id,
                )
            )
        ).all()

    is_empty = not direct_invite_users if view == "direct_invites" else not users

    return templates.TemplateResponse(
        request,
        "participants.html",
        template_context(
            request,
            basket=selected_priority,
            rank_priority=selected_priority,
            view=view,
            basket_pairs=basket_pairs,
            basket_tabs=rank_tabs,
            users=users,
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

    direct_invite_users = list(
        (
            await db.scalars(
                select(User)
                .where(User.direct_invite_stage == "stage_2")
                .order_by(User.direct_invite_group_number.asc().nullslast(), User.created_at)
            )
        ).all()
    )
    direct_invite_ids = [user.id for user in direct_invite_users]
    direct_invite_groups = {
        user.id: int(user.direct_invite_group_number)
        for user in direct_invite_users
        if user.direct_invite_group_number is not None
    }
    tournament_profile_spec = await get_current_tournament_profile_spec(db)

    users = list((await db.scalars(select(User))).all())
    user_by_id = {user.id: user for user in users}

    winner_settings = list(
        (
            await db.scalars(
                select(SiteSetting).where(SiteSetting.key.in_(("tournament_winner_user_id", "tournament_winner_nickname")))
            )
        ).all()
    )
    winner_setting_by_key = {setting.key: setting for setting in winner_settings}

    winner_user_id_setting = winner_setting_by_key.get("tournament_winner_user_id")
    winner_user_id: int | None = None
    if winner_user_id_setting and winner_user_id_setting.value:
        try:
            winner_user_id = int(winner_user_id_setting.value)
        except ValueError:
            winner_user_id = None

    winner_nickname_setting = winner_setting_by_key.get("tournament_winner_nickname")
    winner_nickname = (winner_nickname_setting.value or "").strip() if winner_nickname_setting else ""
    if winner_user_id and not winner_nickname:
        winner_nickname = user_by_id.get(winner_user_id).nickname if user_by_id.get(winner_user_id) else ""

    try:
        stage_columns = build_bracket_columns(
            groups,
            playoff_stages,
            user_by_id,
            direct_invite_ids,
            winner_user_id,
            direct_invite_groups=direct_invite_groups,
        )
    except TypeError:
        stage_columns = build_bracket_columns(
            groups,
            playoff_stages,
            user_by_id,
            direct_invite_ids,
            stage_1_promoted_count=int(tournament_profile_spec["stage_1_promoted_count"]),
            stage_2_size=int(tournament_profile_spec["stage_2_size"]),
            direct_invite_groups=direct_invite_groups,
        )

    lang = get_lang(request.cookies.get("lang"))
    active_playoff_stage = next((stage for stage in playoff_stages if stage.is_started), None)
    active_stage_key = active_playoff_stage.key if active_playoff_stage else "group_stage"
    current_stage_display = resolve_current_stage_label(lang, playoff_stages, tournament_started)
    try:
        tournament_tree = build_tournament_tree_vm(
            groups,
            playoff_stages,
            user_by_id,
            direct_invite_ids,
            winner_user_id,
            active_stage_key=active_stage_key,
            direct_invite_groups=direct_invite_groups,
        )
    except TypeError:
        tournament_tree = build_tournament_tree_vm(
            groups,
            playoff_stages,
            user_by_id,
            direct_invite_ids,
            winner_user_id,
            direct_invite_groups=direct_invite_groups,
        )
    playoff_empty_active_stage_alert = get_empty_active_stage_alert(playoff_stages)

    return templates.TemplateResponse(
        request,
        "tournament.html",
        template_context(
            request,
            groups=groups,
            playoff_stages=playoff_stages,
            stage_columns=stage_columns,
            tournament_tree=tournament_tree,
            current_stage_display=current_stage_display,
            playoff_empty_active_stage_alert=playoff_empty_active_stage_alert,
            tournament_winner_user_id=winner_user_id,
            tournament_winner_nickname=winner_nickname,
        ),
    )


@router.get("/donate", response_class=HTMLResponse)
async def donate_page(request: Request, db: AsyncSession = Depends(get_db)):
    # Отдаем страницу донатов.
    lang = get_lang(request.cookies.get("lang"))
    donation_links = (await db.scalars(select(DonationLink).where(DonationLink.is_active.is_(True)).order_by(DonationLink.sort_order, DonationLink.id))).all()
    crypto_wallets = (await db.scalars(select(CryptoWallet).where(CryptoWallet.is_active.is_(True)).order_by(CryptoWallet.sort_order, CryptoWallet.id))).all()
    donors = (await db.scalars(select(Donor).order_by(Donor.sort_order, Donor.id))).all()
    total_sponsors_amount = parse_donor_amount("0")
    for donor in donors:
        total_sponsors_amount += parse_donor_amount(str(donor.amount))
    highlight_amount_setting = await db.scalar(
        select(SiteSetting).where(SiteSetting.key == DONATE_HIGHLIGHT_AMOUNT_SETTING_KEY)
    )
    support_author_visible_setting = await db.scalar(
        select(SiteSetting).where(SiteSetting.key == DONATE_SUPPORT_AUTHOR_VISIBLE_SETTING_KEY)
    )
    show_support_author_block = True
    if support_author_visible_setting:
        show_support_author_block = (support_author_visible_setting.value or "").strip().lower() in {"1", "true", "yes", "on"}
    highlight_amount = (highlight_amount_setting.value or "").strip() if highlight_amount_setting else ""
    display_total_amount = parse_donor_amount(highlight_amount) if highlight_amount else total_sponsors_amount
    total_sponsors_amount_rub, total_sponsors_amount_usd = to_rub_and_usd_display_amounts(display_total_amount)
    prize_pool_display_mode = "rub" if lang == "ru" else "usd"

    donation_links_vm = [
        {"url": item.url, "title_html": sanitize_content_html(localized_attr(item, "title", lang))}
        for item in donation_links
        if (item.category or "general") == "general"
    ]
    bank_cards_vm = [
        {"url": item.url, "title_html": sanitize_content_html(localized_attr(item, "title", lang))}
        for item in donation_links
        if (item.category or "general") == "bank_cards"
    ]
    support_author_vm = [
        {"url": item.url, "title_html": sanitize_content_html(localized_attr(item, "title", lang))}
        for item in donation_links
        if (item.category or "general") == "support_author"
    ]
    crypto_wallets_vm = [
        {
            "wallet_name": item.wallet_name,
            "requisites_html": sanitize_content_html(item.requisites),
        }
        for item in crypto_wallets
    ]
    donors_vm = [
        {
            "name": donor.name,
            "amount": str(donor.amount),
            "message_html": sanitize_content_html(localized_attr(donor, "message", lang)),
        }
        for donor in donors
    ]

    return templates.TemplateResponse(
        request,
        "donate.html",
        template_context(
            request,
            total_sponsors_amount_rub=total_sponsors_amount_rub,
            total_sponsors_amount_usd=total_sponsors_amount_usd,
            prize_pool_display_mode=prize_pool_display_mode,
            donation_links=donation_links_vm,
            bank_cards_links=bank_cards_vm,
            support_author_links=support_author_vm,
            show_support_author_block=show_support_author_block,
            crypto_wallets=crypto_wallets_vm,
            donors=donors_vm,
        ),
    )


@router.get("/rules", response_class=HTMLResponse)
async def rules_page(request: Request, db: AsyncSession = Depends(get_db)):
    # Отдаем страницу правил.
    rules_content = await get_or_create_rules_content(db)
    await db.commit()
    return templates.TemplateResponse(
        request,
        "rules.html",
        template_context(
            request,
            rules_content=rules_content,
            rules_content_html=sanitize_content_html(localized_attr(rules_content, "body", get_lang(request.cookies.get("lang")))),
        ),
    )


@router.get("/archive", response_class=HTMLResponse)
async def archive_page(request: Request, db: AsyncSession = Depends(get_db)):
    # Отдаем страницу архива.
    archive_entries = (await db.scalars(select(ArchiveEntry).where(ArchiveEntry.is_published.is_(True)).order_by(ArchiveEntry.sort_order, ArchiveEntry.id))).all()
    tournament_archives = (
        await db.scalars(
            select(TournamentArchive)
            .where(TournamentArchive.is_public.is_(True))
            .order_by(TournamentArchive.created_at.desc(), TournamentArchive.id.desc())
        )
    ).all()

    for entry in tournament_archives:
        columns, summary = _build_archive_bracket_columns(entry.bracket_payload_json)
        entry.bracket_columns = columns
        entry.bracket_tree = _build_archive_tree_vm(columns) if columns else None
        entry.bracket_summary = summary

    for entry in archive_entries:
        columns, summary = _build_archive_bracket_columns(entry.bracket_payload)
        entry.bracket_columns = columns
        entry.bracket_tree = _build_archive_tree_vm(columns) if columns else None
        entry.bracket_summary = summary

    return templates.TemplateResponse(
        request,
        "archive.html",
        template_context(request, archive_entries=archive_entries, tournament_archives=tournament_archives),
    )


@router.get("/technical-works", response_class=HTMLResponse)
async def technical_works_page(request: Request):
    return templates.TemplateResponse(request, "technical_works.html", template_context(request))


@router.get("/freak", response_class=HTMLResponse)
async def freak_page(request: Request):
    return templates.TemplateResponse(request, "freak.html", template_context(request))




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
    tournament_finished_setting = await db.scalar(select(SiteSetting).where(SiteSetting.key == "tournament_finished"))
    tournament_winner_nickname_setting = await db.scalar(select(SiteSetting).where(SiteSetting.key == "tournament_winner_nickname"))
    tournament_finished = (tournament_finished_setting.value == "1") if tournament_finished_setting else False
    tournament_winner_nickname = tournament_winner_nickname_setting.value if tournament_winner_nickname_setting else ""
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
    manual_draw_main_users = [user for user in manual_draw_users if not str(user.basket or "").endswith("_reserve")]
    manual_draw_reserve_users = [user for user in manual_draw_users if str(user.basket or "").endswith("_reserve")]
    user_rows = (await db.execute(select(User.id, User.nickname))).all()
    users_by_id = {user_id: nickname for user_id, nickname in user_rows}
    stages = (await db.scalars(select(TournamentStage).order_by(TournamentStage.id))).all()
    playoff_stages = await get_playoff_stages_with_data(db)
    active_playoff_stage = get_active_playoff_stage(playoff_stages)

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
    current_tournament_profile_key = await get_current_tournament_profile_key(db)
    current_tournament_profile_spec = await get_current_tournament_profile_spec(db)
    tournament_profile_options = [
        {
            "key": profile_key,
            "title": str(profile_spec["title"]),
        }
        for profile_key, profile_spec in TOURNAMENT_PROFILE_SPECS.items()
    ]
    is_draw_valid, invalid_draw_reason = await validate_group_draw_integrity(
        db,
        profile_key=current_tournament_profile_key,
    )
    if is_draw_valid:
        invalid_draw_reason = None
    group_stage_finished = bool(playoff_stages)
    active_stage_key = None
    if not tournament_started:
        active_stage_key = None
    elif not group_stage_finished:
        active_stage_key = "group_stage"
    else:
        active_stage_key = get_admin_active_playoff_stage_key(playoff_stages, stage_progression_keys)

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
                            "eighth_places": participant.eighth_places or 0,
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
    current_playoff_stage_submit_status = (
        get_playoff_stage_submit_status(current_playoff_stage)
        if current_playoff_stage
        else {"can_submit": False, "reason": "stage_key_unrecognized"}
    )
    current_playoff_stage_can_submit_results = current_playoff_stage_submit_status["can_submit"]
    current_playoff_stage_is_final = is_stage_allowed_for_manual_winner(current_playoff_stage)
    current_stage_groups = playoff_stage_groups.get(current_playoff_stage.id, []) if current_playoff_stage else []
    current_stage_participants = playoff_stage_participants.get(current_playoff_stage.id, []) if current_playoff_stage else []
    playoff_stage_finish_progress: list[dict[str, int | str]] = []
    playoff_stage_finish_ready = False
    playoff_stage_finish_progress_limit: int | str = GROUP_STAGE_GAME_LIMIT
    if current_playoff_stage:
        playoff_stage_finish_progress, playoff_stage_finish_ready = build_playoff_stage_finish_status(current_playoff_stage)
        playoff_stage_finish_progress_limit = GROUP_STAGE_GAME_LIMIT if is_limited_stage(current_playoff_stage.key) else "∞"
    playoff_empty_active_stage_alert = get_empty_active_stage_alert(playoff_stages)
    playoff_stage_integrity_alert = get_playoff_stage_integrity_alert(playoff_stages)
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
            current_tournament_profile_key=current_tournament_profile_key,
            current_tournament_profile_spec=current_tournament_profile_spec,
            tournament_profile_options=tournament_profile_options,
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
            manual_draw_main_users=manual_draw_main_users,
            manual_draw_reserve_users=manual_draw_reserve_users,
            group_user_choices=group_user_choices,
            group_stage_table_members=group_stage_table_members,
            playoff_stage_participants=playoff_stage_participants,
            playoff_stage_groups=playoff_stage_groups,
            active_playoff_stage=active_playoff_stage,
            active_stage_key=active_stage_key,
            current_playoff_stage=current_playoff_stage,
            current_playoff_stage_config=current_playoff_stage_config,
            current_playoff_stage_submit_status=current_playoff_stage_submit_status,
            current_playoff_stage_can_submit_results=current_playoff_stage_can_submit_results,
            current_playoff_stage_is_final=current_playoff_stage_is_final,
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
            playoff_stage_integrity_alert=playoff_stage_integrity_alert,
            tournament_finished=tournament_finished,
            tournament_winner_nickname=tournament_winner_nickname,
        ),
    )



@router.get("/admin/users", response_class=HTMLResponse)
async def admin_users_page(request: Request, db: AsyncSession = Depends(get_db)):
    users = (await db.scalars(select(User).order_by(desc(User.created_at)))).all()
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
    playoff_stages = list((await db.scalars(select(PlayoffStage).order_by(PlayoffStage.stage_order, PlayoffStage.id))).all())
    stage_group_options = {
        stage.id: list(range(1, max(1, math.ceil(int(stage.stage_size or 0) / 8)) + 1))
        for stage in playoff_stages
    }
    user_playoff_participants = (
        await db.scalars(select(PlayoffParticipant).where(PlayoffParticipant.user_id.in_(list(users_by_id.keys()))))
    ).all() if users_by_id else []
    user_playoff_state = {
        participant.user_id: {
            "stage_id": participant.stage_id,
            "group_number": get_stage_group_number_by_seed(participant.seed),
        }
        for participant in user_playoff_participants
    }
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
            playoff_stages=playoff_stages,
            stage_group_options=stage_group_options,
            user_playoff_state=user_playoff_state,
            basket_pairs=BASKET_PAIRS,
        ),
    )



def _resolve_basket_quick_move(current_basket: str | None, quick_move: str | None) -> str | None:
    if quick_move not in {"to_main", "to_reserve"}:
        return None
    for main_basket, reserve_basket in BASKET_PAIRS:
        if current_basket in {main_basket, reserve_basket}:
            return main_basket if quick_move == "to_main" else reserve_basket
    return None


async def _find_group_seed_for_stage(
    db: AsyncSession,
    *,
    stage_id: int,
    group_number: int,
    stage_size: int,
) -> int:
    participants = list((await db.scalars(select(PlayoffParticipant).where(PlayoffParticipant.stage_id == stage_id))).all())
    occupied = {participant.seed for participant in participants}
    min_seed = ((group_number - 1) * 8) + 1
    max_seed = min(stage_size, group_number * 8)
    for candidate_seed in range(min_seed, max_seed + 1):
        if candidate_seed not in occupied:
            return candidate_seed
    raise ValueError("target_group_is_full")


@router.post("/admin/user/reassign")
async def admin_reassign_user(
    user_id: int = Form(...),
    target_stage_id: int | None = Form(default=None),
    target_group_number: int | None = Form(default=None),
    replace_from_user_id: int | None = Form(default=None),
    quick_move: str | None = Form(default=None),
    db: AsyncSession = Depends(get_db),
):
    user = await db.get(User, user_id)
    if not user:
        return redirect_with_admin_users_msg("msg_operation_failed", details="user_not_found")

    next_basket = _resolve_basket_quick_move(user.basket, quick_move)
    if next_basket and next_basket != user.basket:
        user.basket = next_basket

    if not target_stage_id:
        await db.commit()
        return redirect_with_admin_users_msg("msg_status_ok")

    target_stage = await db.get(PlayoffStage, target_stage_id)
    if not target_stage:
        return redirect_with_admin_users_msg("msg_invalid_playoff_stage")

    if target_group_number is not None:
        allowed_group_numbers = set(range(1, max(1, math.ceil(int(target_stage.stage_size or 0) / 8)) + 1))
        if target_group_number not in allowed_group_numbers:
            return redirect_with_admin_users_msg("msg_operation_failed", details="invalid_target_group")

    existing_memberships = list((await db.scalars(select(PlayoffParticipant).where(PlayoffParticipant.user_id == user_id))).all())
    if len(existing_memberships) > 1:
        return redirect_with_admin_users_msg("msg_operation_failed", details="duplicate_membership")
    current_membership = existing_memberships[0] if existing_memberships else None

    try:
        if current_membership and current_membership.stage_id != target_stage_id:
            await move_user_to_stage(db, current_membership.stage_id, target_stage_id, user_id)
        elif not current_membership:
            group_member = await db.scalar(select(GroupMember).where(GroupMember.user_id == user_id).order_by(GroupMember.id))
            if group_member:
                await promote_group_member_to_stage(db, group_member.group_id, user_id, target_stage_id)
            elif replace_from_user_id:
                await replace_stage_player(db, target_stage_id, replace_from_user_id, user_id)
            else:
                stage_participants = list((await db.scalars(select(PlayoffParticipant).where(PlayoffParticipant.stage_id == target_stage_id))).all())
                if any(participant.user_id == user_id for participant in stage_participants):
                    raise ValueError("duplicate_membership")
                if len(stage_participants) >= int(target_stage.stage_size or 0):
                    raise ValueError("target_stage_is_full")
                next_seed = max((participant.seed for participant in stage_participants), default=0) + 1
                db.add(PlayoffParticipant(stage_id=target_stage_id, user_id=user_id, seed=next_seed))
                await db.commit()

        target_membership = await db.scalar(
            select(PlayoffParticipant).where(PlayoffParticipant.stage_id == target_stage_id, PlayoffParticipant.user_id == user_id)
        )
        if not target_membership:
            return redirect_with_admin_users_msg("msg_operation_failed", details="target_membership_not_found")

        if target_group_number is not None:
            target_membership.seed = await _find_group_seed_for_stage(
                db,
                stage_id=target_stage_id,
                group_number=target_group_number,
                stage_size=int(target_stage.stage_size or 0),
            )

        await db.commit()
        return redirect_with_admin_users_msg("msg_player_moved")
    except ValueError as exc:
        await db.rollback()
        details = str(exc) or "reassign_failed"
        return redirect_with_admin_users_msg("msg_operation_failed", details=details)
    except Exception:
        await db.rollback()
        logger.exception("Failed to reassign user from admin users page", extra={"user_id": user_id})
        return redirect_with_admin_users_msg("msg_operation_failed", details="reassign_failed")


async def _update_user_allowed_fields(
    db: AsyncSession,
    *,
    user_id: int,
    basket: str,
    direct_invite_stage: str | None,
    manual_points: int | None = None,
) -> RedirectResponse:
    user = await db.get(User, user_id)
    if not user:
        return redirect_with_admin_users_msg("msg_operation_failed")

    try:
        validated_data = _validate_user_update_payload(
            basket=basket,
            direct_invite_stage=direct_invite_stage,
        )
    except ValueError:
        return redirect_with_admin_users_msg("msg_operation_failed")

    for field_name, field_value in validated_data.items():
        if field_name not in ALLOWED_USER_UPDATE_FIELDS:
            continue
        setattr(user, field_name, field_value)

    if user.direct_invite_stage is None:
        user.direct_invite_group_number = None

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


async def _delete_user_with_dependencies(db: AsyncSession, *, user: User) -> None:
    """Удаляет пользователя и связанные записи явными запросами для надежности между СУБД."""
    user_id = user.id

    await db.execute(delete(GroupGameResult).where(GroupGameResult.user_id == user_id))
    await db.execute(delete(GroupManualTieBreak).where(GroupManualTieBreak.user_id == user_id))
    await db.execute(delete(GroupMember).where(GroupMember.user_id == user_id))
    await db.execute(delete(PlayoffParticipant).where(PlayoffParticipant.user_id == user_id))

    await db.execute(
        update(PlayoffMatch)
        .where(PlayoffMatch.winner_user_id == user_id)
        .values(winner_user_id=None)
    )
    await db.execute(
        update(PlayoffMatch)
        .where(PlayoffMatch.manual_winner_user_id == user_id)
        .values(manual_winner_user_id=None)
    )
    await db.execute(
        update(PlayoffStage)
        .where(PlayoffStage.final_candidate_user_id == user_id)
        .values(final_candidate_user_id=None)
    )

    await db.delete(user)


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
    crypto_wallets = (await db.scalars(select(CryptoWallet).order_by(CryptoWallet.sort_order, CryptoWallet.id))).all()
    donors = (await db.scalars(select(Donor).order_by(Donor.sort_order, Donor.id))).all()
    donate_highlight_amount_setting = await db.scalar(
        select(SiteSetting).where(SiteSetting.key == DONATE_HIGHLIGHT_AMOUNT_SETTING_KEY)
    )
    support_author_visible_setting = await db.scalar(
        select(SiteSetting).where(SiteSetting.key == DONATE_SUPPORT_AUTHOR_VISIBLE_SETTING_KEY)
    )
    donate_support_author_visible = True
    if support_author_visible_setting:
        donate_support_author_visible = (support_author_visible_setting.value or "").strip().lower() in {"1", "true", "yes", "on"}
    selected_lang = get_lang(request.query_params.get("content_lang") or request.cookies.get("lang"))
    content_by_lang = {
        "ru": dump_admin_content_for_lang("ru", rules_content).model_dump(),
        "en": dump_admin_content_for_lang("en", rules_content).model_dump(),
    }
    return templates.TemplateResponse(
        request,
        "admin_content.html",
        template_context(
            request,
            selected_content_lang=selected_lang,
            content_by_lang=content_by_lang,
            tiny_mce_api_key=settings.tiny_mce_api_key,
            donation_links=donation_links,
            crypto_wallets=crypto_wallets,
            sponsors=donors,
            donate_highlight_amount=(donate_highlight_amount_setting.value if donate_highlight_amount_setting else ""),
            donate_support_author_visible=donate_support_author_visible,
        ),
    )


@router.get("/admin/emergency", response_class=HTMLResponse)
async def admin_emergency_page(request: Request, db: AsyncSession = Depends(get_db)):
    return await _render_admin_emergency_page(request, db)


@router.post("/admin/user/update")
async def admin_update_user(
    user_id: int = Form(...),
    basket: str = Form(...),
    direct_invite_stage: str | None = Form(default=None),
    manual_points: int | None = Form(default=None),
    db: AsyncSession = Depends(get_db),
):
    # Атомарно обновляем разрешенные поля пользователя из админ-панели.
    user = await db.get(User, user_id)
    if not user:
        return redirect_with_admin_users_msg("msg_operation_failed")

    resolved_direct_invite_stage = user.direct_invite_stage if direct_invite_stage is None else direct_invite_stage
    return await _update_user_allowed_fields(
        db,
        user_id=user_id,
        basket=basket,
        direct_invite_stage=resolved_direct_invite_stage,
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
        basket=basket,
        direct_invite_stage=user.direct_invite_stage,
        manual_points=None,
    )


@router.post("/admin/user/delete")
async def admin_delete_user(
    user_id: int = Form(...),
    db: AsyncSession = Depends(get_db),
):
    user = await db.get(User, user_id)
    if not user:
        return redirect_with_admin_users_msg("msg_user_delete_not_found")

    try:
        await _delete_user_with_dependencies(db, user=user)
        await db.commit()
    except Exception:
        await db.rollback()
        logger.exception("Failed to delete user %s from admin panel", user_id)
        return redirect_with_admin_users_msg("msg_user_delete_failed")

    return redirect_with_admin_users_msg("msg_user_deleted")



@router.post("/admin/users/refresh-ranks")
async def admin_refresh_users_ranks(db: AsyncSession = Depends(get_db)):
    users = (
        await db.scalars(
            select(User)
            .where(User.steam_id.is_not(None), User.steam_id != "")
            .order_by(User.id.asc())
        )
    ).all()

    updated_count = 0
    failed_count = 0
    for index, user in enumerate(users):
        try:
            profile = await fetch_autochess_data(user.steam_id)
            user.current_rank = profile["current_rank"]
            user.highest_rank = profile["highest_rank"]
            updated_count += 1
        except Exception:
            failed_count += 1
            logger.exception("Failed to refresh ranks for user_id=%s steam_id=%s", user.id, user.steam_id)

        if index < len(users) - 1:
            await asyncio.sleep(1.5)

    await db.commit()
    return redirect_with_admin_users_msg(
        "msg_status_ok",
        details=f"ranks_refreshed:{updated_count};failed:{failed_count}",
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
    return redirect_with_admin_emergency_msg("msg_status_ok")




@router.post("/admin/technical-works")
async def admin_technical_works_toggle(
    technical_works_enabled: bool = Form(default=False),
    db: AsyncSession = Depends(get_db),
):
    row = await db.scalar(select(SiteSetting).where(SiteSetting.key == "technical_works_enabled"))
    if not row:
        row = SiteSetting(key="technical_works_enabled", value="0")
        db.add(row)
    row.value = "1" if technical_works_enabled else "0"
    await db.commit()
    return redirect_with_admin_emergency_msg("msg_status_ok")


@router.post("/admin/tournament/profile")
async def admin_set_tournament_profile(
    profile_key: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    tournament_started = await get_tournament_started(db)
    if tournament_started:
        return redirect_with_admin_msg("msg_operation_failed", details="tournament_already_started")

    normalized_profile_key = normalize_tournament_profile_key(profile_key)
    if normalized_profile_key != profile_key.strip():
        return redirect_with_admin_msg("msg_operation_failed", details="invalid_tournament_profile")

    groups_count = await db.scalar(
        select(func.count(TournamentGroup.id)).where(TournamentGroup.stage == "group_stage")
    )
    if groups_count:
        is_compatible, draw_issue = await validate_group_draw_integrity(db, profile_key=normalized_profile_key)
        if not is_compatible:
            return redirect_with_admin_msg("msg_operation_failed", details=f"profile_incompatible_draw:{draw_issue}")

    profile_row = await db.scalar(select(SiteSetting).where(SiteSetting.key == "tournament_profile"))
    if not profile_row:
        profile_row = SiteSetting(key="tournament_profile", value=normalized_profile_key)
        db.add(profile_row)
    profile_row.value = normalized_profile_key

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

    profile_key = await get_current_tournament_profile_key(db)
    is_draw_valid, draw_issue = await validate_group_draw_integrity(db, profile_key=profile_key)
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
    direct_invite_group: int | None = Form(default=None),
    db: AsyncSession = Depends(get_db),
):
    # Добавляем участника вручную в корзину invited.
    steam_id = await normalize_steam_id(steam_input)
    if not steam_id:
        return redirect_with_admin_emergency_msg("msg_invalid_steam_id")

    exists = await db.scalar(select(User).where(User.steam_id == steam_id))
    if exists:
        return redirect_with_admin_emergency_msg("msg_user_exists")

    profile = await fetch_autochess_data(steam_id)
    direct_invite_stage = "stage_2" if invite_type == "stage_2" else None
    direct_invite_group_number = None
    if direct_invite_stage:
        if direct_invite_group not in {1, 2, 3, 4}:
            return redirect_with_admin_emergency_msg("msg_operation_failed", details="invalid_direct_invite_group")
        profile_spec = await get_current_tournament_profile_spec(db)
        stage_1_promoted_count = int(profile_spec["stage_1_promoted_count"])
        stage_2_size = int(profile_spec["stage_2_size"])
        direct_invite_limit = max(0, stage_2_size - stage_1_promoted_count)
        direct_invite_count = await db.scalar(
            select(func.count(User.id)).where(User.direct_invite_stage == direct_invite_stage)
        )
        if (direct_invite_count or 0) >= direct_invite_limit:
            return redirect_with_admin_emergency_msg("msg_operation_failed", details=f"invite_limit:{direct_invite_limit}")
        direct_invite_group_number = direct_invite_group
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
        direct_invite_group_number=direct_invite_group_number,
        extra_data=json.dumps(profile["raw"], ensure_ascii=False),
    )
    db.add(user)
    await db.commit()
    return redirect_with_admin_emergency_msg("msg_invited_added")


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

    if not can_change_playoff_group_meta(stage, match):
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

    if not can_change_playoff_group_meta(stage, match):
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

    profile_key = await get_current_tournament_profile_key(db)
    is_valid, details = await validate_group_draw_integrity(db, profile_key=profile_key)
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

@router.post("/admin/emergency/rebuild-stage")
async def admin_emergency_rebuild_stage(
    request: Request,
    stage_id: int = Form(...),
    user_ids: str = Form(...),
    dry_run: bool = Form(default=False),
    confirm_final: bool = Form(default=False),
    db: AsyncSession = Depends(get_db),
):
    stage = await _get_playoff_stage(db, stage_id)
    if not stage:
        return redirect_with_admin_msg("msg_invalid_playoff_stage")
    allowed, reason = await _check_emergency_safety_lock(db, confirm_final=confirm_final)
    if not allowed:
        return redirect_with_admin_msg("msg_operation_failed", details=reason)

    try:
        ordered_user_ids = _parse_user_id_list(user_ids)
    except Exception:
        return redirect_with_admin_msg("msg_operation_failed", details="invalid_user_list")

    current = list((await db.scalars(select(PlayoffParticipant).where(PlayoffParticipant.stage_id == stage_id))).all())
    preview = {
        "stage_id": stage_id,
        "before_count": len(current),
        "after_count": len(ordered_user_ids),
        "added": [uid for uid in ordered_user_ids if uid not in {p.user_id for p in current}],
        "removed": [p.user_id for p in current if p.user_id not in set(ordered_user_ids)],
        "dry_run": dry_run,
    }

    if not dry_run:
        await db.execute(delete(PlayoffParticipant).where(PlayoffParticipant.stage_id == stage_id))
        for seed, user_id in enumerate(ordered_user_ids, start=1):
            db.add(PlayoffParticipant(stage_id=stage_id, user_id=user_id, seed=seed))
        stage.stage_size = len(ordered_user_ids)

    await _log_emergency_action(
        db,
        request=request,
        action_type="rebuild_stage",
        dry_run=dry_run,
        target_stage_id=stage_id,
        details=preview,
    )
    if dry_run:
        await db.flush()
        return await _render_admin_emergency_page(request, db, preview_title="Dry-run: rebuild stage", preview_payload=preview)
    await db.commit()
    return redirect_with_admin_msg("msg_status_ok", details="stage_rebuilt")


@router.post("/admin/emergency/stage-config")
async def admin_emergency_stage_config(
    request: Request,
    stage_id: int = Form(...),
    stage_size: int = Form(...),
    groups_count: int = Form(...),
    reseed: bool = Form(default=False),
    dry_run: bool = Form(default=False),
    confirm_final: bool = Form(default=False),
    db: AsyncSession = Depends(get_db),
):
    stage = await _get_playoff_stage(db, stage_id)
    if not stage:
        return redirect_with_admin_msg("msg_invalid_playoff_stage")
    allowed, reason = await _check_emergency_safety_lock(db, confirm_final=confirm_final)
    if not allowed:
        return redirect_with_admin_msg("msg_operation_failed", details=reason)

    participants = list((await db.scalars(select(PlayoffParticipant).where(PlayoffParticipant.stage_id == stage_id).order_by(PlayoffParticipant.seed))).all())
    matches = list((await db.scalars(select(PlayoffMatch).where(PlayoffMatch.stage_id == stage_id))).all())
    required_matches = max(1, groups_count)
    preview = {
        "stage_id": stage_id,
        "old_stage_size": stage.stage_size,
        "new_stage_size": stage_size,
        "old_matches": len(matches),
        "new_matches": required_matches,
        "reseed": reseed,
        "dry_run": dry_run,
    }

    if not dry_run:
        stage.stage_size = stage_size
        if reseed:
            for seed, participant in enumerate(participants, start=1):
                participant.seed = seed
        await db.execute(delete(PlayoffMatch).where(PlayoffMatch.stage_id == stage_id))
        for group_number in range(1, required_matches + 1):
            db.add(PlayoffMatch(stage_id=stage_id, match_number=group_number, group_number=group_number, game_number=1, lobby_password="0000", schedule_text="TBD"))

    await _log_emergency_action(db, request=request, action_type="stage_config", dry_run=dry_run, target_stage_id=stage_id, details=preview)
    if dry_run:
        await db.flush()
        return await _render_admin_emergency_page(request, db, preview_title="Dry-run: stage config", preview_payload=preview)
    await db.commit()
    return redirect_with_admin_msg("msg_status_ok", details="stage_config_updated")


@router.post("/admin/emergency/bulk-move")
async def admin_emergency_bulk_move(
    request: Request,
    from_stage_id: int = Form(...),
    to_stage_id: int = Form(...),
    user_ids: str = Form(...),
    dry_run: bool = Form(default=False),
    confirm_final: bool = Form(default=False),
    db: AsyncSession = Depends(get_db),
):
    if not await _playoff_stage_exists(db, from_stage_id) or not await _playoff_stage_exists(db, to_stage_id):
        return redirect_with_admin_msg("msg_invalid_playoff_stage")
    allowed, reason = await _check_emergency_safety_lock(db, confirm_final=confirm_final)
    if not allowed:
        return redirect_with_admin_msg("msg_operation_failed", details=reason)
    try:
        ordered_user_ids = _parse_user_id_list(user_ids)
    except Exception:
        return redirect_with_admin_msg("msg_operation_failed", details="invalid_user_list")

    moved: list[int] = []
    skipped: list[int] = []
    for user_id in ordered_user_ids:
        source = await db.scalar(select(PlayoffParticipant).where(PlayoffParticipant.stage_id == from_stage_id, PlayoffParticipant.user_id == user_id))
        target_exists = await db.scalar(select(PlayoffParticipant).where(PlayoffParticipant.stage_id == to_stage_id, PlayoffParticipant.user_id == user_id))
        if not source or target_exists:
            skipped.append(user_id)
            continue
        moved.append(user_id)
        if not dry_run:
            await db.delete(source)
            next_seed = (await db.scalar(select(func.max(PlayoffParticipant.seed)).where(PlayoffParticipant.stage_id == to_stage_id))) or 0
            db.add(PlayoffParticipant(stage_id=to_stage_id, user_id=user_id, seed=int(next_seed) + 1))

    preview = {"from_stage_id": from_stage_id, "to_stage_id": to_stage_id, "moved": moved, "skipped": skipped, "dry_run": dry_run}
    await _log_emergency_action(db, request=request, action_type="bulk_move", dry_run=dry_run, target_stage_id=to_stage_id, details=preview)
    if dry_run:
        await db.flush()
        return await _render_admin_emergency_page(request, db, preview_title="Dry-run: bulk move", preview_payload=preview)
    await db.commit()
    return redirect_with_admin_msg("msg_status_ok", details=f"bulk_moved:{len(moved)}")


@router.post("/admin/emergency/diagnostics")
async def admin_emergency_diagnostics(
    request: Request,
    dry_run: bool = Form(default=True),
    db: AsyncSession = Depends(get_db),
):
    stages = list((await db.scalars(select(PlayoffStage).order_by(PlayoffStage.stage_order, PlayoffStage.id))).all())
    diagnostics: list[dict[str, object]] = []
    for stage in stages:
        participants = list((await db.scalars(select(PlayoffParticipant).where(PlayoffParticipant.stage_id == stage.id))).all())
        matches = list((await db.scalars(select(PlayoffMatch).where(PlayoffMatch.stage_id == stage.id))).all())
        duplicate_users = sorted({p.user_id for p in participants if [x.user_id for x in participants].count(p.user_id) > 1})
        expected_groups = max(1, math.ceil(int(stage.stage_size or 0) / 8))
        group_numbers = {m.group_number for m in matches}
        missing_groups = [number for number in range(1, expected_groups + 1) if number not in group_numbers]
        if len(participants) != int(stage.stage_size or 0) or duplicate_users or missing_groups:
            diagnostics.append({
                "stage_id": stage.id,
                "stage_key": stage.key,
                "stage_size": stage.stage_size,
                "participants": len(participants),
                "missing_groups": missing_groups,
                "duplicate_users": duplicate_users,
            })

    payload = {"dry_run": dry_run, "issues": diagnostics}
    await _log_emergency_action(db, request=request, action_type="diagnostics", dry_run=dry_run, target_stage_id=None, details=payload)
    await db.flush()
    return await _render_admin_emergency_page(request, db, preview_title="Diagnostics", preview_payload=payload)


@router.post("/admin/playoff/move")
async def admin_move_playoff_player(
    from_stage_id: int = Form(...),
    to_stage_id: int = Form(...),
    user_id: int = Form(...),
    confirm_final: bool = Form(default=False),
    db: AsyncSession = Depends(get_db),
):
    allowed, reason = await _check_emergency_safety_lock(db, confirm_final=confirm_final)
    if not allowed:
        return redirect_with_admin_msg("msg_operation_failed", details=reason)
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
    confirm_final: bool = Form(default=False),
    db: AsyncSession = Depends(get_db),
):
    allowed, reason = await _check_emergency_safety_lock(db, confirm_final=confirm_final)
    if not allowed:
        return redirect_with_admin_msg("msg_operation_failed", details=reason)
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
    confirm_final: bool = Form(default=False),
    db: AsyncSession = Depends(get_db),
):
    allowed, reason = await _check_emergency_safety_lock(db, confirm_final=confirm_final)
    if not allowed:
        return redirect_with_admin_msg("msg_operation_failed", details=reason)
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
    submit_status = get_playoff_stage_submit_status(stage)
    if not submit_status["can_submit"] and not await can_submit_playoff_stage_results_with_db(db, stage):
        return redirect_with_admin_msg("msg_operation_failed", details=str(submit_status["reason"]))
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
    submit_status = get_playoff_stage_submit_status(stage)
    if not submit_status["can_submit"] and not await can_submit_playoff_stage_results_with_db(db, stage):
        return redirect_with_admin_msg("msg_operation_failed", details=str(submit_status["reason"]))

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
    submit_status = get_playoff_stage_submit_status(stage)
    if not submit_status["can_submit"] and not await can_submit_playoff_stage_results_with_db(db, stage):
        return redirect_with_admin_msg("msg_operation_failed", details=str(submit_status["reason"]))
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
    confirm_final: bool = Form(default=False),
    db: AsyncSession = Depends(get_db),
):
    allowed, reason = await _check_emergency_safety_lock(db, confirm_final=confirm_final)
    if not allowed:
        return redirect_with_admin_msg("msg_operation_failed", details=reason)
    stage = await _get_playoff_stage(db, stage_id)
    if not stage:
        return redirect_with_admin_msg("msg_invalid_playoff_stage")
    if not is_stage_allowed_for_manual_winner(stage):
        return redirect_with_admin_msg("msg_operation_failed", details="stage_not_final_by_policy")

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
        return redirect_with_admin_msg("msg_status_ok", details="winner_selected")
    except Exception:  # noqa: BLE001
        return redirect_with_admin_msg("msg_operation_failed")

@router.post("/admin/tournament/finish")
async def admin_finish_tournament(
    db: AsyncSession = Depends(get_db),
):
    started_stages = list(
        (
            await db.scalars(
                select(PlayoffStage)
                .where(PlayoffStage.is_started.is_(True))
                .order_by(PlayoffStage.stage_order.desc(), PlayoffStage.id.desc())
            )
        ).all()
    )
    final_stage = next((stage for stage in started_stages if is_stage_allowed_for_manual_winner(stage)), None)
    if not final_stage:
        return redirect_with_admin_msg("msg_operation_failed", details="stage_not_final_by_policy")

    final_match = await db.scalar(
        select(PlayoffMatch).where(
            PlayoffMatch.stage_id == final_stage.id,
            PlayoffMatch.group_number == 1,
        )
    )
    if not final_match or final_match.state != "finished":
        return redirect_with_admin_msg("msg_operation_failed", details="final_not_finished")

    winner_user_id = final_match.manual_winner_user_id or final_match.winner_user_id
    if not winner_user_id:
        return redirect_with_admin_msg("msg_operation_failed", details="winner_not_selected")

    winner_participant = await db.scalar(
        select(PlayoffParticipant).where(
            PlayoffParticipant.stage_id == final_stage.id,
            PlayoffParticipant.user_id == winner_user_id,
        )
    )
    if not winner_participant or (winner_participant.points or 0) < 22:
        return redirect_with_admin_msg("msg_operation_failed", details="winner_points_below_threshold")

    try:
        await snapshot_tournament_archive(
            db,
            winner_user_id=winner_user_id,
            title=final_stage.title,
            season=datetime.utcnow().strftime("%Y"),
            source_tournament_version="playoff_v2",
            is_public=True,
        )
        winner_nickname = await finalize_tournament_with_winner(db, winner_user_id)
        await reset_tournament_cycle_after_finish(db)
        await db.commit()
        return redirect_with_admin_msg("msg_status_ok", details=f"tournament_finished_and_archived:{winner_nickname}")
    except Exception:
        await db.rollback()
        return redirect_with_admin_msg("msg_operation_failed")


@router.post("/admin/donation-links")
async def admin_save_donation_links(
    items: str = Form(default=""),
    content_lang: str = Form(default="ru"),
    db: AsyncSession = Depends(get_db),
):
    lang = get_lang(content_lang)
    existing_rows = list((await db.scalars(select(DonationLink).order_by(DonationLink.sort_order, DonationLink.id))).all())
    rows = parse_visual_editor_rows(items)
    for idx, parts in enumerate(rows):
        if len(parts) < 2:
            continue
        row = existing_rows[idx] if idx < len(existing_rows) else DonationLink()
        row.sort_order = idx
        row.url = parts[1]
        row.category = "general"
        row.is_active = (parts[2] != "0") if len(parts) > 2 else True
        setattr(row, f"title_{lang}", parts[0])
        if idx >= len(existing_rows):
            db.add(row)

    for row in existing_rows[len(rows):]:
        await db.delete(row)

    await db.commit()
    return RedirectResponse(url=f"/admin/content?msg=msg_donation_links_saved&content_lang={lang}", status_code=303)


@router.post("/admin/sponsors")
async def admin_create_sponsor(
    name: str = Form(...),
    amount: int = Form(default=0),
    db: AsyncSession = Depends(get_db),
):
    max_sort_order = await db.scalar(select(func.max(Donor.sort_order)))
    db.add(Donor(name=(name or "").strip(), amount=max(0, amount), sort_order=(max_sort_order or -1) + 1))
    await db.commit()
    return RedirectResponse(url="/admin/content?msg=msg_donors_saved", status_code=303)


@router.post("/admin/sponsors/{sponsor_id}/update")
async def admin_update_sponsor(
    sponsor_id: int,
    name: str = Form(...),
    amount: int = Form(default=0),
    db: AsyncSession = Depends(get_db),
):
    sponsor = await db.get(Donor, sponsor_id)
    if not sponsor:
        return RedirectResponse(url="/admin/content?msg=msg_operation_failed", status_code=303)
    sponsor.name = (name or "").strip()
    sponsor.amount = max(0, amount)
    await db.commit()
    return RedirectResponse(url="/admin/content?msg=msg_donors_saved", status_code=303)


@router.post("/admin/sponsors/{sponsor_id}/delete")
async def admin_delete_sponsor(
    sponsor_id: int,
    db: AsyncSession = Depends(get_db),
):
    sponsor = await db.get(Donor, sponsor_id)
    if sponsor:
        await db.delete(sponsor)
        await db.commit()
    return RedirectResponse(url="/admin/content?msg=msg_donors_saved", status_code=303)


@router.post("/admin/donate-highlight-amount")
async def admin_update_donate_highlight_amount(
    amount: str = Form(default=""),
    db: AsyncSession = Depends(get_db),
):
    row = await db.scalar(select(SiteSetting).where(SiteSetting.key == DONATE_HIGHLIGHT_AMOUNT_SETTING_KEY))
    normalized_amount = (amount or "").strip()
    if not row:
        row = SiteSetting(key=DONATE_HIGHLIGHT_AMOUNT_SETTING_KEY, value=normalized_amount)
        db.add(row)
    else:
        row.value = normalized_amount
    await db.commit()
    return RedirectResponse(url="/admin/content?msg=msg_prize_pool_saved", status_code=303)


@router.post("/admin/donate-support-author-visibility")
async def admin_update_donate_support_author_visibility(
    visible: str = Form(default="0"),
    db: AsyncSession = Depends(get_db),
):
    is_visible = (visible or "").strip().lower() in {"1", "true", "yes", "on"}
    row = await db.scalar(select(SiteSetting).where(SiteSetting.key == DONATE_SUPPORT_AUTHOR_VISIBLE_SETTING_KEY))
    if not row:
        row = SiteSetting(key=DONATE_SUPPORT_AUTHOR_VISIBLE_SETTING_KEY, value="1" if is_visible else "0")
        db.add(row)
    else:
        row.value = "1" if is_visible else "0"
    await db.commit()
    return RedirectResponse(url="/admin/content?msg=msg_content_saved", status_code=303)


@router.post("/admin/crypto-wallets")
async def admin_create_crypto_wallet(
    wallet_name: str = Form(...),
    requisites: str = Form(default=""),
    is_active: bool = Form(default=False),
    db: AsyncSession = Depends(get_db),
):
    max_sort_order = await db.scalar(select(func.max(CryptoWallet.sort_order)))
    db.add(CryptoWallet(wallet_name=(wallet_name or "").strip(), requisites=(requisites or "").strip(), is_active=is_active, sort_order=(max_sort_order or -1) + 1))
    await db.commit()
    return RedirectResponse(url="/admin/content?msg=msg_donation_methods_saved", status_code=303)


@router.post("/admin/crypto-wallets/{wallet_id}/update")
async def admin_update_crypto_wallet(
    wallet_id: int,
    wallet_name: str = Form(...),
    requisites: str = Form(default=""),
    is_active: bool = Form(default=False),
    db: AsyncSession = Depends(get_db),
):
    wallet = await db.get(CryptoWallet, wallet_id)
    if not wallet:
        return RedirectResponse(url="/admin/content?msg=msg_operation_failed", status_code=303)
    wallet.wallet_name = (wallet_name or "").strip()
    wallet.requisites = (requisites or "").strip()
    wallet.is_active = is_active
    await db.commit()
    return RedirectResponse(url="/admin/content?msg=msg_donation_methods_saved", status_code=303)


@router.post("/admin/crypto-wallets/{wallet_id}/delete")
async def admin_delete_crypto_wallet(
    wallet_id: int,
    db: AsyncSession = Depends(get_db),
):
    wallet = await db.get(CryptoWallet, wallet_id)
    if wallet:
        await db.delete(wallet)
        await db.commit()
    return RedirectResponse(url="/admin/content?msg=msg_donation_methods_saved", status_code=303)


@router.post("/admin/donation-links/create")
async def admin_create_donation_link(
    label: str = Form(...),
    url: str = Form(default=""),
    is_active: bool = Form(default=False),
    content_lang: str = Form(default="ru"),
    category: str = Form(default="general"),
    db: AsyncSession = Depends(get_db),
):
    lang = get_lang(content_lang)
    max_sort_order = await db.scalar(select(func.max(DonationLink.sort_order)))
    normalized_category = category if category in {"general", "bank_cards", "support_author"} else "general"
    normalized_url = (url or "").strip()
    if normalized_category != "bank_cards" and not normalized_url:
        return RedirectResponse(url=f"/admin/content?msg=msg_operation_failed&content_lang={lang}", status_code=303)
    row = DonationLink(url=normalized_url, category=normalized_category, is_active=is_active, sort_order=(max_sort_order or -1) + 1)
    setattr(row, f"title_{lang}", (label or "").strip())
    db.add(row)
    await db.commit()
    return RedirectResponse(url=f"/admin/content?msg=msg_donation_links_saved&content_lang={lang}", status_code=303)


@router.post("/admin/donation-links/{link_id}/update")
async def admin_update_donation_link(
    link_id: int,
    label: str = Form(...),
    url: str = Form(default=""),
    is_active: bool = Form(default=False),
    content_lang: str = Form(default="ru"),
    category: str = Form(default="general"),
    db: AsyncSession = Depends(get_db),
):
    lang = get_lang(content_lang)
    row = await db.get(DonationLink, link_id)
    if not row:
        return RedirectResponse(url=f"/admin/content?msg=msg_operation_failed&content_lang={lang}", status_code=303)
    normalized_category = category if category in {"general", "bank_cards", "support_author"} else "general"
    normalized_url = (url or "").strip()
    if normalized_category != "bank_cards" and not normalized_url:
        return RedirectResponse(url=f"/admin/content?msg=msg_operation_failed&content_lang={lang}", status_code=303)
    row.url = normalized_url
    row.category = normalized_category
    row.is_active = is_active
    setattr(row, f"title_{lang}", (label or "").strip())
    await db.commit()
    return RedirectResponse(url=f"/admin/content?msg=msg_donation_links_saved&content_lang={lang}", status_code=303)


@router.post("/admin/donation-links/{link_id}/delete")
async def admin_delete_donation_link(
    link_id: int,
    content_lang: str = Form(default="ru"),
    category: str = Form(default="general"),
    db: AsyncSession = Depends(get_db),
):
    lang = get_lang(content_lang)
    row = await db.get(DonationLink, link_id)
    if row:
        await db.delete(row)
        await db.commit()
    return RedirectResponse(url=f"/admin/content?msg=msg_donation_links_saved&content_lang={lang}", status_code=303)


@router.post("/admin/rules")
async def admin_save_rules(
    body: str = Form(default=""),
    content_lang: str = Form(default="ru"),
    db: AsyncSession = Depends(get_db),
):
    lang = get_lang(content_lang)
    row = await get_or_create_rules_content(db)
    setattr(row, f"body_{lang}", body)
    await db.commit()
    return RedirectResponse(url=f"/admin/content?msg=msg_rules_saved&content_lang={lang}", status_code=303)


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
    return redirect_with_admin_emergency_msg("msg_status_ok")


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
    await chat_event_broker.publish()
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
