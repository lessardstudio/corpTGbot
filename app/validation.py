import re


_NODE_ID_RE = re.compile(r"^[0-9a-fA-F]{10}$")


def is_valid_node_id(node_id: str) -> bool:
    return bool(_NODE_ID_RE.fullmatch(node_id.strip()))

