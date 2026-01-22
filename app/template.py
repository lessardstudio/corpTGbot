import json
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any


@dataclass(frozen=True)
class ApprovalMessageSettings:
    template_html: str
    fallbacks: dict[str, str]


class _TelegramHTMLSanitizer(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.allowed_tags = {
            "b",
            "strong",
            "i",
            "em",
            "u",
            "s",
            "strike",
            "del",
            "code",
            "pre",
            "a",
            "br",
        }
        self.tag_stack: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag not in self.allowed_tags:
            return
        if tag == "br":
            self.out.append("<br>")
            return
        if tag == "a":
            href = None
            for k, v in attrs:
                if k.lower() == "href" and v:
                    href = v.strip()
            if not href:
                return
            safe_href = href.replace("\"", "&quot;")
            self.out.append(f'<a href="{safe_href}">')
            self.tag_stack.append("a")
            return
        self.out.append(f"<{tag}>")
        self.tag_stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag not in self.allowed_tags or tag == "br":
            return
        for i in range(len(self.tag_stack) - 1, -1, -1):
            if self.tag_stack[i] == tag:
                while len(self.tag_stack) > i:
                    t = self.tag_stack.pop()
                    self.out.append(f"</{t}>")
                return

    def handle_data(self, data: str) -> None:
        self.out.append(
            (data or "")
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )

    def get_html(self) -> str:
        while self.tag_stack:
            t = self.tag_stack.pop()
            self.out.append(f"</{t}>")
        return "".join(self.out).strip()


_VAR_RE = re.compile(r"\{([a-zA-Z0-9_]+)\}")


def sanitize_telegram_html(html: str) -> str:
    p = _TelegramHTMLSanitizer()
    p.feed(html or "")
    return p.get_html()


def render_template_html(template_html: str, variables: dict[str, Any], fallbacks: dict[str, str] | None = None) -> str:
    fallbacks = fallbacks or {}

    def repl(m: re.Match[str]) -> str:
        key = m.group(1)
        v = variables.get(key)
        if v is None or v == "":
            v = fallbacks.get(key, "")
        s = str(v)
        s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        return s

    rendered = _VAR_RE.sub(repl, template_html or "")
    return sanitize_telegram_html(rendered)


def default_approval_message_settings() -> ApprovalMessageSettings:
    template_html = (
        "<b>Заявка #{request_id} подтверждена</b><br>"
        "node_id: <code>{node_id}</code><br>"
        "Если у вас возникли вопросы — напишите администратору."
    )
    return ApprovalMessageSettings(template_html=template_html, fallbacks={"client_name": ""})


def settings_to_json(s: ApprovalMessageSettings) -> str:
    return json.dumps({"template_html": s.template_html, "fallbacks": s.fallbacks}, ensure_ascii=False)


def settings_from_json(raw: str) -> ApprovalMessageSettings:
    try:
        obj = json.loads(raw or "{}")
    except Exception:
        obj = {}
    template_html = str(obj.get("template_html") or "")
    fallbacks = obj.get("fallbacks")
    if not isinstance(fallbacks, dict):
        fallbacks = {}
    fallbacks_str: dict[str, str] = {}
    for k, v in fallbacks.items():
        fallbacks_str[str(k)] = str(v) if v is not None else ""
    return ApprovalMessageSettings(template_html=template_html, fallbacks=fallbacks_str)

