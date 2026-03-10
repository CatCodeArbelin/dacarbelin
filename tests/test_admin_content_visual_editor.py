from fastapi.testclient import TestClient

from app.core.admin_session import ADMIN_SESSION_COOKIE, create_admin_session_cookie
from app.db.session import get_db
from app.main import app
import app.main as main_module
from app.models.settings import CryptoWallet, DonationLink, Donor, PrizePoolEntry, RulesContent, SiteSetting


class _FakeScalarResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeContentDB:
    def __init__(self):
        self.donation_links = []
        self.crypto_wallets = []
        self.prize_pool_entries = []
        self.donors = []
        self.site_settings = []
        self.rules_content = []

    async def scalars(self, statement):
        query = str(statement)
        if "donation_links" in query:
            return _FakeScalarResult(self.donation_links)
        if "crypto_wallets" in query:
            return _FakeScalarResult(self.crypto_wallets)
        if "prize_pool_entries" in query:
            return _FakeScalarResult(self.prize_pool_entries)
        if "max(" in query and "donors" in query:
            class _MaxResult:
                def __iter__(self):
                    return iter([])
            return _FakeScalarResult([])
        return _FakeScalarResult(self.donors)

    async def scalar(self, statement):
        query = str(statement)
        if "max(donation_links.sort_order)" in query:
            return max([item.sort_order for item in self.donation_links], default=None)
        if "max(crypto_wallets.sort_order)" in query:
            return max([item.sort_order for item in self.crypto_wallets], default=None)
        if "max(donors.sort_order)" in query:
            return max([item.sort_order for item in self.donors], default=None)
        if "FROM rules_content" in query:
            return self.rules_content[0] if self.rules_content else None
        if "site_settings.key" in query:
            if "donate_highlight_amount" in query:
                key = "donate_highlight_amount"
            elif "donate_support_author_visible" in query:
                key = "donate_support_author_visible"
            else:
                key = "donate_support_author_visible"
            for row in self.site_settings:
                if row.key == key:
                    return row
        return None

    async def get(self, model, row_id):
        collection_map = {
            DonationLink: self.donation_links,
            CryptoWallet: self.crypto_wallets,
            Donor: self.donors,
            SiteSetting: self.site_settings,
            RulesContent: self.rules_content,
        }
        for row in collection_map.get(model, []):
            if row.id == row_id:
                return row
        return None

    def add(self, row):
        if isinstance(row, DonationLink):
            row.id = len(self.donation_links) + 1
            self.donation_links.append(row)
        elif isinstance(row, CryptoWallet):
            row.id = len(self.crypto_wallets) + 1
            self.crypto_wallets.append(row)
        elif isinstance(row, PrizePoolEntry):
            row.id = len(self.prize_pool_entries) + 1
            self.prize_pool_entries.append(row)
        elif isinstance(row, Donor):
            row.id = len(self.donors) + 1
            self.donors.append(row)
        elif isinstance(row, SiteSetting):
            row.id = len(self.site_settings) + 1
            self.site_settings.append(row)
        elif isinstance(row, RulesContent):
            row.id = 1
            self.rules_content = [row]

    async def delete(self, row):
        for collection in (self.donation_links, self.crypto_wallets, self.prize_pool_entries, self.donors, self.site_settings, self.rules_content):
            if row in collection:
                collection.remove(row)

    async def flush(self):
        return None

    async def commit(self):
        return None


HTML_TABLE = "<table><tbody><tr><td>A</td><td>B</td><td>1</td></tr></tbody></table>"


def test_admin_content_endpoints_accept_html_payloads():
    fake_db = _FakeContentDB()

    async def override_get_db():
        yield fake_db

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as client:
            client.cookies.set(ADMIN_SESSION_COOKIE, create_admin_session_cookie())
            assert client.post("/admin/donation-links", data={"items": HTML_TABLE, "content_lang": "ru"}, follow_redirects=False).status_code == 303
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert fake_db.donation_links[0].title_ru == "A"


def test_admin_content_structured_crud_forms():
    fake_db = _FakeContentDB()

    async def override_get_db():
        yield fake_db

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as client:
            client.cookies.set(ADMIN_SESSION_COOKIE, create_admin_session_cookie())

            assert client.post(
                "/admin/donation-links/create",
                data={"label": "Boosty", "url": "https://example.com", "is_active": "true", "content_lang": "ru"},
                follow_redirects=False,
            ).status_code == 303
            assert client.post(
                "/admin/donation-links/1/update",
                data={"label": "Boosty RU", "url": "https://example.com/ru", "content_lang": "ru"},
                follow_redirects=False,
            ).status_code == 303

            assert client.post(
                "/admin/crypto-wallets",
                data={"wallet_name": "USDT TRC20", "requisites": "TXX123", "is_active": "true"},
                follow_redirects=False,
            ).status_code == 303
            assert client.post(
                "/admin/crypto-wallets/1/update",
                data={"wallet_name": "BTC", "requisites": "bc1abc", "is_active": "true"},
                follow_redirects=False,
            ).status_code == 303

            assert client.post("/admin/sponsors", data={"name": "Alice", "amount": "100"}, follow_redirects=False).status_code == 303
            assert client.post("/admin/sponsors/1/update", data={"name": "Alice Corp", "amount": "200"}, follow_redirects=False).status_code == 303

            assert client.post("/admin/sponsors/1/delete", follow_redirects=False).status_code == 303
            assert client.post("/admin/crypto-wallets/1/delete", follow_redirects=False).status_code == 303
            assert client.post("/admin/donation-links/1/delete", data={"content_lang": "ru"}, follow_redirects=False).status_code == 303
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert fake_db.donation_links == []
    assert fake_db.crypto_wallets == []
    assert fake_db.donors == []


def test_donate_page_renders_sanitized_html_content(monkeypatch):
    fake_db = _FakeContentDB()

    async def fake_enabled() -> bool:
        return False

    monkeypatch.setattr(main_module, "is_technical_works_enabled", fake_enabled)
    fake_db.donation_links = [DonationLink(title_ru="<strong>Link</strong>", title_en="", url="https://example.com", is_active=True)]
    fake_db.crypto_wallets = [CryptoWallet(wallet_name="<em>Card</em>", requisites="<script>x</script>OK", is_active=True)]
    fake_db.prize_pool_entries = [PrizePoolEntry(place_label_ru="<b>1st</b>", reward_ru="<i>Gold</i>")]
    fake_db.donors = [Donor(name="Neo", amount=1, message_ru="<u>Hi</u>")]

    async def override_get_db():
        yield fake_db

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as client:
            response = client.get("/donate")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 200
    assert "<strong>Link</strong>" in response.text
    assert "<script>" not in response.text
    assert "<u>Hi</u>" in response.text


def test_admin_can_toggle_donate_support_author_visibility():
    fake_db = _FakeContentDB()

    async def override_get_db():
        yield fake_db

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as client:
            client.cookies.set(ADMIN_SESSION_COOKIE, create_admin_session_cookie())

            response_off = client.post(
                "/admin/donate-support-author-visibility",
                data={"visible": "0"},
                follow_redirects=False,
            )
            response_on = client.post(
                "/admin/donate-support-author-visibility",
                data={"visible": "1"},
                follow_redirects=False,
            )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response_off.status_code == 303
    assert response_on.status_code == 303
    assert len(fake_db.site_settings) == 1
    assert fake_db.site_settings[0].key == "donate_support_author_visible"
    assert fake_db.site_settings[0].value == "1"


def test_admin_content_page_has_ch_language_option_and_rules_can_be_saved():
    fake_db = _FakeContentDB()

    async def override_get_db():
        yield fake_db

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as client:
            client.cookies.set(ADMIN_SESSION_COOKIE, create_admin_session_cookie())

            page = client.get("/admin/content?content_lang=zh")
            response = client.post(
                "/admin/rules",
                data={"content_lang": "zh", "body": "<p>中文规则</p>"},
                follow_redirects=False,
            )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert page.status_code == 200
    assert 'option value="zh"' in page.text
    assert '>CH<' in page.text
    assert response.status_code == 303
    assert fake_db.rules_content
    assert fake_db.rules_content[0].body_zh == "<p>中文规则</p>"
