import base64
from typing import Any

from aiohttp import web

from .db import DB


def _is_authorized(request: web.Request, password: str) -> bool:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Basic "):
        return False
    raw = auth[len("Basic ") :].strip()
    try:
        decoded = base64.b64decode(raw).decode("utf-8")
    except Exception:
        return False
    if ":" not in decoded:
        return False
    username, pwd = decoded.split(":", 1)
    return username == "admin" and pwd == password


def _unauthorized() -> web.Response:
    return web.Response(
        status=401,
        headers={"WWW-Authenticate": 'Basic realm="tgbot"'},
        text="Unauthorized",
    )


def _html_page(title: str, body: str) -> str:
    return (
        "<!doctype html>"
        "<html><head><meta charset='utf-8'/>"
        f"<title>{title}</title>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'/>"
        "<style>body{font-family:system-ui,Segoe UI,Arial,sans-serif;padding:16px}table{border-collapse:collapse;width:100%}th,td{border:1px solid #ddd;padding:8px;text-align:left}th{background:#f5f5f5}code{background:#f6f8fa;padding:2px 4px;border-radius:4px}</style>"
        "</head><body>"
        f"<h1>{title}</h1>"
        "<p><a href='/admin'>Users</a> · <a href='/admin/requests'>Requests</a></p>"
        f"{body}"
        "</body></html>"
    )


def create_dashboard_app(db: DB, password: str) -> web.Application:
    app = web.Application()

    async def users_page(request: web.Request) -> web.Response:
        if not _is_authorized(request, password):
            return _unauthorized()
        users = await db.list_users()
        rows = "".join(
            f"<tr><td><code>{tg_id}</code></td><td><code>{node_id}</code></td><td>{updated_at}</td></tr>"
            for tg_id, node_id, updated_at in users
        )
        body = (
            "<p>Basic Auth: user <code>admin</code>, password из <code>TG_DASHBOARD_PASSWORD</code>.</p>"
            "<table><thead><tr><th>tg_id</th><th>node_id</th><th>updated_at</th></tr></thead>"
            f"<tbody>{rows}</tbody></table>"
        )
        return web.Response(text=_html_page("Users (node_id ↔ tg_id)", body), content_type="text/html")

    async def requests_page(request: web.Request) -> web.Response:
        if not _is_authorized(request, password):
            return _unauthorized()
        reqs = await db.list_recent_requests()
        rows = "".join(
            "<tr>"
            f"<td><code>{r.id}</code></td>"
            f"<td><code>{r.tg_id}</code></td>"
            f"<td><code>{r.node_id}</code></td>"
            f"<td>{r.status}</td>"
            f"<td>{r.created_at}</td>"
            f"<td>{r.decided_at or ''}</td>"
            f"<td>{r.decided_by or ''}</td>"
            "</tr>"
            for r in reqs
        )
        body = (
            "<table><thead><tr><th>id</th><th>tg_id</th><th>node_id</th><th>status</th><th>created_at</th><th>decided_at</th><th>decided_by</th></tr></thead>"
            f"<tbody>{rows}</tbody></table>"
        )
        return web.Response(text=_html_page("Requests", body), content_type="text/html")

    app.router.add_get("/admin", users_page)
    app.router.add_get("/admin/requests", requests_page)
    return app

