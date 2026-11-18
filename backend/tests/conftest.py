import os
import sys
import tempfile
from pathlib import Path

import pytest

_tmp = tempfile.mkdtemp(prefix="docops-test-")
os.environ.update({
    "DATABASE_URL": f"sqlite:///{_tmp}/test.db",
    "REDIS_URL": "memory://",
    "SECRET_KEY": "test-secret-key-0123456789abcdef0123456789",
    "ADMIN_EMAIL": "admin@teste.local",
    "ADMIN_PASSWORD": "Admin#Inicial2026",
    "COOKIE_SECURE": "false",
    "COLLECTOR_COST_EXPLORER": "false",
    "AWS_ACCESS_KEY_ID": "test", "AWS_SECRET_ACCESS_KEY": "test", "AWS_DEFAULT_REGION": "us-east-1",
})
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
FIXTURES = Path(__file__).parent / "fixtures"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app, bootstrap  # noqa: E402

H = {"X-DocOps": "1"}


@pytest.fixture(scope="session")
def client():
    bootstrap()
    with TestClient(app) as c:
        yield c


def login(c, email, password, totp=None):
    c.cookies.clear()
    return c.post("/api/auth/login", json={"email": email, "password": password, "totp": totp}, headers=H)


@pytest.fixture(scope="session")
def admin(client):
    r = login(client, "admin@teste.local", "Admin#Inicial2026")
    assert r.status_code == 200, r.text
    assert r.json()["must_change_password"] is True
    r = client.post("/api/auth/password", json={"current": "Admin#Inicial2026", "new": "Admin#Trocada2026"}, headers=H)
    assert r.status_code == 200, r.text
    return {"email": "admin@teste.local", "password": "Admin#Trocada2026"}
