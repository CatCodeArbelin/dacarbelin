"""Единая конфигурация турнирных стадий и их ограничений."""

from dataclasses import dataclass
from collections.abc import Mapping

LIMITED_PLAYOFF_STAGE_KEYS = {"stage_2", "stage_1_4"}
GROUP_STAGE_GAME_LIMIT = 3
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
    return stage_key in LIMITED_PLAYOFF_STAGE_KEYS


def get_game_limit(stage_key: str) -> int | None:
    return get_admin_playoff_stage_config(stage_key).game_limit


def get_promote_top_n(stage_key: str) -> int:
    return get_admin_playoff_stage_config(stage_key).promote_top_n


def get_admin_playoff_stage_config(stage_key: str) -> AdminPlayoffStageConfig:
    return ADMIN_PLAYOFF_STAGE_CONFIGS.get(stage_key, DEFAULT_ADMIN_PLAYOFF_STAGE_CONFIG)
