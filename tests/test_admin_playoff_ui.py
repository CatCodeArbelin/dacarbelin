"""Проверяет UI-поведение admin-шаблона для управления этапами playoff."""

from pathlib import Path


def test_admin_template_has_playoff_hint_without_manual_stage_controls() -> None:
    template = Path("app/templates/admin.html").read_text(encoding="utf-8")

    assert "has_playoff_stages = playoff_stages|length > 0" in template
    assert "admin_playoff_stages_empty_hint_title" in template
    assert "admin_playoff_stages_empty_hint_steps" in template
    assert "Закончить этап, определить победителей по очкам" in template
    assert "/admin/playoff/group/finish" in template
    assert "is_limited_playoff_stage = current_playoff_stage.key in ['stage_2', 'stage_1_8', 'stage_1_4']" in template
    assert "is_final_playoff_stage = current_playoff_stage.key == 'stage_final'" in template
    assert "Управление финалом (22+ и подтверждение победителя)" in template
    assert "Подтвердить победителя финала" in template
    assert "Кандидат на победу" in template
    assert "/admin/playoff/override" in template
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
