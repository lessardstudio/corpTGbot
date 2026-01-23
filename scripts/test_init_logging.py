import asyncio
import os
import sys
import tempfile
import logging


def _set_env_for_failure(log_path: str) -> None:
    os.environ.pop("TG_TOKEN", None)
    os.environ["TG_ADMIN_CHAT_ID"] = "123"
    os.environ["TG_INSTRUCTION_ARTICLE_URL"] = "https://example.com"
    os.environ["TG_DASHBOARD_PASSWORD"] = "pw"
    os.environ["ZT_NETWORK_ID"] = "8185934e6af6ceb3"
    os.environ["TG_WEB_PAGE_URL_1"] = "https://joinzt.example/"
    os.environ["TG_WEB_PAGE_URL_2"] = "https://joinzt.example/"
    os.environ["TG_BOT_USERNAME"] = "bot"
    os.environ["TG_DB_PATH"] = os.path.join(os.path.dirname(log_path), "test.db")
    os.environ["TG_LOG_PATH"] = log_path


async def main() -> None:
    with tempfile.TemporaryDirectory() as td:
        log_path = os.path.join(td, "app.log")
        _set_env_for_failure(log_path)

        sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
        from app.main import main_async

        try:
            await main_async()
        except RuntimeError:
            pass

        with open(log_path, "r", encoding="utf-8") as f:
            text = f.read()

        assert "init_start" in text
        assert "init_failed" in text
        assert "run_id=" in text

        logging.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
