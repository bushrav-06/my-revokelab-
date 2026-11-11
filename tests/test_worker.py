import asyncio
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import worker
from app.database import Base
from app.models import User, Project, ExperimentRun
from app.runner import ExperimentOutcome, TimelineEvent


@pytest.fixture
def worker_db(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys = ON")

    TestingSession = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)

    with TestingSession() as db:
        user = User(
            id=1,
            username="tester",
            password_hash="test-hash",
            role="member",
        )
        db.add(user)
        db.flush()

        project = Project(
            id=1,
            name="Worker Test Project",
            created_by=1,
        )
        db.add(project)
        db.flush()

        experiment = ExperimentRun(
            id=1,
            owner_id=1,
            project_id=1,
            idempotency_key="worker-test-001",
            authorization_mode="continuous",
            cutoff_seconds=2,
            status="running",
            attempt_count=1,
            max_attempts=3,
        )
        db.add(experiment)
        db.commit()

    monkeypatch.setattr(worker, "SessionLocal", TestingSession)

    yield TestingSession

    Base.metadata.drop_all(engine)


def test_worker_saves_result_and_events(worker_db, monkeypatch):
    events = [
        TimelineEvent(
            "websocket_connected",
            "Connection established",
        ),
        TimelineEvent(
            "access_revoked",
            "Alice access revoked",
        ),
    ]

    async def fake_execute_experiment(**kwargs):
        return ExperimentOutcome("pass", events)

    monkeypatch.setattr(
        worker,
        "execute_experiment",
        fake_execute_experiment,
    )

    asyncio.run(
        worker.process_experiment({
            "id": 1,
            "attempt_number": 1,
            "authorization_mode": "continuous",
            "cutoff_seconds": 2,
        })
    )

    with worker_db() as db:
        experiment = db.get(ExperimentRun, 1)

        assert experiment.status == "succeeded"
        assert experiment.result == "pass"
        assert experiment.completed_at is not None

        assert len(experiment.events) == 2
        assert [e.sequence for e in experiment.events] == [1, 2]
        assert all(e.occurred_at is not None for e in experiment.events)

def test_worker_retries_failed_experiment(worker_db, monkeypatch):
    async def fake_execute_experiment(**kwargs):
        from app.runner import ExperimentExecutionError

        raise ExperimentExecutionError(
            "Temporary failure",
            [],
        )

    monkeypatch.setattr(
        worker,
        "execute_experiment",
        fake_execute_experiment,
    )

    asyncio.run(
        worker.process_experiment({
            "id": 1,
            "attempt_number": 1,
            "authorization_mode": "continuous",
            "cutoff_seconds": 2,
        })
    )

    with worker_db() as db:
        experiment = db.get(ExperimentRun, 1)

        assert experiment.status == "queued"
        assert experiment.error_code == "EXPERIMENT_EXECUTION_ERROR"
        assert experiment.completed_at is None

def test_worker_marks_experiment_failed_after_max_attempts(
    worker_db,
    monkeypatch,
):
    async def fake_execute_experiment(**kwargs):
        from app.runner import ExperimentExecutionError

        raise ExperimentExecutionError(
            "Permanent failure",
            [],
        )

    monkeypatch.setattr(
        worker,
        "execute_experiment",
        fake_execute_experiment,
    )

    # Simulate the third and final attempt.
    with worker_db() as db:
        experiment = db.get(ExperimentRun, 1)
        experiment.attempt_count = 3
        db.commit()

    asyncio.run(
        worker.process_experiment({
            "id": 1,
            "attempt_number": 3,
            "authorization_mode": "continuous",
            "cutoff_seconds": 2,
        })
    )

    with worker_db() as db:
        experiment = db.get(ExperimentRun, 1)

        assert experiment.status == "failed"
        assert experiment.error_code == "EXPERIMENT_EXECUTION_ERROR"
        assert experiment.completed_at is not None

def test_worker_recovers_interrupted_experiment(worker_db):
    job = worker.claim_next_experiment()

    assert job is not None
    assert job["id"] == 1
    assert job["attempt_number"] == 2

    with worker_db() as db:
        experiment = db.get(ExperimentRun, 1)

        assert experiment.status == "running"
        assert experiment.attempt_count == 2
        assert experiment.started_at is not None

        assert any(
            event.event_type == "worker_recovered"
            for event in experiment.events
        )
