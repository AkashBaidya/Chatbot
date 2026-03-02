"""Tests for server.py — FastAPI endpoints."""

import os
import pytest

# Ensure a dummy API key is set before importing server
os.environ.setdefault("GROQ_API_KEY", "gsk_test_dummy_key")

from fastapi.testclient import TestClient
from server import app


@pytest.fixture()
def client():
    """Fresh client per test — no shared cookies."""
    return TestClient(app, cookies={})


@pytest.fixture()
def admin_client():
    """Client already logged in as admin."""
    c = TestClient(app, cookies={})
    r = c.post("/api/admin/login", json={"password": "1243"})
    assert r.status_code == 200
    return c


class TestFrontend:
    def test_serves_html(self, client):
        r = client.get("/")
        assert r.status_code == 200
        assert "Trenkwalder" in r.text


class TestAdminAuth:
    def test_login_success(self, client):
        r = client.post("/api/admin/login", json={"password": "1243"})
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_login_wrong_password(self, client):
        r = client.post("/api/admin/login", json={"password": "wrong"})
        assert r.status_code == 403

    def test_admin_check_unauthenticated(self, client):
        r = client.get("/api/admin/check")
        assert r.json()["is_admin"] is False

    def test_admin_check_authenticated(self, admin_client):
        r = admin_client.get("/api/admin/check")
        assert r.json()["is_admin"] is True

    def test_protected_endpoint_without_auth(self, client):
        r = client.get("/api/admin/files")
        assert r.status_code == 401


class TestAdminApiConfig:
    def test_get_config(self, admin_client):
        r = admin_client.get("/api/admin/api-config")
        assert r.status_code == 200
        data = r.json()
        assert "tools" in data
        assert len(data["tools"]) == 4

    def test_tool_names(self, admin_client):
        r = admin_client.get("/api/admin/api-config")
        names = [t["name"] for t in r.json()["tools"]]
        assert "get_vacation_balance" in names
        assert "get_upcoming_holidays" in names


class TestAdminMockData:
    def test_get_mock_data(self, admin_client):
        r = admin_client.get("/api/admin/mock-data")
        assert r.status_code == 200
        data = r.json()
        assert "E001" in data["employees"]

    def test_update_mock_data_missing_employees(self, admin_client):
        r = admin_client.put("/api/admin/mock-data", json={"foo": "bar"})
        assert r.status_code == 400


class TestAdminTestService:
    def test_vacation_service(self, admin_client):
        r = admin_client.post(
            "/api/admin/test-service/get_vacation_balance",
            json={"params": {"employee_id": "E001"}},
        )
        assert r.status_code == 200
        assert r.json()["status"] == "ok"
        assert r.json()["result"]["vacation_days_remaining"] == 11

    def test_unknown_service(self, admin_client):
        r = admin_client.post(
            "/api/admin/test-service/nonexistent",
            json={"params": {}},
        )
        assert r.status_code == 404


class TestAdminKBFiles:
    def test_list_files(self, admin_client):
        r = admin_client.get("/api/admin/files")
        assert r.status_code == 200
        names = [f["name"] for f in r.json()["files"]]
        assert "benefits_guide.txt" in names
        assert "company_handbook.md" in names


class TestEmployeeAuth:
    def test_login_success(self, client):
        r = client.post(
            "/api/employee/login",
            json={"email": "alice@trenkwalder.com", "password": "alice123"},
        )
        assert r.status_code == 200
        assert r.json()["name"] == "Alice Mueller"
        assert r.json()["employee_id"] == "E001"

    def test_login_wrong_password(self, client):
        r = client.post(
            "/api/employee/login",
            json={"email": "alice@trenkwalder.com", "password": "wrong"},
        )
        assert r.status_code == 401

    def test_login_unknown_email(self, client):
        r = client.post(
            "/api/employee/login",
            json={"email": "nobody@trenkwalder.com", "password": "pass"},
        )
        assert r.status_code == 401

    def test_me_unauthenticated(self, client):
        r = client.get("/api/employee/me")
        assert r.json()["logged_in"] is False

    def test_me_authenticated(self, client):
        client.post(
            "/api/employee/login",
            json={"email": "alice@trenkwalder.com", "password": "alice123"},
        )
        r = client.get("/api/employee/me")
        assert r.json()["logged_in"] is True
        assert r.json()["name"] == "Alice Mueller"

    def test_logout(self, client):
        client.post(
            "/api/employee/login",
            json={"email": "bob@trenkwalder.com", "password": "bob123"},
        )
        client.post("/api/employee/logout")
        r = client.get("/api/employee/me")
        assert r.json()["logged_in"] is False


class TestChatEndpoint:
    def test_empty_message_rejected(self, client):
        r = client.post("/api/chat", json={"message": "   "})
        assert r.status_code == 400

    def test_reset(self, client):
        r = client.post("/api/reset")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"
