import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture()
def app(tmp_path):
    a = create_app(str(tmp_path / "test.db"))
    a.state.settings.log_dir = str(tmp_path / "logs")
    return a


@pytest.fixture()
def client(app):
    return TestClient(app)
