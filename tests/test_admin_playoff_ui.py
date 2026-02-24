"""Проверяет UI-поведение admin-шаблона для управления этапами playoff."""

from pathlib import Path


def test_admin_template_has_empty_playoff_hint_and_disabled_controls() -> None:
    template = Path("app/templates/admin.html").read_text(encoding="utf-8")

    assert "has_playoff_stages = playoff_stages|length > 0" in template
    assert "admin_playoff_stages_empty_hint_title" in template
    assert "admin_playoff_stages_empty_hint_steps" in template
    assert "{% if not has_playoff_stages %}disabled{% endif %}" in template


def test_admin_template_has_stage_placeholder_option() -> None:
    template = Path("app/templates/admin.html").read_text(encoding="utf-8")

    assert "{{ tr('admin_select_stage') }}" in template
    assert '<option value="" selected disabled>' in template


def test_admin_users_template_has_group_sections() -> None:
    template = Path("app/templates/admin_users.html").read_text(encoding="utf-8")

    assert "{% for section in group_sections %}" in template
    assert "{% for user in section.users %}" in template
    assert "Группы отображаются, потому что жеребьевка применена и турнир запущен." in template
