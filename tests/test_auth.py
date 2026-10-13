"""HTTP Basic — włączane hasłem w DZIENNIK_PASSWORD (na RPi)."""

import base64

import pytest
from fastapi.testclient import TestClient

import app.main as main


def basic(user: str, password: str) -> dict:
    return {"Authorization": "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()}


@pytest.fixture
def client():
    return TestClient(main.app)


def test_no_password_means_open(client):
    assert client.get("/static/app.css").status_code == 200


@pytest.mark.parametrize("headers", [
    pytest.param({}, id="no_header"),
    pytest.param(basic("kuba", "zle"), id="wrong_password"),
    pytest.param(basic("ktos", "sekret"), id="wrong_user"),
    pytest.param({"Authorization": "Basic !!!"}, id="garbage"),
])
def test_password_required(client, monkeypatch, headers):
    monkeypatch.setenv("DZIENNIK_PASSWORD", "sekret")
    r = client.get("/static/app.css", headers=headers)
    assert r.status_code == 401
    assert r.headers["www-authenticate"].startswith("Basic")


def test_correct_password(client, monkeypatch):
    monkeypatch.setenv("DZIENNIK_PASSWORD", "sekret")
    monkeypatch.setenv("DZIENNIK_USER", "kuba")
    assert client.get("/static/app.css", headers=basic("kuba", "sekret")).status_code == 200
