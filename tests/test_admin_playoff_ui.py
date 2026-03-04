"""Проверяет UI-поведение admin-шаблона для управления этапами playoff."""

from pathlib import Path


def test_admin_template_has_playoff_hint_without_manual_stage_controls() -> None:
    template = Path("app/templates/admin.html").read_text(encoding="utf-8")
    macros = Path("app/templates/includes/tournament_stage_macros.html").read_text(encoding="utf-8")

    assert "has_playoff_stages = playoff_stages|length > 0" in template
    assert "admin_playoff_stages_empty_hint_title" in template
    assert "admin_playoff_stages_empty_hint_steps" in template
    assert "stage_macros.stage_group_controls" in template
    assert "/admin/playoff/stage/finish" in template
    assert "playoff_stage_finish_ready" in template
    assert "/admin/playoff/results/batch" in template
    assert "admin_playoff_match_results" in template
    assert "current_playoff_stage_config.can_shuffle" in template
    assert "current_playoff_stage_config.can_debug_simulate" in template
    assert "current_playoff_stage_is_final" in template
    assert "current_playoff_stage.key == 'stage_2'" in template
    assert "Подтвердить победителя этапа" in template
    assert 'name="winner_user_id"' in template
    assert "/admin/playoff/override" in template
    assert "Выберите победителя из 8 участников текущего финала." in template
    assert "Победителем можно назначить только игрока с 22+ очками." in template
    assert "final_group.participants" in template
    assert "stage_macros.stage_finish_panel" in template
    assert "playoff_empty_active_stage_alert" in template
    assert "visual-draw-move" in template
    assert "Переместить выше" in template
    assert "Переместить ниже" in template
    assert "/admin/group-stage/finish" in template
    assert "group_stage_game_limit" in template
    assert "stage_finish_panel" in macros
    assert "stage_group_controls" in macros
    assert "highlight_winner_eligible" in macros
    assert "/admin/playoff/start" not in template
    assert "/admin/playoff/promote" not in template
    assert "/admin/group/create" not in template
    assert "/admin/group/member/add" not in template
    assert "/admin/group/member/remove" not in template
    assert "/admin/group/member/move" not in template
    assert "/admin/group/member/swap" not in template


def test_admin_users_template_has_group_sections() -> None:
    template = Path("app/templates/admin_users.html").read_text(encoding="utf-8")

    assert "{% for section in group_sections %}" in template
    assert "{% for user in section.users %}" in template
    assert "Группы отображаются, потому что жеребьевка применена и турнир запущен." in template


def test_tournament_template_has_empty_active_stage_alert() -> None:
    template = Path("app/templates/tournament.html").read_text(encoding="utf-8")

    assert "playoff_empty_active_stage_alert" in template


def test_admin_template_disables_stage_result_submit_for_disallowed_stage() -> None:
    template = Path("app/templates/admin.html").read_text(encoding="utf-8")
    macros = Path("app/templates/includes/tournament_stage_macros.html").read_text(encoding="utf-8")
    router = Path("app/routers/web.py").read_text(encoding="utf-8")

    assert "current_playoff_stage_can_submit_results" in router
    assert "can_submit_playoff_stage_results" in router
    assert "can_submit_results=current_playoff_stage_can_submit_results" in template
    assert "submit_results_disabled_reason='Запись результатов для этой стадии запрещена" in template
    assert "can_submit_results=True" in macros
    assert "group_locked or not can_submit_results" in macros
    assert "Запись результатов для этой стадии запрещена" in macros
