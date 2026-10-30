"""Thin database layer that speaks both SQLite and PostgreSQL.

Deliberately small: a connection factory, a dict-row cursor wrapper, and a
transaction helper. Everything above this layer is dialect-agnostic.
"""
from __future__ import annotations

import json
import re
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

from .schema import render_schema


def new_id() -> str:
    return str(uuid.uuid4())


def utcnow_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def to_dialect(sql: str, dialect: str) -> str:
    """Translate the neutral placeholder style into the driver's style.

    The codebase writes ``?`` placeholders everywhere so the SQL reads the
    same in both backends.  psycopg2 wants ``%s``.  A literal ``%`` in the
    SQL is doubled at the same time, because psycopg2 would otherwise read
    it as a format specifier.
    """
    if dialect != "postgresql":
        return sql
    return sql.replace("%", "%%").replace("?", "%s")


_INSERT_RE = re.compile(
    r"INSERT\s+INTO\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(([^)]*)\)",
    re.IGNORECASE)


# `column = 1` / `column = 0` against a boolean column is invalid in
# PostgreSQL.  These patterns are rewritten to the boolean literals.
# Matches "<lhs>=<digit>" capturing the last identifier of the lhs.
_BOOL_CMP = re.compile(
    r"((?:[A-Za-z_][A-Za-z0-9_]*\.)?(?:[A-Za-z_][A-Za-z0-9_]*)\s*=\s*)([01])\b")


def _insert_columns(sql: str) -> tuple[str | None, list[str]]:
    """Return (table, columns) for an INSERT statement, else (None, [])."""
    m = _INSERT_RE.search(sql)
    if not m:
        return None, []
    table = m.group(1).strip('"')
    cols = [c.strip().strip('"') for c in m.group(2).split(",") if c.strip()]
    return table, cols


def rewrite_bool_literals(sql: str, bool_names: set[str]) -> str:
    """Rewrite ``col = 1`` / ``col = 0`` for known boolean columns.

    Only columns that are actually boolean in the schema are touched, so a
    legitimate ``quantity = 1`` comparison is left alone.
    """
    if not bool_names:
        return sql

    def repl(m: "re.Match[str]") -> str:
        # group(1) is "<lhs>=", group(2) is the digit.  The column name is the
        # last identifier before the "=", with any table qualifier removed.
        lhs = m.group(1).rsplit("=", 1)[0].strip()
        col = lhs.split(".")[-1].strip().strip('"')
        if col.lower() not in bool_names:
            return m.group(0)
        return m.group(1) + ("TRUE" if m.group(2) == "1" else "FALSE")

    return _BOOL_CMP.sub(repl, sql)


class Database:
    """Connection factory + helpers.

    ``url`` accepts ``sqlite:///path`` or ``postgres://...``.
    """

    def __init__(self, url: str):
        self.url = url
        self.dialect = "sqlite" if url.startswith("sqlite") else "postgresql"
        self._conn = None
        self._bool_columns: dict[str, set[str]] = {}
        # Serialises access to the connection.  SQLite tolerates one
        # writer at a time; the lock turns "tolerates" into "guarantees".
        self._lock = threading.RLock()

    # -- connection ----------------------------------------------------
    @property
    def conn(self):
        if self._conn is None:
            if self.dialect == "sqlite":
                path = self.url.split("sqlite:///", 1)[-1] or ":memory:"
                if path != ":memory:":
                    Path(path).parent.mkdir(parents=True, exist_ok=True)
                # check_same_thread=False because FastAPI runs the
                # synchronous route handlers in a worker thread, and a
                # request may land on a different thread from the one
                # that opened the connection.  The lock below keeps the
                # access serialised, so this is safe rather than merely
                # tolerated.
                self._conn = sqlite3.connect(path,
                                             detect_types=sqlite3.PARSE_DECLTYPES,
                                             check_same_thread=False)
                self._conn.row_factory = sqlite3.Row
                self._conn.execute("PRAGMA foreign_keys = ON")
            else:
                import psycopg2
                import psycopg2.extras
                self._conn = psycopg2.connect(self.url)
                self._conn.autocommit = False
        return self._conn

    def close(self):
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # -- schema --------------------------------------------------------
    def init_schema(self) -> None:
        ddl = render_schema(self.dialect)
        if self.dialect == "sqlite":
            self.conn.executescript(ddl)
            self.conn.commit()
        else:
            with self.conn.cursor() as cur:
                cur.execute(ddl)
            self.conn.commit()

    def reset(self) -> None:
        """Drop and recreate every table (test fixture helper)."""
        if self.dialect == "sqlite":
            self.conn.executescript(
                "PRAGMA foreign_keys = OFF;"
                "DROP TABLE IF EXISTS api_tokens; DROP TABLE IF EXISTS approvals;"
                "DROP TABLE IF EXISTS agent_runs;"
                "DROP TABLE IF EXISTS audit_log; DROP TABLE IF EXISTS assortment;"
                "DROP TABLE IF EXISTS reviews; DROP TABLE IF EXISTS stock;"
                "DROP TABLE IF EXISTS purchase_intel; DROP TABLE IF EXISTS order_lines;"
                "DROP TABLE IF EXISTS orders; DROP TABLE IF EXISTS schools;"
                "DROP TABLE IF EXISTS shipping_tariffs; DROP TABLE IF EXISTS shipping_rules;"
                "DROP TABLE IF EXISTS ean_registry; DROP TABLE IF EXISTS products;"
                "DROP TABLE IF EXISTS bundles; DROP TABLE IF EXISTS components;"
                "PRAGMA foreign_keys = ON;")
            self.conn.commit()
        else:
            self.conn.rollback()
            with self.conn.cursor() as cur:
                cur.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
            self.conn.commit()
        self.init_schema()

    # -- dialect adaptation ---------------------------------------------
    def bool_columns(self, table: str) -> set[str]:
        """Names of the boolean columns of ``table`` on this backend.

        SQLite has no boolean type -- it stores 0/1 in an INTEGER column --
        while PostgreSQL has a real boolean type and refuses an integer
        parameter for it.  Rather than making every caller dialect-aware,
        the layer introspects the table once and coerces the values.
        """
        if self.dialect != "postgresql":
            return set()
        if table not in self._bool_columns:
            import psycopg2.extras
            cur = self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name=%s "
                "AND data_type='boolean'", (table,))
            self._bool_columns[table] = {r["column_name"] for r in cur.fetchall()}
        return self._bool_columns[table]

    def _all_bool_columns(self) -> set[str]:
        """Every boolean column name in the database.

        Queried directly through the driver rather than through ``query()``,
        because ``query()`` is what consults this method.
        """
        if self.dialect != "postgresql":
            return set()
        if not hasattr(self, "_all_bool_cache"):
            import psycopg2.extras
            cur = self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='public' AND data_type='boolean'")
            self._all_bool_cache = {r["column_name"] for r in cur.fetchall()}
        return self._all_bool_cache

    def _adapt_sql(self, sql: str) -> str:
        """Apply backend-specific rewrites to a statement."""
        if self.dialect != "postgresql":
            return sql
        return rewrite_bool_literals(sql, self._all_bool_columns())

    def _coerce(self, sql: str, params: Sequence[Any] | None):
        """Convert 0/1 to False/True for the boolean columns an INSERT targets."""
        if self.dialect != "postgresql" or not params:
            return params
        table, cols = _insert_columns(sql)
        if not table:
            return params
        bools = self.bool_columns(table)
        if not bools:
            return params
        out = list(params)
        for idx, col in enumerate(cols):
            if col in bools and idx < len(out) and isinstance(out[idx], int):
                out[idx] = bool(out[idx])
        return tuple(out)

    # -- query helpers -------------------------------------------------
    def execute(self, sql: str, params: Sequence[Any] | None = None) -> int:
        with self._lock:
            cur = self.conn.cursor()
            cur.execute(to_dialect(self._adapt_sql(sql), self.dialect),
                        self._coerce(sql, params or ()))
            self.conn.commit()
            return cur.rowcount

    def executemany(self, sql: str, rows: Iterable[Sequence[Any]]) -> int:
        rows = list(rows)
        if not rows:
            return 0
        with self._lock:
            cur = self.conn.cursor()
            coerced = [self._coerce(sql, row) for row in rows]
            cur.executemany(to_dialect(self._adapt_sql(sql), self.dialect), coerced)
            self.conn.commit()
            return cur.rowcount

    def query(self, sql: str, params: Sequence[Any] | None = None) -> list[dict]:
        with self._lock:
            cur = self.conn.cursor()
            if self.dialect == "sqlite":
                cur.execute(sql, params or ())
                rows = [dict(r) for r in cur.fetchall()]
            else:
                # RealDictCursor gives every row the same column-name mapping as
                # sqlite3.Row, so callers never branch on the backend.
                import psycopg2.extras
                cur = self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                cur.execute(to_dialect(self._adapt_sql(sql), self.dialect),
                            params or ())
                rows = [dict(r) for r in cur.fetchall()]
            return rows

    def query_one(self, sql: str, params: Sequence[Any] | None = None) -> dict | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def scalar(self, sql: str, params: Sequence[Any] | None = None) -> Any:
        row = self.query_one(sql, params)
        if not row:
            return None
        return list(row.values())[0]

    @contextmanager
    def transaction(self) -> Iterator["Database"]:
        with self._lock:
            try:
                yield self
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise

    # -- portable JSON columns ----------------------------------------
    @staticmethod
    def dumps(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False)

    @staticmethod
    def loads(value: Any) -> Any:
        if value in (None, ""):
            return None
        if isinstance(value, (dict, list)):
            return value
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return None