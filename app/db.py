import datetime as dt
import hashlib
from dataclasses import dataclass

from typing import Any

import aiosqlite

from .template import default_approval_message_settings, settings_to_json


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


@dataclass(frozen=True)
class RequestRow:
    id: int
    tg_id: int
    node_id: str
    status: str
    created_at: str
    decided_at: str | None
    decided_by: int | None
    decided_via: str | None


@dataclass(frozen=True)
class UserRow:
    tg_id: int
    username: str | None
    first_name: str | None
    last_name: str | None
    email: str | None
    created_at: str
    updated_at: str
    is_active: bool
    deactivated_at: str | None
    node_id: str | None


class DB:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    async def init(self) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                  tg_id INTEGER PRIMARY KEY,
                  username TEXT,
                  first_name TEXT,
                  last_name TEXT,
                  email TEXT,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  is_active INTEGER NOT NULL DEFAULT 1,
                  deactivated_at TEXT,
                  node_id TEXT
                );
                """
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS requests (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  tg_id INTEGER NOT NULL,
                  node_id TEXT NOT NULL,
                  status TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  decided_at TEXT,
                  decided_by INTEGER,
                  decided_via TEXT
                );
                """
            )

            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS settings (
                  key TEXT PRIMARY KEY,
                  value TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  updated_by INTEGER
                );
                """
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS settings_history (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  key TEXT NOT NULL,
                  value TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  created_by INTEGER,
                  action TEXT NOT NULL
                );
                """
            )
            await db.execute("CREATE INDEX IF NOT EXISTS idx_settings_history_key ON settings_history(key);")

            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS admin_sessions (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  token_hash TEXT NOT NULL UNIQUE,
                  created_at TEXT NOT NULL,
                  last_seen_at TEXT NOT NULL,
                  expires_at TEXT NOT NULL,
                  ip TEXT,
                  user_agent TEXT,
                  revoked_at TEXT
                );
                """
            )
            await db.execute("CREATE INDEX IF NOT EXISTS idx_admin_sessions_token_hash ON admin_sessions(token_hash);")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_admin_sessions_revoked_at ON admin_sessions(revoked_at);")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_admin_sessions_expires_at ON admin_sessions(expires_at);")

            users_cols = await self._table_cols(db, "users")
            if users_cols and "created_at" not in users_cols:
                await self._migrate_users_v1_to_v2(db)

            req_cols = await self._table_cols(db, "requests")
            if req_cols and "decided_via" not in req_cols:
                await db.execute("ALTER TABLE requests ADD COLUMN decided_via TEXT")

            await db.execute("CREATE INDEX IF NOT EXISTS idx_users_updated_at ON users(updated_at);")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_users_is_active ON users(is_active);")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_requests_status ON requests(status);")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_requests_tg_id ON requests(tg_id);")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_requests_created_at ON requests(created_at);")
            await db.commit()

        existing = await self.get_setting("approval_message")
        if existing is None:
            s = default_approval_message_settings()
            await self.set_setting("approval_message", settings_to_json(s), updated_by=None, action="seed")

    async def get_setting(self, key: str) -> str | None:
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute("SELECT value FROM settings WHERE key = ?", (key,))
            row = await cur.fetchone()
            return str(row[0]) if row else None

    async def set_setting(self, key: str, value: str, updated_by: int | None, action: str) -> None:
        now = _now_iso()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO settings_history(key, value, created_at, created_by, action) VALUES(?, ?, ?, ?, ?)",
                (key, value, now, updated_by, action),
            )
            await db.execute(
                "INSERT INTO settings(key, value, updated_at, updated_by) VALUES(?, ?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at, updated_by = excluded.updated_by",
                (key, value, now, updated_by),
            )
            await db.commit()

    async def list_setting_history(self, key: str, limit: int = 50) -> list[tuple[int, str, int | None, str, str]]:
        limit = min(max(int(limit), 1), 200)
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                "SELECT id, created_at, created_by, action, value FROM settings_history WHERE key = ? ORDER BY id DESC LIMIT ?",
                (key, limit),
            )
            rows = await cur.fetchall()
            return [(int(r[0]), str(r[1]), int(r[2]) if r[2] is not None else None, str(r[3]), str(r[4])) for r in rows]

    async def get_setting_history_value(self, history_id: int) -> tuple[str, str] | None:
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute("SELECT key, value FROM settings_history WHERE id = ?", (history_id,))
            row = await cur.fetchone()
            if not row:
                return None
            return str(row[0]), str(row[1])

    def hash_session_token(self, token: str) -> str:
        return hashlib.sha256((token or "").encode("utf-8")).hexdigest()

    async def create_admin_session(self, token_hash: str, created_at: str, expires_at: str, ip: str | None, user_agent: str | None) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                "INSERT INTO admin_sessions(token_hash, created_at, last_seen_at, expires_at, ip, user_agent) VALUES(?, ?, ?, ?, ?, ?)",
                (token_hash, created_at, created_at, expires_at, ip, user_agent),
            )
            await db.commit()
            return int(cur.lastrowid)

    async def get_admin_session(self, token_hash: str) -> dict[str, Any] | None:
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                "SELECT id, token_hash, created_at, last_seen_at, expires_at, ip, user_agent, revoked_at FROM admin_sessions WHERE token_hash = ?",
                (token_hash,),
            )
            row = await cur.fetchone()
            if not row:
                return None
            return {
                "id": int(row[0]),
                "token_hash": str(row[1]),
                "created_at": str(row[2]),
                "last_seen_at": str(row[3]),
                "expires_at": str(row[4]),
                "ip": str(row[5]) if row[5] is not None else None,
                "user_agent": str(row[6]) if row[6] is not None else None,
                "revoked_at": str(row[7]) if row[7] is not None else None,
            }

    async def touch_admin_session(self, session_id: int, last_seen_at: str) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE admin_sessions SET last_seen_at = ? WHERE id = ? AND revoked_at IS NULL",
                (last_seen_at, session_id),
            )
            await db.commit()

    async def revoke_admin_session(self, session_id: int, revoked_at: str) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("UPDATE admin_sessions SET revoked_at = ? WHERE id = ?", (revoked_at, session_id))
            await db.commit()

    async def revoke_admin_session_by_hash(self, token_hash: str, revoked_at: str) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("UPDATE admin_sessions SET revoked_at = ? WHERE token_hash = ?", (revoked_at, token_hash))
            await db.commit()

    async def list_admin_sessions(self, limit: int = 100) -> list[dict[str, Any]]:
        limit = min(max(int(limit), 1), 500)
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                "SELECT id, created_at, last_seen_at, expires_at, ip, user_agent, revoked_at FROM admin_sessions ORDER BY id DESC LIMIT ?",
                (limit,),
            )
            rows = await cur.fetchall()
            out: list[dict[str, Any]] = []
            for r in rows:
                out.append(
                    {
                        "id": int(r[0]),
                        "created_at": str(r[1]),
                        "last_seen_at": str(r[2]),
                        "expires_at": str(r[3]),
                        "ip": str(r[4]) if r[4] is not None else None,
                        "user_agent": str(r[5]) if r[5] is not None else None,
                        "revoked_at": str(r[6]) if r[6] is not None else None,
                    }
                )
            return out

    async def revoke_other_admin_sessions(self, current_session_id: int, revoked_at: str) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                "UPDATE admin_sessions SET revoked_at = ? WHERE id != ? AND revoked_at IS NULL",
                (revoked_at, current_session_id),
            )
            await db.commit()
            return int(cur.rowcount or 0)

    async def _table_cols(self, db: aiosqlite.Connection, table: str) -> set[str]:
        cur = await db.execute(f"PRAGMA table_info({table})")
        rows = await cur.fetchall()
        return {str(r[1]) for r in rows}

    async def _migrate_users_v1_to_v2(self, db: aiosqlite.Connection) -> None:
        await db.execute("ALTER TABLE users RENAME TO users_old")
        await db.execute(
            """
            CREATE TABLE users (
              tg_id INTEGER PRIMARY KEY,
              username TEXT,
              first_name TEXT,
              last_name TEXT,
              email TEXT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              is_active INTEGER NOT NULL DEFAULT 1,
              deactivated_at TEXT,
              node_id TEXT
            );
            """
        )
        await db.execute(
            """
            INSERT INTO users(tg_id, username, first_name, last_name, email, created_at, updated_at, is_active, deactivated_at, node_id)
            SELECT tg_id, NULL, NULL, NULL, NULL, updated_at, updated_at, 1, NULL, node_id FROM users_old
            """
        )
        await db.execute("DROP TABLE users_old")

    async def create_request(self, tg_id: int, node_id: str) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                "SELECT id FROM requests WHERE tg_id = ? AND node_id = ? AND status = 'pending' LIMIT 1",
                (tg_id, node_id),
            )
            row = await cur.fetchone()
            if row:
                return int(row[0])
            cur2 = await db.execute(
                "INSERT INTO requests(tg_id, node_id, status, created_at) VALUES(?, ?, 'pending', ?)",
                (tg_id, node_id, _now_iso()),
            )
            await db.commit()
            return int(cur2.lastrowid)

    async def upsert_user_profile(
        self,
        tg_id: int,
        username: str | None,
        first_name: str | None,
        last_name: str | None,
        email: str | None = None,
    ) -> None:
        now = _now_iso()
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute("SELECT tg_id FROM users WHERE tg_id = ?", (tg_id,))
            row = await cur.fetchone()
            if row:
                await db.execute(
                    """
                    UPDATE users
                    SET username = ?, first_name = ?, last_name = ?, email = COALESCE(?, email), updated_at = ?
                    WHERE tg_id = ?
                    """,
                    (username, first_name, last_name, email, now, tg_id),
                )
            else:
                await db.execute(
                    """
                    INSERT INTO users(tg_id, username, first_name, last_name, email, created_at, updated_at, is_active)
                    VALUES(?, ?, ?, ?, ?, ?, ?, 1)
                    """,
                    (tg_id, username, first_name, last_name, email, now, now),
                )
            await db.commit()

    async def get_request(self, request_id: int) -> RequestRow | None:
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                "SELECT id, tg_id, node_id, status, created_at, decided_at, decided_by, decided_via FROM requests WHERE id = ?",
                (request_id,),
            )
            row = await cur.fetchone()
            if not row:
                return None
            return RequestRow(
                id=int(row[0]),
                tg_id=int(row[1]),
                node_id=str(row[2]),
                status=str(row[3]),
                created_at=str(row[4]),
                decided_at=row[5],
                decided_by=int(row[6]) if row[6] is not None else None,
                decided_via=str(row[7]) if row[7] is not None else None,
            )

    async def decide_request(self, request_id: int, status: str, decided_by: int, decided_via: str | None = None) -> bool:
        if status not in ("approved", "denied"):
            raise ValueError("invalid status")

        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute("SELECT tg_id, node_id, status FROM requests WHERE id = ?", (request_id,))
            row = await cur.fetchone()
            if not row:
                return False
            if row[2] != "pending":
                return False

            await db.execute(
                "UPDATE requests SET status = ?, decided_at = ?, decided_by = ?, decided_via = ? WHERE id = ?",
                (status, _now_iso(), decided_by, decided_via, request_id),
            )
            if status == "approved":
                tg_id = int(row[0])
                node_id = str(row[1])
                curu = await db.execute("SELECT tg_id FROM users WHERE tg_id = ?", (tg_id,))
                uru = await curu.fetchone()
                if not uru:
                    now = _now_iso()
                    await db.execute(
                        """
                        INSERT INTO users(tg_id, username, first_name, last_name, email, created_at, updated_at, is_active, node_id)
                        VALUES(?, NULL, NULL, NULL, NULL, ?, ?, 1, ?)
                        """,
                        (tg_id, now, now, node_id),
                    )
                await db.execute(
                    """
                    UPDATE users
                    SET node_id = ?, updated_at = ?, is_active = 1, deactivated_at = NULL
                    WHERE tg_id = ?
                    """,
                    (node_id, _now_iso(), tg_id),
                )
            await db.commit()
            return True

    async def deactivate_user(self, tg_id: int) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                "UPDATE users SET is_active = 0, deactivated_at = ?, updated_at = ? WHERE tg_id = ?",
                (_now_iso(), _now_iso(), tg_id),
            )
            await db.commit()
            return cur.rowcount > 0

    async def bulk_deactivate_users(self, tg_ids: list[int]) -> int:
        tg_ids = [int(x) for x in tg_ids if int(x) > 0]
        if not tg_ids:
            return 0
        placeholders = ",".join(["?"] * len(tg_ids))
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                f"UPDATE users SET is_active = 0, deactivated_at = ?, updated_at = ? WHERE tg_id IN ({placeholders})",
                (_now_iso(), _now_iso(), *tg_ids),
            )
            await db.commit()
            return int(cur.rowcount or 0)

    async def get_user(self, tg_id: int) -> UserRow | None:
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                """
                SELECT tg_id, username, first_name, last_name, email, created_at, updated_at, is_active, deactivated_at, node_id
                FROM users
                WHERE tg_id = ?
                """,
                (tg_id,),
            )
            r = await cur.fetchone()
            if not r:
                return None
            return UserRow(
                tg_id=int(r[0]),
                username=str(r[1]) if r[1] is not None else None,
                first_name=str(r[2]) if r[2] is not None else None,
                last_name=str(r[3]) if r[3] is not None else None,
                email=str(r[4]) if r[4] is not None else None,
                created_at=str(r[5]),
                updated_at=str(r[6]),
                is_active=bool(int(r[7])),
                deactivated_at=str(r[8]) if r[8] is not None else None,
                node_id=str(r[9]) if r[9] is not None else None,
            )

    async def list_users_paginated(
        self,
        q: str | None,
        page: int,
        page_size: int,
        sort: str,
        order: str,
    ) -> tuple[list[UserRow], int]:
        page = max(int(page), 1)
        page_size = min(max(int(page_size), 1), 200)
        sort_map = {
            "tg_id": "tg_id",
            "username": "username",
            "created_at": "created_at",
            "updated_at": "updated_at",
            "is_active": "is_active",
            "node_id": "node_id",
        }
        sort_sql = sort_map.get(sort, "updated_at")
        order_sql = "ASC" if str(order).lower() == "asc" else "DESC"
        where = ""
        args: list[Any] = []
        if q:
            qn = f"%{q.strip()}%"
            where = "WHERE CAST(tg_id AS TEXT) LIKE ? OR COALESCE(username,'') LIKE ? OR COALESCE(first_name,'') LIKE ? OR COALESCE(last_name,'') LIKE ? OR COALESCE(email,'') LIKE ? OR COALESCE(node_id,'') LIKE ?"
            args.extend([qn, qn, qn, qn, qn, qn])

        offset = (page - 1) * page_size
        async with aiosqlite.connect(self.db_path) as db:
            cur_total = await db.execute(f"SELECT COUNT(1) FROM users {where}", args)
            total_row = await cur_total.fetchone()
            total = int(total_row[0]) if total_row else 0
            cur = await db.execute(
                f"""
                SELECT tg_id, username, first_name, last_name, email, created_at, updated_at, is_active, deactivated_at, node_id
                FROM users
                {where}
                ORDER BY {sort_sql} {order_sql}
                LIMIT ? OFFSET ?
                """,
                (*args, page_size, offset),
            )
            rows = await cur.fetchall()
            out: list[UserRow] = []
            for r in rows:
                out.append(
                    UserRow(
                        tg_id=int(r[0]),
                        username=str(r[1]) if r[1] is not None else None,
                        first_name=str(r[2]) if r[2] is not None else None,
                        last_name=str(r[3]) if r[3] is not None else None,
                        email=str(r[4]) if r[4] is not None else None,
                        created_at=str(r[5]),
                        updated_at=str(r[6]),
                        is_active=bool(int(r[7])),
                        deactivated_at=str(r[8]) if r[8] is not None else None,
                        node_id=str(r[9]) if r[9] is not None else None,
                    )
                )
            return out, total

    async def list_requests_paginated(
        self,
        q: str | None,
        status: str | None,
        page: int,
        page_size: int,
        sort: str,
        order: str,
        tg_id: int | None = None,
    ) -> tuple[list[RequestRow], int]:
        page = max(int(page), 1)
        page_size = min(max(int(page_size), 1), 200)
        sort_map = {"id": "id", "created_at": "created_at", "status": "status", "tg_id": "tg_id"}
        sort_sql = sort_map.get(sort, "id")
        order_sql = "ASC" if str(order).lower() == "asc" else "DESC"

        wheres: list[str] = []
        args: list[Any] = []
        if status:
            wheres.append("status = ?")
            args.append(status)
        if tg_id is not None:
            wheres.append("tg_id = ?")
            args.append(int(tg_id))
        if q:
            qn = f"%{q.strip()}%"
            wheres.append("CAST(id AS TEXT) LIKE ? OR CAST(tg_id AS TEXT) LIKE ? OR node_id LIKE ?")
            args.extend([qn, qn, qn])
        where = "WHERE " + " AND ".join(wheres) if wheres else ""

        offset = (page - 1) * page_size
        async with aiosqlite.connect(self.db_path) as db:
            cur_total = await db.execute(f"SELECT COUNT(1) FROM requests {where}", args)
            total_row = await cur_total.fetchone()
            total = int(total_row[0]) if total_row else 0
            cur = await db.execute(
                f"""
                SELECT id, tg_id, node_id, status, created_at, decided_at, decided_by, decided_via
                FROM requests
                {where}
                ORDER BY {sort_sql} {order_sql}
                LIMIT ? OFFSET ?
                """,
                (*args, page_size, offset),
            )
            rows = await cur.fetchall()
            out: list[RequestRow] = []
            for r in rows:
                out.append(
                    RequestRow(
                        id=int(r[0]),
                        tg_id=int(r[1]),
                        node_id=str(r[2]),
                        status=str(r[3]),
                        created_at=str(r[4]),
                        decided_at=str(r[5]) if r[5] is not None else None,
                        decided_by=int(r[6]) if r[6] is not None else None,
                        decided_via=str(r[7]) if r[7] is not None else None,
                    )
                )
            return out, total

