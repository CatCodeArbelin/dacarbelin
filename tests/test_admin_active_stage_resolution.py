from app.models.tournament import PlayoffStage
from app.routers import web


def test_resolve_admin_active_stage_keeps_group_stage_until_ready() -> None:
    playoff_stages = [
        PlayoffStage(id=1, key="stage_2", title="Stage 2", stage_size=16, stage_order=1, is_started=True),
    ]

    active_stage_key = web.resolve_admin_active_stage_key(
        tournament_started=True,
        group_stage_finish_ready=False,
        playoff_stages=playoff_stages,
        stage_progression_keys=web.PLAYOFF_STAGE_KEYS_ORDER,
    )

    assert active_stage_key == "group_stage"


def test_resolve_admin_active_stage_uses_playoff_after_group_completion() -> None:
    playoff_stages = [
        PlayoffStage(id=1, key="stage_2", title="Stage 2", stage_size=16, stage_order=1, is_started=True),
    ]

    active_stage_key = web.resolve_admin_active_stage_key(
        tournament_started=True,
        group_stage_finish_ready=True,
        playoff_stages=playoff_stages,
        stage_progression_keys=web.PLAYOFF_STAGE_KEYS_ORDER,
    )

    assert active_stage_key == "stage_2"


def test_resolve_admin_active_stage_returns_none_when_tournament_not_started() -> None:
    active_stage_key = web.resolve_admin_active_stage_key(
        tournament_started=False,
        group_stage_finish_ready=False,
        playoff_stages=[],
        stage_progression_keys=web.PLAYOFF_STAGE_KEYS_ORDER,
    )

    assert active_stage_key is None
