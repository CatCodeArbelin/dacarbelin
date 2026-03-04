"""Единая конфигурация турнирных стадий и их ограничений."""

from dataclasses import dataclass
from collections.abc import Mapping

LIMITED_PLAYOFF_STAGE_KEYS = {"stage_2", "stage_1_4"}
GROUP_STAGE_GAME_LIMIT = 3
LEGACY_STAGE_KEY_ALIASES: Mapping[str, str] = {
    "final": "stage_final",
    "stage_4": "stage_final",
    "stage4": "stage_final",
    "stage_4_final": "stage_final",
    "final_stage": "stage_final",
}
FINAL_STAGE_SCORING_MODES = {"final_22_top1"}
PROMOTE_TOP_N_BY_STAGE: Mapping[str, int] = {
    "stage_2": 4,
    "stage_1_4": 4,
    "stage_final": 1,
}


@dataclass(frozen=True)
class AdminPlayoffStageConfig:
    can_shuffle: bool = False
    can_debug_simulate: bool = False
    game_limit: int | None = None
    promote_top_n: int = 0
    is_final: bool = False


ADMIN_PLAYOFF_STAGE_CONFIGS: Mapping[str, AdminPlayoffStageConfig] = {
    "stage_2": AdminPlayoffStageConfig(
        can_shuffle=True,
        can_debug_simulate=True,
        game_limit=GROUP_STAGE_GAME_LIMIT,
        promote_top_n=4,
    ),
    "stage_1_4": AdminPlayoffStageConfig(
        can_debug_simulate=True,
        game_limit=GROUP_STAGE_GAME_LIMIT,
        promote_top_n=4,
    ),
    "stage_final": AdminPlayoffStageConfig(
        promote_top_n=1,
        is_final=True,
    ),
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
    return normalize_stage_key(stage_key) == "stage_final"


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
