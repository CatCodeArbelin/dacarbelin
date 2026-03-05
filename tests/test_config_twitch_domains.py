from app.core.config import parse_twitch_parent_domains_csv


def test_parse_twitch_parent_domains_csv_normalizes_csv_values() -> None:
    result = parse_twitch_parent_domains_csv(" Example.com:443,https://WWW.EXAMPLE.com/path,,http://sub.example.com ")

    assert result == ["example.com", "www.example.com", "sub.example.com"]
