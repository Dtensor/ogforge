"""Database access layer — drives SQLite (dev/tests) or Postgres (prod) off DATABASE_URL.

No ORM. A thin `DB` wrapper normalizes the two drivers so the rest of the app is
driver-agnostic: it translates `?` placeholders to `%s` for Postgres, returns dict-like
rows from both, and provides `insert_returning_id()` for the one INSERT that needs the
new row id (SQLite lastrowid vs Postgres RETURNING).

Schema:
  users(id, email UNIQUE, password_hash, plan ['free'|'pro'], stripe_customer_id, created_at)
  api_keys(id, user_id, key UNIQUE, revoked, created_at)
  usage(id, user_id, endpoint, ts)   -- one row per generated image
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone

from .config import settings

# Catch unique-violation from whichever driver is present. Harmless to list both.
INTEGRITY_ERRORS: tuple = (sqlite3.IntegrityError,)
try:  # psycopg is only installed in prod images, optional in dev
    import psycopg  # noqa: F401
    from psycopg import errors as _pg_errors

    INTEGRITY_ERRORS = (sqlite3.IntegrityError, _pg_errors.UniqueViolation)
except Exception:  # pragma: no cover - psycopg absent in pure-sqlite envs
    pass


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _database_url() -> str:
    """DATABASE_URL wins (prod Postgres); otherwise fall back to the SQLite file path."""
    return os.environ.get("DATABASE_URL", "").strip()


def _is_pg(url: str) -> bool:
    return url.startswith("postgres://") or url.startswith("postgresql://")


def _db_path() -> str:
    """SQLite path, resolved at call time so per-test DB_PATH overrides take effect."""
    return os.environ.get("DB_PATH", settings.db_path)


def _schema_statements(is_pg: bool) -> list[str]:
    pk = "BIGSERIAL PRIMARY KEY" if is_pg else "INTEGER PRIMARY KEY AUTOINCREMENT"
    intref = "BIGINT" if is_pg else "INTEGER"
    return [
        f"""CREATE TABLE IF NOT EXISTS users (
            id                  {pk},
            email               TEXT UNIQUE NOT NULL,
            password_hash       TEXT NOT NULL,
            plan                TEXT NOT NULL DEFAULT 'free',
            pro_until           TEXT,
            created_at          TEXT NOT NULL
        )""",
        f"""CREATE TABLE IF NOT EXISTS api_keys (
            id          {pk},
            user_id     {intref} NOT NULL REFERENCES users(id),
            key         TEXT UNIQUE NOT NULL,
            revoked     INTEGER NOT NULL DEFAULT 0,
            created_at  TEXT NOT NULL
        )""",
        f"""CREATE TABLE IF NOT EXISTS usage (
            id          {pk},
            user_id     {intref} NOT NULL REFERENCES users(id),
            endpoint    TEXT NOT NULL,
            ts          TEXT NOT NULL
        )""",
        "CREATE INDEX IF NOT EXISTS idx_usage_user_ts ON usage(user_id, ts)",
        "CREATE INDEX IF NOT EXISTS idx_api_keys_key ON api_keys(key)",
    ]


class _Cursor:
    """Wraps a driver cursor so callers can chain .fetchone()/.fetchall()."""

    def __init__(self, cur):
        self._cur = cur

    def fetchone(self):
        return self._cur.fetchone()

    def fetchall(self):
        return self._cur.fetchall()

    @property
    def lastrowid(self):
        return self._cur.lastrowid


class _Buffered:
    """Holds rows already fetched (for pooled Postgres ops, where the connection is
    borrowed and returned inside execute() so it never crosses threads)."""

    def __init__(self, rows):
        self._rows = list(rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows


class DB:
    """Driver-agnostic connection wrapper.

    For Postgres it borrows a pooled connection LAZILY on first use, so the borrow
    happens in the same thread that runs the queries. This is critical under FastAPI:
    the get_db dependency runs in a different threadpool thread than the path-operation
    function, and a psycopg connection used across threads desyncs the wire protocol and
    hangs forever in connection.wait(). Borrowing on first execute() (called from the
    endpoint thread) keeps every query on one thread.
    """

    def __init__(self, raw, is_pg: bool, pool=None):
        self._raw = raw
        self.is_pg = is_pg
        self._pool = pool  # set => pooled mode (borrow per op); None => direct/sqlite

    def _adapt(self, sql: str) -> str:
        return sql.replace("?", "%s") if self.is_pg else sql

    def execute(self, sql: str, params: tuple = ()):
        if self._pool is not None:
            # Pooled: borrow, run, fetch, return — all inside this one call, so the
            # connection lives entirely on the calling (endpoint) thread. autocommit
            # means each statement is independent, so per-op borrowing is correct.
            with self._pool.connection() as conn:
                cur = conn.cursor()
                cur.execute(self._adapt(sql), params)
                rows = cur.fetchall() if cur.description else []
                return _Buffered(rows)
        if self.is_pg:
            cur = self._raw.cursor()
            cur.execute(self._adapt(sql), params)
            return _Cursor(cur)
        return _Cursor(self._raw.execute(sql, params))

    def insert_returning_id(self, sql: str, params: tuple = ()) -> int:
        """Run an INSERT (written with `?`, NO RETURNING clause) and return the new id."""
        if self._pool is not None:
            with self._pool.connection() as conn:
                cur = conn.cursor()
                cur.execute(self._adapt(sql) + " RETURNING id", params)
                return int(cur.fetchone()["id"])
        if self.is_pg:
            cur = self._raw.cursor()
            cur.execute(self._adapt(sql) + " RETURNING id", params)
            return int(cur.fetchone()["id"])
        return int(self._raw.execute(sql, params).lastrowid)

    def commit(self) -> None:
        # Pooled connections run autocommit, so this is a no-op there.
        if self._raw is not None:
            self._raw.commit()

    def rollback(self) -> None:
        if self._raw is not None:
            self._raw.rollback()

    def release(self) -> None:
        """Pooled mode holds nothing between ops, so there is nothing to release."""
        return

    def close(self) -> None:
        if self._raw is not None and self._pool is None:
            self._raw.close()


# Postgres connection pool — created lazily, kept warm. Opening a fresh connection
# per request against Neon's pooler intermittently blocks for >10s; a pool reuses
# warm connections and bounds total connections.
_pool = None


def _get_pool():
    global _pool
    if _pool is None:
        from psycopg.rows import dict_row
        from psycopg_pool import ConnectionPool

        def _configure(conn):
            # Disable prepared statements: this app manages its own pool, and if it ever
            # points at a transaction-mode pooler (e.g. Neon's -pooler / PgBouncer),
            # prepared statements break because the named statement lives on a different
            # server connection than the next execute lands on. Harmless on a direct conn.
            conn.prepare_threshold = None

        _pool = ConnectionPool(
            _database_url(),
            min_size=2,
            max_size=10,
            timeout=15,
            max_idle=120,
            # check on borrow: validate (and transparently replace) stale connections.
            # Neon drops idle server-side connections, which would otherwise hang on use.
            check=ConnectionPool.check_connection,
            # autocommit: each statement commits immediately, so a pooled connection is
            # never returned with a dangling transaction. Explicit db.commit() calls
            # become harmless no-ops.
            kwargs={
                "row_factory": dict_row,
                "autocommit": True,
                "connect_timeout": 10,
                # TCP keepalives detect dead connections; statement_timeout makes any
                # wedged query fail (15s) instead of hanging a worker indefinitely.
                "keepalives": 1,
                "keepalives_idle": 30,
                "keepalives_interval": 10,
                "keepalives_count": 3,
                "options": "-c statement_timeout=15000",
            },
            configure=_configure,
            open=True,
        )
    return _pool


def connect() -> DB:
    """Open a standalone connection (used by init_db / scripts). Routes use the pool
    via get_db()."""
    url = _database_url()
    if _is_pg(url):
        import psycopg
        from psycopg.rows import dict_row

        conn = psycopg.connect(url, row_factory=dict_row, connect_timeout=10)
        return DB(conn, is_pg=True)

    # SQLite. check_same_thread=False: the per-request connection may be created by the
    # sync get_db() dependency in a threadpool worker, then used by an async route handler
    # on the event-loop thread. One request owns it for its lifetime — never shared.
    conn = sqlite3.connect(_db_path(), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return DB(conn, is_pg=False)


def init_db() -> None:
    db = connect()
    try:
        for stmt in _schema_statements(db.is_pg):
            db.execute(stmt)
        # Migrate: add pro_until to pre-existing users tables (created before this column).
        if db.is_pg:
            db.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS pro_until TEXT")
        else:
            cols = [r["name"] for r in db.execute("PRAGMA table_info(users)").fetchall()]
            if "pro_until" not in cols:
                db.execute("ALTER TABLE users ADD COLUMN pro_until TEXT")
        db.commit()
    finally:
        db.close()


def get_db():
    """FastAPI dependency.

    Postgres: borrow a connection from the warm pool for the request (returned, not
    closed, on exit). SQLite: open and close a per-request connection.
    """
    if _is_pg(_database_url()):
        db = DB(None, is_pg=True, pool=_get_pool())  # borrows lazily in the request thread
        try:
            yield db
        finally:
            db.release()
    else:
        db = connect()
        try:
            yield db
        finally:
            db.close()
