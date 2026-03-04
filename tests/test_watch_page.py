from fastapi.testclient import TestClient

from app.main import app


def test_watch_page_renders_twitch_embed_with_parent() -> None:
    with TestClient(app) as client:
        response = client.get("/watch", headers={"host": "dac.example.com"})

    assert response.status_code == 200
    assert "player.twitch.tv" in response.text
    assert "channel=loyrensss" in response.text
    assert "parent=dac.example.com" in response.text
