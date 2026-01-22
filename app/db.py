import datetime as dt
from dataclasses import dataclass

import aiosqlite


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


class DB:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    async def init(self) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                  tg_id INTEGER PRIMARY KEY,
                  node_id TEXT NOT NULL,
                  updated_at TEXT NOT NULL
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
                  decided_by INTEGER
                );
                """
            )
            await db.execute("CREATE INDEX IF NOT EXISTS idx_requests_status ON requests(status);")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_requests_tg_id ON requests(tg_id);")
            await db.commit()

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

    async def get_request(self, request_id: int) -> RequestRow | None:
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                "SELECT id, tg_id, node_id, status, created_at, decided_at, decided_by FROM requests WHERE id = ?",
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
            )

    async def decide_request(self, request_id: int, status: str, decided_by: int) -> bool:
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
                "UPDATE requests SET status = ?, decided_at = ?, decided_by = ? WHERE id = ?",
                (status, _now_iso(), decided_by, request_id),
            )
            if status == "approved":
                tg_id = int(row[0])
                node_id = str(row[1])
                await db.execute(
                    "INSERT INTO users(tg_id, node_id, updated_at) VALUES(?, ?, ?) "
                    "ON CONFLICT(tg_id) DO UPDATE SET node_id = excluded.node_id, updated_at = excluded.updated_at",
                    (tg_id, node_id, _now_iso()),
                )
            await db.commit()
            return True

    async def list_users(self) -> list[tuple[int, str, str]]:
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                "SELECT tg_id, node_id, updated_at FROM users ORDER BY updated_at DESC LIMIT 500"
            )
            rows = await cur.fetchall()
            return [(int(r[0]), str(r[1]), str(r[2])) for r in rows]

    async def list_recent_requests(self) -> list[RequestRow]:
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                "SELECT id, tg_id, node_id, status, created_at, decided_at, decided_by FROM requests ORDER BY id DESC LIMIT 200"
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
                        decided_at=r[5],
                        decided_by=int(r[6]) if r[6] is not None else None,
                    )
                )
            return out

