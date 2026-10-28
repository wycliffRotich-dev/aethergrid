from __future__ import annotations

import logging
import threading
from typing import Any

import psycopg

from app.application.scheduler_leadership import SchedulerLeadership

logger = logging.getLogger(__name__)

# The advisory lock key held by the process that leads the scheduler.
# It is not the migration lock key (nm_migra), so a migration run and
# a scheduler never wait on each other (ADR 0078).
SCHEDULER_LOCK_KEY = int.from_bytes(b"nm_sched", "big")

DEFAULT_CONNECT_TIMEOUT_SECONDS = 5

# The lock connection sits idle while a tick runs a job's command. The
# keepalive settings let the operating system find a connection that a
# firewall or NAT device dropped, and tcp_user_timeout bounds how long
# a ping can wait on a dead one.
KEEPALIVE_IDLE_SECONDS = 30
KEEPALIVE_INTERVAL_SECONDS = 10
KEEPALIVE_PROBES = 3
TCP_USER_TIMEOUT_MILLISECONDS = 10_000


class PostgresSchedulerLeadership(SchedulerLeadership):
    """
    Leadership held as a Postgres session level advisory lock
    (ADR 0078).

    The lock lives on a dedicated connection that is not part of the
    pool, because a pooled connection goes back to the pool and the
    lock would go with it. The connection must reach Postgres
    directly: session level locks do not survive a transaction mode
    pooler. It connects with autocommit, so it never sits idle inside
    a transaction.

    Postgres releases the lock when the connection ends, however it
    ends, so a crashed leader loses leadership without any cleanup.
    While the connection is open this process leads. Each call to
    try_acquire pings it, and a failed ping means leadership is gone.
    """

    def __init__(
        self,
        database_url: str,
        password: str | None = None,
        lock_key: int = SCHEDULER_LOCK_KEY,
        connect_timeout_seconds: int = DEFAULT_CONNECT_TIMEOUT_SECONDS,
    ) -> None:
        self._lock_key = lock_key
        self._database_url = database_url
        self._connect_kwargs: dict[str, Any] = {
            "autocommit": True,
            "connect_timeout": connect_timeout_seconds,
            "keepalives": 1,
            "keepalives_idle": KEEPALIVE_IDLE_SECONDS,
            "keepalives_interval": KEEPALIVE_INTERVAL_SECONDS,
            "keepalives_count": KEEPALIVE_PROBES,
            "tcp_user_timeout": TCP_USER_TIMEOUT_MILLISECONDS,
        }
        if password is not None:
            self._connect_kwargs["password"] = password

        self._guard = threading.Lock()
        self._connection: psycopg.Connection | None = None
        self._unreachable = False

    def try_acquire(self) -> bool:
        with self._guard:
            if self._connection is not None:
                if self._still_connected(self._connection):
                    return True
                self._close(self._connection)
                self._connection = None
                logger.warning(
                    "This process lost the scheduler lock because its "
                    "connection failed.",
                )
            return self._take_lock()

    def release(self) -> None:
        with self._guard:
            connection = self._connection
            if connection is None:
                return
            self._connection = None
            try:
                connection.execute(
                    "SELECT pg_advisory_unlock(%s::bigint)",
                    (self._lock_key,),
                )
            except psycopg.Error:
                # A broken connection drops its session locks when
                # it closes, and a failed unlock must not hide the
                # reason the caller is releasing.
                pass
            self._close(connection)
            logger.info("This process released the scheduler lock.")

    def _take_lock(self) -> bool:
        try:
            connection = psycopg.connect(
                self._database_url,
                **self._connect_kwargs,
            )
        except psycopg.Error as error:
            self._note_unreachable(error)
            return False

        try:
            row = connection.execute(
                "SELECT pg_try_advisory_lock(%s::bigint)",
                (self._lock_key,),
            ).fetchone()
        except psycopg.Error as error:
            self._close(connection)
            self._note_unreachable(error)
            return False

        self._note_reachable()

        if row is None or not row[0]:
            self._close(connection)
            return False

        self._connection = connection
        logger.info("This process now leads the scheduler.")
        return True

    @staticmethod
    def _still_connected(connection: psycopg.Connection) -> bool:
        try:
            connection.execute("SELECT 1")
        except psycopg.Error:
            return False
        return True

    @staticmethod
    def _close(connection: psycopg.Connection) -> None:
        try:
            connection.close()
        except psycopg.Error:
            pass

    def _note_unreachable(self, error: psycopg.Error) -> None:
        if self._unreachable:
            return
        self._unreachable = True
        logger.warning(
            "Scheduler leadership cannot reach the database: %s",
            str(error).strip(),
        )

    def _note_reachable(self) -> None:
        if not self._unreachable:
            return
        self._unreachable = False
        logger.info("Scheduler leadership reached the database again.")
