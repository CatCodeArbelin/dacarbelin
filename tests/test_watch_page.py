from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app


def test_watch_page_renders_twitch_embed_from_config() -> None:
    original_channel = settings.twitch_channel
    original_domains = settings.twitch_parent_domains
    original_mode = settings.twitch_embed_mode

    settings.twitch_channel = "mychannel"
    settings.twitch_parent_domains = "Example.com,www.Example.com:443"
    settings.twitch_embed_mode = "iframe"

    try:
        with TestClient(app) as client:
            response = client.get("/watch", headers={"host": "dac.example.com"})
    finally:
        settings.twitch_channel = original_channel
        settings.twitch_parent_domains = original_domains
        settings.twitch_embed_mode = original_mode

    assert response.status_code == 200
    assert "player.twitch.tv" in response.text
    assert "channel=mychannel" in response.text
    assert "parent=dac.example.com" in response.text
    assert "parent=example.com" in response.text
    assert "parent=www.example.com" in response.text


def test_watch_page_renders_interactive_embed_when_enabled() -> None:
    original_mode = settings.twitch_embed_mode
    original_domains = settings.twitch_parent_domains
    original_channel = settings.twitch_channel

    settings.twitch_embed_mode = "interactive"
    settings.twitch_parent_domains = "example.com"
    settings.twitch_channel = "anotherchannel"

    try:
        with TestClient(app) as client:
            response = client.get("/watch", headers={"host": "embed.localhost"})
    finally:
        settings.twitch_embed_mode = original_mode
        settings.twitch_parent_domains = original_domains
        settings.twitch_channel = original_channel

    assert response.status_code == 200
    assert "player.twitch.tv" in response.text
    assert "embed/v1.js" in response.text
    assert 'channel: "anotherchannel"' in response.text
    assert 'parent: ["embed.localhost", "example.com"]' in response.text


def test_watch_page_uses_x_forwarded_host_for_parent() -> None:
    original_domains = settings.twitch_parent_domains

    settings.twitch_parent_domains = "example.com"

    try:
        with TestClient(app) as client:
            response = client.get("/watch", headers={"x-forwarded-host": "Proxy.Example.com:8443", "host": "ignored.local"})
    finally:
        settings.twitch_parent_domains = original_domains

    assert response.status_code == 200
    assert "parent=proxy.example.com" in response.text
    assert "parent=example.com" in response.text


def test_watch_page_strips_scheme_from_configured_parents() -> None:
    original_domains = settings.twitch_parent_domains

    settings.twitch_parent_domains = "https://Example.com:443/path,http://sub.example.com"

    try:
        with TestClient(app) as client:
            response = client.get("/watch", headers={"host": "dac.example.com"})
    finally:
        settings.twitch_parent_domains = original_domains

    assert response.status_code == 200
    assert "parent=example.com" in response.text
    assert "parent=sub.example.com" in response.text
