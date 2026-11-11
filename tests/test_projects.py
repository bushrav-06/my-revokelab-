from datetime import datetime
import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault(
    "REVOKELAB_SESSION_SECRET",
    "test-only-key-never-used-in-production",
)

from app.auth import hash_password
from app.database import Base, get_db
from app.main import app
from app.models import Membership, Project, User


@pytest.fixture
def client(monkeypatch):
    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(test_engine, "connect")
    def enable_foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys = ON")

    TestingSession = sessionmaker(bind=test_engine)
    monkeypatch.setattr(
        "app.realtime.SessionLocal",
        TestingSession,
    )
    Base.metadata.create_all(test_engine)

    with TestingSession() as database:
        admin = User(
            id=1,
            username="admin",
            password_hash=hash_password("admin-test-password"),
            role="admin",
        )
        alice = User(
            id=2,
            username="alice",
            password_hash=hash_password("alice-test-password"),
            role="member",
        )
        bob = User(
            id=3,
            username="bob",
            password_hash=hash_password("bob-test-password"),
            role="member",
        )
        database.add_all([admin, alice, bob])
        database.flush()

        project = Project(
            id=1,
            name="Project Red",
            created_by=admin.id,
        )
        database.add(project)
        database.flush()

        database.add(
            Membership(
                id=1,
                user_id=alice.id,
                project_id=project.id,
                status="active",
            )
        )
        database.commit()

    def override_database():
        with TestingSession() as database:
            yield database

    app.dependency_overrides[get_db] = override_database

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()
    Base.metadata.drop_all(test_engine)


def login(client: TestClient, username: str, password: str) -> None:
    response = client.post(
        "/auth/login",
        data={"username": username, "password": password},
    )
    assert response.status_code == 200

def test_connection_only_socket_leaks_message_after_revocation(
    client: TestClient,
):
    login(client, "alice", "alice-test-password")

    with client.websocket_connect(
        "/ws/connection-only/projects/1"
    ) as websocket:
        connected = websocket.receive_json()
        assert connected["type"] == "connected"

        login(client, "admin", "admin-test-password")
        client.post("/projects/1/members/2/revoke")

        response = client.post(
            "/projects/1/messages",
            json={
                "message_code": "DEMO-LEAK",
                "content": "Created after Alice was removed",
            },
        )
        assert response.status_code == 201

        leaked_message = websocket.receive_json()
        assert leaked_message["type"] == "private_message"
        assert leaked_message["message"]["message_code"] == "DEMO-LEAK"

    client.post("/projects/1/members/2/grant")


def test_continuous_socket_blocks_message_after_revocation(
    client: TestClient,
):
    login(client, "alice", "alice-test-password")

    with client.websocket_connect(
        "/ws/continuous/projects/1"
    ) as websocket:
        connected = websocket.receive_json()
        assert connected["type"] == "connected"

        login(client, "admin", "admin-test-password")
        client.post("/projects/1/members/2/revoke")

        response = client.post(
            "/projects/1/messages",
            json={
                "message_code": "DEMO-BLOCKED",
                "content": "Alice must not receive this",
            },
        )
        assert response.status_code == 201

        revocation_notice = websocket.receive_json()
        assert revocation_notice["type"] == "access_revoked"
        assert "removed" in revocation_notice["detail"]

    client.post("/projects/1/members/2/grant")
def test_bob_cannot_read_project(client: TestClient):
    login(client, "bob", "bob-test-password")

    response = client.get("/projects/1")

    assert response.status_code == 403


def test_message_creation_is_safe_to_retry(client: TestClient):
    login(client, "alice", "alice-test-password")
    payload = {
        "message_code": "DEMO-001",
        "content": "Private test message",
    }

    first = client.post("/projects/1/messages", json=payload)
    second = client.post("/projects/1/messages", json=payload)

    assert first.status_code == 201
    assert first.json()["created"] is True
    assert second.status_code == 200
    assert second.json()["created"] is False
    assert second.json()["id"] == first.json()["id"]


def test_revocation_blocks_and_grant_restores_access(client: TestClient):
    login(client, "admin", "admin-test-password")

    first_revoke = client.post("/projects/1/members/2/revoke")
    second_revoke = client.post("/projects/1/members/2/revoke")

    assert first_revoke.json()["changed"] is True
    assert second_revoke.json()["changed"] is False

    login(client, "alice", "alice-test-password")
    assert client.get("/projects/1").status_code == 403

    login(client, "admin", "admin-test-password")
    first_grant = client.post("/projects/1/members/2/grant")
    second_grant = client.post("/projects/1/members/2/grant")

    assert first_grant.json()["changed"] is True
    assert second_grant.json()["changed"] is False

    login(client, "alice", "alice-test-password")
    assert client.get("/projects/1").status_code == 200
    
def test_experiment_creation_is_safe_to_retry(client: TestClient):
    login(client, "alice", "alice-test-password")

    headers = {"Idempotency-Key": "automated-test-001"}
    payload = {
        "project_id": 1,
        "authorization_mode": "continuous",
        "cutoff_seconds": 2,
    }

    first = client.post("/experiments", headers=headers, json=payload)
    second = client.post("/experiments", headers=headers, json=payload)

    assert first.status_code == 202
    assert second.status_code == 202
    assert second.json()["id"] == first.json()["id"]

    changed = client.post(
        "/experiments",
        headers=headers,
        json={**payload, "cutoff_seconds": 3},
    )
    assert changed.status_code == 409


def test_experiment_creation_requires_authentication(client: TestClient):
    response = client.post(
        "/experiments",
        headers={"Idempotency-Key": "unauthorized-test-001"},
        json={
            "project_id": 1,
            "authorization_mode": "continuous",
            "cutoff_seconds": 2,
        },
    )
assert response.status_code == 401
def test_revoked_alice_cannot_create_message(client: TestClient):
    login(client, "admin", "admin-test-password")

    revoke = client.post("/projects/1/members/2/revoke")
    assert revoke.status_code == 200

    login(client, "alice", "alice-test-password")

    response = client.post(
        "/projects/1/messages",
        json={
            "message_code": "REVOKED-001",
            "content": "Alice should not create this",
        },
    )

    assert response.status_code == 403

def test_experiment_timestamps_are_valid(client: TestClient):
    login(client, "alice", "alice-test-password")

    response = client.post(
        "/experiments",
        headers={"Idempotency-Key": "timestamp-test-001"},
        json={
            "project_id": 1,
            "authorization_mode": "continuous",
            "cutoff_seconds": 2,
        },
    )

    assert response.status_code == 202
    data = response.json()

    assert data["created_at"]
    datetime.fromisoformat(data["created_at"].replace("Z", "+00:00"))

    for field in ("started_at", "completed_at"):
        if data.get(field):
            datetime.fromisoformat(data[field].replace("Z", "+00:00"))

    for event in data["events"]:
        assert event["occurred_at"]
        datetime.fromisoformat(
            event["occurred_at"].replace("Z", "+00:00")
        )
def test_messages_have_unique_ids(client: TestClient):
    login(client, "alice", "alice-test-password")

    first = client.post(
        "/projects/1/messages",
        json={"message_code": "UNIQUE-001", "content": "First"},
    )
    second = client.post(
        "/projects/1/messages",
        json={"message_code": "UNIQUE-002", "content": "Second"},
    )

assert first.status_code == 201
assert second.status_code == 201
assert first.json()["id"] != second.json()["id"]