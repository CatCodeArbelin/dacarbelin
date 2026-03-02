from app.services.tournament import ManualDrawValidationError, _normalize_manual_layout_payload


def test_normalize_manual_layout_payload_keeps_explicit_order() -> None:
    payload = {
        "group_order": [2, 0, 1],
        "groups": [
            {"group_label": "Group A", "group_index": 0, "members": ["11"]},
            {"group_label": "Group B", "group_index": 1, "members": ["12"]},
            {"group_label": "Group C", "group_index": 2, "members": ["13"]},
        ],
    }

    assert _normalize_manual_layout_payload(payload) == [["13"], ["11"], ["12"]]


def test_normalize_manual_layout_payload_rejects_missing_groups() -> None:
    try:
        _normalize_manual_layout_payload({"group_order": [0], "groups": []})
    except ManualDrawValidationError as exc:
        assert exc.details == "invalid_layout"
    else:
        raise AssertionError("Expected ManualDrawValidationError")
