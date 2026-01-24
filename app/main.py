import asyncio
import os
import platform
import ssl
import time
import uuid
import logging

from aiohttp import web

from .bot import create_dispatcher
from .dashboard import create_dashboard_app
from .db import DB
from .logging_setup import setup_bootstrap_logging, setup_logging
from .settings import get_settings
from .zt_monitor import zt_monitor_loop


log = logging.getLogger("main")


async def _run_dashboard(app: web.Application, port: int, use_ssl: bool = False, cert_path: str = None, key_path: str = None) -> None:
    runner = web.AppRunner(app)
    await runner.setup()
    
    ssl_context = None
    if use_ssl and cert_path and key_path:
        ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        ssl_context.load_cert_chain(cert_path, key_path)
    
    site = web.TCPSite(runner, host="0.0.0.0", port=port, ssl_context=ssl_context)
    await site.start()
    log.info("dashboard_started port=%s ssl=%s", port, bool(ssl_context))
    await asyncio.Event().wait()

async def main_async() -> None:
    run_id = uuid.uuid4().hex
    setup_bootstrap_logging(run_id)
    started = time.perf_counter()
    log.info(
        "init_start python=%s platform=%s pid=%s",
        platform.python_version(),
        platform.platform(),
        os.getpid(),
    )

    try:
        t0 = time.perf_counter()
        s = get_settings()
        log.info("init_config_loaded ms=%d dashboard_port=%s db_path=%s", int((time.perf_counter() - t0) * 1000), s.dashboard_listen_port, s.db_path)

        setup_logging(s.log_path, run_id)
        log.info("init_logging_configured log_path=%s", s.log_path)

        t1 = time.perf_counter()
        db = DB(s.db_path)
        await db.init()
        log.info("init_db_ready ms=%d", int((time.perf_counter() - t1) * 1000))

        t2 = time.perf_counter()
        bot, dp = await create_dispatcher(s, db)
        log.info("init_bot_ready ms=%d bot_username=%s admin_chat_id=%s", int((time.perf_counter() - t2) * 1000), s.bot_username, s.admin_chat_id)

        t3 = time.perf_counter()
        dashboard_app = create_dashboard_app(
            db,
            s.dashboard_password,
            bot,
            s.admin_chat_id,
            s.bot_username,
            s.zt_network_id,
            s.admin_session_max_age_seconds,
            s.admin_session_idle_seconds,
        )
        log.info(
            "init_dashboard_ready ms=%d listen_port=%s session_max_age_s=%s session_idle_s=%s",
            int((time.perf_counter() - t3) * 1000),
            s.dashboard_listen_port,
            s.admin_session_max_age_seconds,
            s.admin_session_idle_seconds,
        )

        log.info("init_done ms=%d", int((time.perf_counter() - started) * 1000))

        zt_task = asyncio.create_task(zt_monitor_loop(s.zt_network_id))

        bot_task = asyncio.create_task(dp.start_polling(bot))
        dash_task = asyncio.create_task(_run_dashboard(
            dashboard_app, 
            s.dashboard_listen_port,
            use_ssl=True,  # или False для HTTP
            cert_path="/app/certs/cert.pem",
            key_path="/app/certs/key.pem"
        ))

        done, pending = await asyncio.wait({bot_task, dash_task, zt_task}, return_when=asyncio.FIRST_EXCEPTION)
        for t in done:
            exc = t.exception()
            if exc:
                raise exc
        for t in pending:
            t.cancel()
    except Exception:
        log.exception("init_failed ms=%d", int((time.perf_counter() - started) * 1000))
        raise


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()

