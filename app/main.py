import asyncio
import logging

from aiohttp import web

from .bot import create_dispatcher
from .dashboard import create_dashboard_app
from .db import DB
from .logging_setup import setup_logging
from .settings import get_settings


log = logging.getLogger("main")


async def _run_dashboard(app: web.Application, port: int) -> None:
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=port)
    await site.start()
    log.info("dashboard_started port=%s", port)
    await asyncio.Event().wait()


async def main_async() -> None:
    s = get_settings()
    setup_logging(s.log_path)

    db = DB(s.db_path)
    await db.init()

    bot, dp = await create_dispatcher(s, db)
    dashboard_app = create_dashboard_app(db, s.dashboard_password, bot, s.admin_chat_id, s.bot_username, s.zt_network_id)

    bot_task = asyncio.create_task(dp.start_polling(bot))
    dash_task = asyncio.create_task(_run_dashboard(dashboard_app, s.dashboard_listen_port))

    done, pending = await asyncio.wait({bot_task, dash_task}, return_when=asyncio.FIRST_EXCEPTION)
    for t in done:
        exc = t.exception()
        if exc:
            raise exc
    for t in pending:
        t.cancel()


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()

