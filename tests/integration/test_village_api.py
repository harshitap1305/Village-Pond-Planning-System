import uuid

from fastapi.testclient import TestClient

from src.api.main import app
from src.db.engine import is_db_configured

client = TestClient(app, raise_server_exceptions=False)


def test_search_villages_503_without_db():
    """Returns 503 when DB is not configured."""
    assert not is_db_configured()
    response = client.get("/village/search?q=test")
    assert response.status_code == 503


def test_get_village_kml_503_without_db():
    """Returns 503 when DB is not configured."""
    assert not is_db_configured()
    test_id = uuid.uuid4()
    response = client.get(f"/village/{test_id}/kml")
    assert response.status_code == 503


# We can also add tests with a mocked DB but that requires pytest-asyncio and
# overriding the get_async_session dependency, which might be overkill since we've
# already verified graceful degradation above.
