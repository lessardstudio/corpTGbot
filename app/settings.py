import os


class Settings:
    def __init__(self) -> None:
        self.tg_token = os.getenv("TG_TOKEN", "").strip()
        self.admin_chat_id = int(os.getenv("TG_ADMIN_CHAT_ID", "0").strip() or "0")
        self.instruction_article_url = os.getenv("TG_INSTRUCTION_ARTICLE_URL", "").strip()
        self.dashboard_password = os.getenv("TG_DASHBOARD_PASSWORD", "").strip()
        self.bot_username = os.getenv("TG_BOT_USERNAME", "").strip()
        self.zt_network_id = os.getenv("ZT_NETWORK_ID", "").strip()
        self.web_page_url_1 = os.getenv("TG_WEB_PAGE_URL_1", "").strip()
        self.web_page_url_2 = os.getenv("TG_WEB_PAGE_URL_2", "").strip()
        self.dashboard_port = int(os.getenv("TG_DASHBOARD_PORT", "8080").strip() or "8080")
        self.db_path = os.getenv("TG_DB_PATH", "/app/data/bot.db").strip()
        self.log_path = os.getenv("TG_LOG_PATH", "/app/logs/app.log").strip()


def get_settings() -> Settings:
    s = Settings()
    missing = []
    if not s.tg_token:
        missing.append("TG_TOKEN")
    if not s.admin_chat_id:
        missing.append("TG_ADMIN_CHAT_ID")
    if not s.instruction_article_url:
        missing.append("TG_INSTRUCTION_ARTICLE_URL")
    if not s.dashboard_password:
        missing.append("TG_DASHBOARD_PASSWORD")
    if not s.web_page_url_1:
        s.web_page_url_1 = f"https://joinzt.com/addnetwork?nwid={s.zt_network_id}&v=1" if s.zt_network_id else "https://joinzt.com/addnetwork?nwid=8185934e6af6ceb3&v=1"
    if not s.web_page_url_2:
        s.web_page_url_2 = s.web_page_url_1
    if missing:
        raise RuntimeError("Missing required env vars: " + ", ".join(missing))
    return s

