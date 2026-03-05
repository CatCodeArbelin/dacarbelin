from fastapi.testclient import TestClient

from app.core.admin_session import ADMIN_SESSION_COOKIE, create_admin_session_cookie
from app.db.session import get_db
from app.main import app
from app.models.settings import DonationLink, DonationMethod, Donor, PrizePoolEntry


class _FakeScalarResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeContentDB:
    def __init__(self):
        self.donation_links = []
        self.donation_methods = []
        self.prize_pool_entries = []
        self.donors = []

    async def scalars(self, statement):
        query = str(statement)
        if "donation_links" in query:
            return _FakeScalarResult(self.donation_links)
        if "donation_methods" in query:
            return _FakeScalarResult(self.donation_methods)
        if "prize_pool_entries" in query:
            return _FakeScalarResult(self.prize_pool_entries)
        return _FakeScalarResult(self.donors)

    def add(self, row):
        if isinstance(row, DonationLink):
            self.donation_links.append(row)
        elif isinstance(row, DonationMethod):
            self.donation_methods.append(row)
        elif isinstance(row, PrizePoolEntry):
            self.prize_pool_entries.append(row)
        elif isinstance(row, Donor):
            self.donors.append(row)

    async def delete(self, row):
        for collection in (self.donation_links, self.donation_methods, self.prize_pool_entries, self.donors):
            if row in collection:
                collection.remove(row)

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
            assert client.post(
                "/admin/donation-methods",
                data={"items": "<table><tbody><tr><td>card</td><td>L</td><td>D</td><td>1</td></tr></tbody></table>", "content_lang": "ru"},
                follow_redirects=False,
            ).status_code == 303
            assert client.post(
                "/admin/prize-pool",
                data={"items": "<table><tbody><tr><td>1</td><td>Reward</td></tr></tbody></table>", "content_lang": "ru"},
                follow_redirects=False,
            ).status_code == 303
            assert client.post(
                "/admin/donors",
                data={"items": "<table><tbody><tr><td>Name</td><td>$10</td><td>Hello</td></tr></tbody></table>", "content_lang": "ru"},
                follow_redirects=False,
            ).status_code == 303
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert fake_db.donation_links[0].title_ru == "A"
    assert fake_db.donation_methods[0].details_ru == "D"
    assert fake_db.prize_pool_entries[0].reward_ru == "Reward"
    assert fake_db.donors[0].message_ru == "Hello"


def test_donate_page_renders_sanitized_html_content():
    fake_db = _FakeContentDB()
    fake_db.donation_links = [DonationLink(title_ru="<strong>Link</strong>", title_en="", url="https://example.com", is_active=True)]
    fake_db.donation_methods = [DonationMethod(method_type="card", label_ru="<em>Card</em>", details_ru="<script>x</script>OK", is_active=True)]
    fake_db.prize_pool_entries = [PrizePoolEntry(place_label_ru="<b>1st</b>", reward_ru="<i>Gold</i>")]
    fake_db.donors = [Donor(name="Neo", amount="$1", message_ru="<u>Hi</u>")]

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
