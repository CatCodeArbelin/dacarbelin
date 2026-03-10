from fastapi.testclient import TestClient

from app.db.session import get_db
from app.main import app
import app.main as main_module
from app.models.settings import CryptoWallet, DonationLink, Donor, SiteSetting


class _FakeScalarResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeDonateDB:
    def __init__(self):
        self.donation_links = [DonationLink(title_ru="Link", title_en="Link", url="https://example.com", is_active=True)]
        self.crypto_wallets = [CryptoWallet(wallet_name="USDT", requisites="TXX", is_active=True)]
        self.donors = [Donor(name="Alice", amount=7900, message_ru="", message_en="")]
        self.site_settings = []

    async def scalars(self, statement):
        query = str(statement)
        if "donation_links" in query:
            return _FakeScalarResult(self.donation_links)
        if "crypto_wallets" in query:
            return _FakeScalarResult(self.crypto_wallets)
        return _FakeScalarResult(self.donors)

    async def scalar(self, statement):
        query = str(statement)
        if "site_settings.key" in query:
            for row in self.site_settings:
                if row.key == "donate_support_author_visible":
                    return row
        return None



def test_donate_page_shows_rub_for_ru_locale_and_usd_for_en_locale(monkeypatch):
    fake_db = _FakeDonateDB()

    async def fake_enabled() -> bool:
        return False

    monkeypatch.setattr(main_module, "is_technical_works_enabled", fake_enabled)


    async def override_get_db():
        yield fake_db

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as client:
            client.cookies.set("lang", "ru")
            ru_response = client.get("/donate")
            client.cookies.set("lang", "en")
            en_response = client.get("/donate")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert ru_response.status_code == 200
    assert "7900 ₽" in ru_response.text
    assert "$100" not in ru_response.text

    assert en_response.status_code == 200
    assert "$100" in en_response.text
    assert "7900 ₽" not in en_response.text


def test_donate_page_support_author_visibility_toggle(monkeypatch):
    fake_db = _FakeDonateDB()

    async def fake_enabled() -> bool:
        return False

    monkeypatch.setattr(main_module, "is_technical_works_enabled", fake_enabled)

    async def override_get_db():
        yield fake_db

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as client:
            client.cookies.set("lang", "en")
            response_default = client.get("/donate")

            fake_db.site_settings = [SiteSetting(key="donate_support_author_visible", value="0")]
            response_hidden = client.get("/donate")

            fake_db.site_settings = [SiteSetting(key="donate_support_author_visible", value="1")]
            response_visible = client.get("/donate")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response_default.status_code == 200
    assert "Support the site author" in response_default.text

    assert response_hidden.status_code == 200
    assert "Support the site author" not in response_hidden.text

    assert response_visible.status_code == 200
    assert "Support the site author" in response_visible.text


def test_donate_page_shows_usd_for_zh_locale(monkeypatch):
    fake_db = _FakeDonateDB()

    async def fake_enabled() -> bool:
        return False

    monkeypatch.setattr(main_module, "is_technical_works_enabled", fake_enabled)

    async def override_get_db():
        yield fake_db

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as client:
            client.cookies.set("lang", "zh")
            response = client.get("/donate")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 200
    assert "$100" in response.text
    assert "7900 ₽" not in response.text
