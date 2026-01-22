import re


_NODE_ID_RE = re.compile(r"^[0-9a-fA-F]{10}$")
_ALLOWED_TEMPLATE_VARS = {
    "client_name",
    "request_id",
    "node_id",
    "tg_id",
    "username",
    "bot_username",
    "network_id",
}
_TEMPLATE_VAR_RE = re.compile(r"\{([a-zA-Z0-9_]+)\}")


def is_valid_node_id(node_id: str) -> bool:
    return bool(_NODE_ID_RE.fullmatch(node_id.strip()))


def validate_template_vars(template: str) -> tuple[bool, list[str]]:
    vars_found = {m.group(1) for m in _TEMPLATE_VAR_RE.finditer(template or "")}
    unknown = sorted([v for v in vars_found if v not in _ALLOWED_TEMPLATE_VARS])
    return (len(unknown) == 0), unknown


def allowed_template_vars() -> list[str]:
    return sorted(_ALLOWED_TEMPLATE_VARS)

