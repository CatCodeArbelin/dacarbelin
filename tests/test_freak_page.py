from fastapi.testclient import TestClient

from app.main import app


def test_freak_page_contains_fullscreen_image_and_music() -> None:
    with TestClient(app) as client:
        response = client.get('/freak')

    assert response.status_code == 200
    assert '/static/OLEGFREAK.png' in response.text
    assert '/static/Shaman King.mp3' in response.text
    assert 'autoplay' in response.text
    assert 'loop' in response.text