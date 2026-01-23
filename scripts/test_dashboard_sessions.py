import asyncio
import os
import sys
import tempfile
import datetime as dt

from aiohttp.test_utils import TestClient, TestServer
import aiosqlite

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.dashboard import create_dashboard_app
from app.db import DB


class DummyBot:
    async def send_message(self, chat_id: int, text: str, **kwargs):
        return None


async def main() -> None:
    tmp = tempfile.NamedTemporaryFile(delete=False)
    tmp.close()
    db = DB(tmp.name)
    await db.init()

    app = create_dashboard_app(
        db=db,
        password="pw",
        bot=DummyBot(),
        admin_chat_id=1,
        bot_username="bot",
        network_id="net",
        session_max_age_seconds=60,
        session_idle_seconds=1,
    )

    server = TestServer(app)
    await server.start_server()
    client = TestClient(server)
    await client.start_server()
    try:
        r = await client.get("/admin", allow_redirects=False)
        assert r.status == 302
        assert r.headers["Location"].startswith("/admin/login")

        r2 = await client.get("/admin/login")
        assert r2.status == 200

        r3 = await client.post("/admin/login", data={"password": "pw", "next": "/admin/settings"}, allow_redirects=False)
        assert r3.status == 302
        assert r3.headers["Location"] == "/admin/settings"

        r4 = await client.get("/api/admin/settings/approval_message")
        assert r4.status == 200

        items = await db.list_admin_sessions(limit=1)
        sid = int(items[0]["id"])
        old = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=120)).isoformat()
        async with aiosqlite.connect(tmp.name) as conn:
            await conn.execute("UPDATE admin_sessions SET last_seen_at = ? WHERE id = ?", (old, sid))
            await conn.commit()

        async with aiosqlite.connect(tmp.name) as conn:
            cur = await conn.execute("SELECT last_seen_at FROM admin_sessions WHERE id = ?", (sid,))
            row = await cur.fetchone()
            assert row and str(row[0]) == old

        r5 = await client.get("/api/admin/settings/approval_message")
        assert r5.status == 401
    finally:
        await client.close()
        await server.close()


if __name__ == "__main__":
    asyncio.run(main())
