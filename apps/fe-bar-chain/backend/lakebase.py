"""Lakebase connection pool with OAuth token rotation.

Pattern lifted from the existing prompt-to-pnl-bdl app: psycopg3 +
ConnectionPool + token refresh.  The app SP mints its own credential at
runtime via the SDK — no static password, no secret in app.yaml.
"""
import logging
import threading
import time
from contextlib import contextmanager

import psycopg
from psycopg_pool import ConnectionPool
from databricks.sdk import WorkspaceClient

from . import config

log = logging.getLogger(__name__)

_w = WorkspaceClient()

# ---- token management ------------------------------------------------

_token_lock = threading.Lock()
_current_token: str = ""
_token_expires: float = 0.0


def _refresh_token() -> str:
    global _current_token, _token_expires
    cred = _w.postgres.generate_database_credential(
        endpoint=config.LAKEBASE_ENDPOINT
    )
    with _token_lock:
        _current_token = cred.token
        _token_expires = time.time() + 2700  # 45 min (token valid 1 hr)
    log.info("Lakebase OAuth token refreshed")
    return _current_token


def _get_token() -> str:
    if time.time() >= _token_expires:
        return _refresh_token()
    with _token_lock:
        return _current_token


# ---- pool ------------------------------------------------------------

def _get_pguser() -> str:
    """The login role is the SP client-id when running as a deployed App,
    or the user email when running locally."""
    try:
        return _w.current_user.me().user_name
    except Exception:
        return "unknown"


class _TokenConn(psycopg.Connection):
    """Subclass that injects a fresh token at connect time."""

    @classmethod
    def connect(cls, conninfo="", **kwargs):
        kwargs["password"] = _get_token()
        return super().connect(conninfo, **kwargs)


_pool: ConnectionPool | None = None
_pool_lock = threading.Lock()


def _close_pool():
    global _pool
    if _pool is not None:
        try:
            _pool.close()
        except Exception:
            pass
        _pool = None


def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                _refresh_token()
                conninfo = psycopg.conninfo.make_conninfo(
                    host=config.LAKEBASE_HOST,
                    dbname=config.LAKEBASE_DB,
                    user=_get_pguser(),
                    sslmode="require",
                )
                _pool = ConnectionPool(
                    conninfo=conninfo,
                    connection_class=_TokenConn,
                    min_size=0,
                    max_size=8,
                    max_idle=60,
                    max_lifetime=600,
                    check=ConnectionPool.check_connection,
                    open=True,
                )
                log.info("Lakebase pool opened (%s)", config.LAKEBASE_HOST)
    return _pool


@contextmanager
def conn():
    """Yield a connection from the pool."""
    pool = get_pool()
    with pool.connection() as c:
        yield c


def _retry(fn):
    """Lakebase Autoscaling kills idle backends; retry once on a fresh pool."""
    try:
        return fn()
    except (psycopg.OperationalError, psycopg.errors.AdminShutdown) as e:
        log.warning("Lakebase connection dead (%s), resetting pool", e)
        with _pool_lock:
            _close_pool()
        _refresh_token()
        return fn()


# ---- helpers ---------------------------------------------------------

def insert_input(run_id: str, curve_id: str, region: str, payload: dict):
    def _go():
        with conn() as c:
            c.execute(
                f"INSERT INTO {config.LAKEBASE_SCHEMA}.model_inputs "
                "(run_id, curve_id, region, payload) VALUES (%s, %s, %s, %s) "
                "ON CONFLICT (run_id) DO NOTHING",
                (run_id, curve_id, region, psycopg.types.json.Json(payload)),
            )
    _retry(_go)


def insert_output(run_id: str, model_id: str, version: int,
                  result: dict, latency_ms: int):
    def _go():
        with conn() as c:
            c.execute(
                f"INSERT INTO {config.LAKEBASE_SCHEMA}.model_outputs "
                "(run_id, model_id, version, result, latency_ms) "
                "VALUES (%s, %s, %s, %s, %s) "
                "ON CONFLICT (run_id, model_id) DO NOTHING",
                (run_id, model_id, version,
                 psycopg.types.json.Json(result), latency_ms),
            )
    _retry(_go)


def upsert_run_state(run_id: str, status: str,
                     total_ms: int | None = None):
    def _go():
        with conn() as c:
            c.execute(
                f"INSERT INTO {config.LAKEBASE_SCHEMA}.run_state "
                "(run_id, status, total_ms) VALUES (%s, %s, %s) "
                "ON CONFLICT (run_id) DO UPDATE SET "
                "status = EXCLUDED.status, "
                "completed_at = CASE WHEN EXCLUDED.status IN ('complete','failed') "
                "  THEN now() ELSE run_state.completed_at END, "
                "total_ms = COALESCE(EXCLUDED.total_ms, run_state.total_ms)",
                (run_id, status, total_ms),
            )
    _retry(_go)


def execute_sql(sql: str, params=None):
    """Execute a write SQL statement."""
    def _go():
        with conn() as c:
            c.execute(sql, params)
    _retry(_go)


def fetch_sql(sql: str, params=None):
    """Execute a read SQL and return all rows."""
    def _go():
        with conn() as c:
            cur = c.execute(sql, params)
            return cur.fetchall()
    return _retry(_go)
