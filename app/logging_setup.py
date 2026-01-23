import logging
from logging.handlers import RotatingFileHandler
import os
from typing import Any


class _RunIdFilter(logging.Filter):
    def __init__(self, run_id: str) -> None:
        super().__init__()
        self._run_id = run_id

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "run_id"):
            record.run_id = self._run_id
        return True


def setup_bootstrap_logging(run_id: str) -> None:
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for h in list(root.handlers):
        root.removeHandler(h)

    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s run_id=%(run_id)s %(message)s")

    sh = logging.StreamHandler()
    sh.addFilter(_RunIdFilter(run_id))
    sh.setFormatter(fmt)
    root.addHandler(sh)

    log_path = os.getenv("TG_LOG_PATH", "").strip()
    if log_path:
        d = os.path.dirname(log_path)
        if d:
            os.makedirs(d, exist_ok=True)
        fh = RotatingFileHandler(log_path, maxBytes=5_000_000, backupCount=5, encoding="utf-8")
        fh.addFilter(_RunIdFilter(run_id))
        fh.setFormatter(fmt)
        root.addHandler(fh)


def setup_logging(log_path: str, run_id: str) -> None:
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for h in list(root.handlers):
        root.removeHandler(h)

    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s run_id=%(run_id)s %(message)s")

    rf = _RunIdFilter(run_id)

    sh = logging.StreamHandler()
    sh.addFilter(rf)
    sh.setFormatter(fmt)
    root.addHandler(sh)

    d = os.path.dirname(log_path)
    if d:
        os.makedirs(d, exist_ok=True)

    fh = RotatingFileHandler(log_path, maxBytes=5_000_000, backupCount=5, encoding="utf-8")
    fh.addFilter(rf)
    fh.setFormatter(fmt)
    root.addHandler(fh)

