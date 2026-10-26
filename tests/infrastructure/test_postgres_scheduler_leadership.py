import os
import time
from collections.abc import Callable, Iterator

import psycopg
import pytest

from app.infrastructure.database_credentials import (
    resolve_database_password,
)
from app.infrastructure.postgres_scheduler_leadership import (
    PostgresSchedulerLeadership,
)

# Not the key a running scheduler uses, so these tests cannot
# interfere with one that shares the test database.
TEST_LOCK_KEY = int.from_bytes(b"nm_test1", "big")

LockHolders = Callable[[], list[int]]


@pytest.fixture
def password(test_database_url: str) -> str | None:
    return resolve_database_password(test_database_url, os.environ)


@pytest.fixture
def make_leadership(
    test_database_url: str,
    password: str | None,
) -> Iterator[Callable[[], PostgresSchedulerLeadership]]:
    created: list[PostgresSchedulerLeadership] = []

    def make() -> PostgresSchedulerLeadership:
        leadership = PostgresSchedulerLeadership(
            test_database_url,
            password=password,
            lock_key=TEST_LOCK_KEY,
        )
        created.append(leadership)
        return leadership

    yield make

    for leadership in created:
        leadership.release()


@pytest.fixture
def lock_holders(
    test_database_url: str,
    password: str | None,
) -> LockHolders:
    def holders() -> list[int]:
        kwargs: dict[str, object] = {"autocommit": True}
        if password is not None:
            kwargs["password"] = password
        with psycopg.connect(test_database_url, **kwargs) as connection:
            rows = connection.execute(
                "SELECT pid FROM pg_locks "
                "WHERE locktype = 'advisory' AND granted "
                "AND objsubid = 1 "
                "AND database = (SELECT oid FROM pg_database "
                "WHERE datname = current_database()) "
                "AND ((classid::bigint << 32) | objid::bigint) "
                "= %s::bigint",
                (TEST_LOCK_KEY,),
            ).fetchall()
        return [row[0] for row in rows]

    return holders


def _wait_until_free(lock_holders: LockHolders) -> None:
    deadline = time.monotonic() + 5.0
    while lock_holders():
        assert time.monotonic() < deadline, "the lock was never freed"
        time.sleep(0.05)


def test_the_first_process_leads_and_the_second_does_not(
    make_leadership: Callable[[], PostgresSchedulerLeadership],
) -> None:
    first = make_leadership()
    second = make_leadership()

    assert first.try_acquire() is True
    assert second.try_acquire() is False


def test_a_leader_keeps_leading_without_stacking_the_lock(
    make_leadership: Callable[[], PostgresSchedulerLeadership],
    lock_holders: LockHolders,
) -> None:
    leader = make_leadership()

    assert leader.try_acquire() is True
    assert leader.try_acquire() is True
    assert leader.try_acquire() is True
    assert len(lock_holders()) == 1

    leader.release()

    assert lock_holders() == []


def test_a_follower_takes_over_after_the_leader_releases(
    make_leadership: Callable[[], PostgresSchedulerLeadership],
) -> None:
    leader = make_leadership()
    follower = make_leadership()
    leader.try_acquire()
    assert follower.try_acquire() is False

    leader.release()

    assert follower.try_acquire() is True
    assert leader.try_acquire() is False


def test_a_follower_takes_over_when_the_leader_connection_dies(
    make_leadership: Callable[[], PostgresSchedulerLeadership],
    lock_holders: LockHolders,
    test_database_url: str,
    password: str | None,
) -> None:
    leader = make_leadership()
    follower = make_leadership()
    assert leader.try_acquire() is True
    (leader_pid,) = lock_holders()

    kwargs: dict[str, object] = {"autocommit": True}
    if password is not None:
        kwargs["password"] = password
    with psycopg.connect(test_database_url, **kwargs) as admin:
        admin.execute("SELECT pg_terminate_backend(%s)", (leader_pid,))
    _wait_until_free(lock_holders)

    assert follower.try_acquire() is True
    assert leader.try_acquire() is False


def test_an_unreachable_database_reports_false_and_does_not_raise() -> None:
    leadership = PostgresSchedulerLeadership(
        "postgresql://nobody@127.0.0.1:1/none",
        connect_timeout_seconds=1,
    )

    assert leadership.try_acquire() is False
    assert leadership.try_acquire() is False


def test_release_is_safe_when_not_leading_and_when_repeated(
    make_leadership: Callable[[], PostgresSchedulerLeadership],
) -> None:
    leadership = make_leadership()

    leadership.release()
    leadership.try_acquire()
    leadership.release()
    leadership.release()
