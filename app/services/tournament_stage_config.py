"""Единая конфигурация турнирных стадий и их ограничений."""

from collections.abc import Mapping

LIMITED_PLAYOFF_STAGE_KEYS = {"stage_2", "stage_1_8", "stage_1_4"}
GROUP_STAGE_GAME_LIMIT = 3
PROMOTE_TOP_N_BY_STAGE: Mapping[str, int] = {
    "stage_2": 4,
    "stage_1_8": 2,
    "stage_1_4": 4,
    "stage_final": 1,
}


def is_limited_stage(stage_key: str) -> bool:
    return stage_key in LIMITED_PLAYOFF_STAGE_KEYS


def get_game_limit(stage_key: str) -> int | None:
    if is_limited_stage(stage_key):
        return GROUP_STAGE_GAME_LIMIT
    return None


def get_promote_top_n(stage_key: str) -> int:
    return PROMOTE_TOP_N_BY_STAGE.get(stage_key, 0)
