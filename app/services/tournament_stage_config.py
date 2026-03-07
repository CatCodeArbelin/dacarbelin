"""Единая конфигурация турнирных стадий и их ограничений."""

from dataclasses import dataclass
from collections.abc import Mapping

GROUP_STAGE_GAME_LIMIT = 3
FINAL_STAGE_SCORING_MODE = "final_22_top1"
DEFAULT_TOURNAMENT_PROFILE_KEY = "56"


TOURNAMENT_PROFILE_SPECS: Mapping[str, Mapping[str, object]] = {
    "56": {
        "key": "56",
        "title": "56 участников (7x8 → 21 → 32)",
        "stage_1_groups_count": 7,
        "stage_1_promoted_count": 21,
        "stage_2_size": 32,
    },
    "48": {
        "key": "48",
        "title": "48 участников (6x8 → 24 → 32)",
        "stage_1_groups_count": 6,
        "stage_1_promoted_count": 24,
        "stage_2_size": 32,
    },
}


TOURNAMENT_FLOW_SPEC: Mapping[str, Mapping[str, object]] = {
    "group_stage": {
        "order": 1,
        "participants": 56,
        "groups_count": 7,
        "group_size": 8,
        "game_limit": GROUP_STAGE_GAME_LIMIT,
        "promote_top_n": 3,
        "is_final": False,
        "can_submit": True,
        "group_label_mode": "letter",
        "display_label_key": "tournament_stage_group_stage_label",
        "column_title": "I этап",
        "admin_title": "I этап (56)",
        "scoring_mode": "standard",
    },
    "stage_2": {
        "order": 2,
        "participants": 32,
        "groups_count": 4,
        "group_size": 8,
        "game_limit": GROUP_STAGE_GAME_LIMIT,
        "promote_top_n": 4,
        "is_final": False,
        "can_submit": True,
        "group_label_mode": "letter",
        "display_label_key": "tournament_stage_1_4_label",
        "column_title": "II этап (32)",
        "admin_title": "Stage 2",
        "scoring_mode": "standard",
    },
    "stage_1_4": {
        "order": 3,
        "participants": 16,
        "groups_count": 2,
        "group_size": 8,
        "game_limit": GROUP_STAGE_GAME_LIMIT,
        "promote_top_n": 4,
        "is_final": False,
        "can_submit": True,
        "group_label_mode": "letter",
        "display_label_key": "tournament_stage_semifinal_groups_label",
        "column_title": "III этап — полуфинальные группы (16)",
        "admin_title": "Stage 3",
        "scoring_mode": "standard",
    },
    "stage_final": {
        "order": 4,
        "participants": 8,
        "groups_count": 1,
        "group_size": 8,
        "game_limit": None,
        "promote_top_n": 1,
        "is_final": True,
        "can_submit": True,
        "group_label_mode": "final",
        "display_label_key": "tournament_stage_final_label",
        "column_title": "Финал (8)",
        "admin_title": "Final",
        "scoring_mode": FINAL_STAGE_SCORING_MODE,
    },
}

LIMITED_PLAYOFF_STAGE_KEYS = {
    stage_key
    for stage_key, stage_spec in TOURNAMENT_FLOW_SPEC.items()
    if stage_key != "group_stage" and stage_spec.get("game_limit") is not None
}
LEGACY_STAGE_KEY_ALIASES: Mapping[str, str] = {
    "stage_1": "group_stage",
    "stage_1_8": "stage_2",
    "stage_3": "stage_1_4",
    "stage3": "stage_1_4",
    "final": "stage_final",
    "stage_4": "stage_final",
    "stage4": "stage_final",
    "stage_4_final": "stage_final",
    "final_stage": "stage_final",
}
FINAL_STAGE_SCORING_MODES = {str(TOURNAMENT_FLOW_SPEC["stage_final"]["scoring_mode"])}
PROMOTE_TOP_N_BY_STAGE: Mapping[str, int] = {
    stage_key: int(stage_spec.get("promote_top_n", 0))
    for stage_key, stage_spec in TOURNAMENT_FLOW_SPEC.items()
    if stage_key != "group_stage"
}


@dataclass(frozen=True)
class AdminPlayoffStageConfig:
    can_shuffle: bool = False
    can_debug_simulate: bool = False
    game_limit: int | None = None
    promote_top_n: int = 0
    is_final: bool = False


ADMIN_PLAYOFF_STAGE_TOGGLES: Mapping[str, Mapping[str, bool]] = {
    "stage_2": {"can_shuffle": True, "can_debug_simulate": True},
    "stage_1_4": {"can_debug_simulate": True},
}

ADMIN_PLAYOFF_STAGE_CONFIGS: Mapping[str, AdminPlayoffStageConfig] = {
    stage_key: AdminPlayoffStageConfig(
        can_shuffle=bool(ADMIN_PLAYOFF_STAGE_TOGGLES.get(stage_key, {}).get("can_shuffle", False)),
        can_debug_simulate=bool(ADMIN_PLAYOFF_STAGE_TOGGLES.get(stage_key, {}).get("can_debug_simulate", False)),
        game_limit=stage_spec.get("game_limit"),
        promote_top_n=int(stage_spec.get("promote_top_n", 0)),
        is_final=bool(stage_spec.get("is_final", False)),
    )
    for stage_key, stage_spec in TOURNAMENT_FLOW_SPEC.items()
    if stage_key != "group_stage"
}

DEFAULT_ADMIN_PLAYOFF_STAGE_CONFIG = AdminPlayoffStageConfig()


def is_limited_stage(stage_key: str) -> bool:
    return normalize_stage_key(stage_key) in LIMITED_PLAYOFF_STAGE_KEYS


def get_game_limit(stage_key: str) -> int | None:
    return get_admin_playoff_stage_config(stage_key).game_limit


def get_promote_top_n(stage_key: str) -> int:
    return get_admin_playoff_stage_config(stage_key).promote_top_n


def get_admin_playoff_stage_config(stage_key: str) -> AdminPlayoffStageConfig:
    return ADMIN_PLAYOFF_STAGE_CONFIGS.get(normalize_stage_key(stage_key), DEFAULT_ADMIN_PLAYOFF_STAGE_CONFIG)


def normalize_stage_key(stage_key: str) -> str:
    normalized_key = (stage_key or "").strip().lower()
    return LEGACY_STAGE_KEY_ALIASES.get(normalized_key, normalized_key)


def is_final_stage_key(stage_key: str) -> bool:
    normalized_stage_key = normalize_stage_key(stage_key)
    return bool(get_stage_spec(normalized_stage_key).get("is_final", False))


def get_stage_spec(stage_key: str) -> Mapping[str, object]:
    return TOURNAMENT_FLOW_SPEC.get(normalize_stage_key(stage_key), {})


def get_stage_group_count(stage_key: str) -> int | None:
    spec = get_stage_spec(stage_key)
    groups_count = spec.get("groups_count")
    return int(groups_count) if groups_count is not None else None


def get_stage_group_size(stage_key: str) -> int:
    group_size = get_stage_spec(stage_key).get("group_size", 8)
    return int(group_size)


def get_stage_display_label_key(stage_key: str) -> str | None:
    value = get_stage_spec(stage_key).get("display_label_key")
    return str(value) if value is not None else None


def get_stage_group_label(stage_key: str, group_number: int) -> str:
    group_label_mode = get_stage_spec(stage_key).get("group_label_mode")
    if group_label_mode == "letter":
        return chr(ord("A") + max(group_number - 1, 0))
    if group_label_mode == "final":
        return "Final"
    return str(group_number)



def can_submit_stage_results(
    stage_key: str,
    *,
    stage_size: int | None = None,
    scoring_mode: str | None = None,
) -> bool:
    stage_config = get_admin_playoff_stage_config(stage_key)
    if stage_config.game_limit is not None or stage_config.is_final:
        return bool(get_stage_spec(stage_key).get("can_submit", True))
    return is_final_stage(stage_key, stage_size=stage_size, scoring_mode=scoring_mode)

def is_final_stage(
    stage_key: str,
    *,
    stage_size: int | None = None,
    scoring_mode: str | None = None,
) -> bool:
    if is_final_stage_key(stage_key):
        return True
    normalized_key = normalize_stage_key(stage_key)
    if "final" in normalized_key:
        return True
    if (scoring_mode or "").strip().lower() in FINAL_STAGE_SCORING_MODES:
        return True
    try:
        return int(stage_size) == 8 if stage_size is not None else False
    except (TypeError, ValueError):
        return False


def normalize_tournament_profile_key(profile_key: str | None) -> str:
    key = (profile_key or "").strip()
    if key in TOURNAMENT_PROFILE_SPECS:
        return key
    return DEFAULT_TOURNAMENT_PROFILE_KEY


def get_tournament_profile_spec(profile_key: str | None = None) -> Mapping[str, object]:
    normalized_key = normalize_tournament_profile_key(profile_key)
    return TOURNAMENT_PROFILE_SPECS[normalized_key]
