from datetime import datetime

from app.routers.web import format_msk_datetime, to_msk_datetime


def test_to_msk_datetime_adds_three_hours_for_naive_utc_value() -> None:
    source = datetime(2026, 1, 1, 8, 34, 0)

    converted = to_msk_datetime(source)

    assert converted is not None
    assert converted.hour == 11
    assert converted.minute == 34


def test_format_msk_datetime_renders_expected_string() -> None:
    source = datetime(2026, 1, 1, 8, 34, 0)

    assert format_msk_datetime(source) == "01.01.26 11:34:00"
