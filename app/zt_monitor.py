import asyncio
import json
import shutil
from dataclasses import dataclass
from typing import Any

import logging


log = logging.getLogger("ztnet")


@dataclass(frozen=True)
class ZtNetworkState:
    network_id: str
    status: str
    assigned_ips: tuple[str, ...]


def _map_status(status: str) -> str:
    s = (status or "").strip().upper()
    if s == "OK":
        return "подключение установлено"
    if s in {"ACCESS_DENIED", "AUTH_FAILED"}:
        return "ошибка аутентификации"
    if s in {"NOT_FOUND"}:
        return "сеть не найдена"
    if s in {"REQUESTING_CONFIGURATION"}:
        return "ожидание конфигурации"
    if s:
        return s.lower()
    return "неизвестно"


async def _run_cli_json(*args: str, timeout_s: float = 3.0) -> dict[str, Any] | list[Any] | None:
    if not shutil.which("zerotier-cli"):
        return None
    proc = await asyncio.create_subprocess_exec(
        "zerotier-cli",
        "-j",
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
    except TimeoutError:
        proc.kill()
        await proc.communicate()
        raise

    if proc.returncode != 0:
        raise RuntimeError((err or out or b"").decode("utf-8", errors="replace").strip() or "zerotier-cli failed")

    raw = (out or b"").decode("utf-8", errors="replace").strip()
    if not raw:
        return None
    return json.loads(raw)


async def _get_node_id() -> str | None:
    try:
        info = await _run_cli_json("info")
    except Exception as e:
        log.warning("zt_cli_info_failed error=%s", str(e))
        return None
    if not isinstance(info, dict):
        return None
    node_id = str(info.get("address") or "").strip()
    return node_id or None


async def _get_network_state(network_id: str) -> ZtNetworkState | None:
    if not network_id:
        return None
    try:
        nets = await _run_cli_json("listnetworks")
    except Exception as e:
        log.warning("zt_cli_listnetworks_failed network_id=%s error=%s", network_id, str(e))
        return None
    if not isinstance(nets, list):
        return None

    for n in nets:
        if not isinstance(n, dict):
            continue
        if str(n.get("nwid") or "") != network_id:
            continue
        status = str(n.get("status") or "").strip() or "unknown"
        ips = n.get("assignedAddresses")
        if isinstance(ips, list):
            assigned = tuple(str(x) for x in ips if x)
        else:
            assigned = ()
        return ZtNetworkState(network_id=network_id, status=status, assigned_ips=assigned)
    return ZtNetworkState(network_id=network_id, status="NOT_JOINED", assigned_ips=())


async def zt_monitor_loop(network_id: str, poll_interval_s: float = 10.0) -> None:
    if not network_id:
        log.info("zt_monitor_disabled reason=missing_network_id")
        return

    node_id: str | None = None
    last_state: ZtNetworkState | None = None
    fail_count = 0

    log.info("zt_monitor_start network_id=%s", network_id)
    while True:
        try:
            node_id = node_id or await _get_node_id()
            state = await _get_network_state(network_id)
            if not state:
                fail_count += 1
                if fail_count == 1 or fail_count % 6 == 0:
                    log.warning(
                        "zt_status network_id=%s node_id=%s status=%s retry=%s",
                        network_id,
                        node_id,
                        "unavailable",
                        fail_count,
                    )
                await asyncio.sleep(poll_interval_s)
                continue

            changed = (last_state != state)
            msg = _map_status(state.status)

            if state.status.upper() == "OK":
                if last_state is None or last_state.status.upper() != "OK" or changed:
                    log.info(
                        "zt_status network_id=%s node_id=%s status=%s msg=%s ips=%s",
                        network_id,
                        node_id,
                        state.status,
                        msg,
                        ",".join(state.assigned_ips),
                    )
                fail_count = 0
            else:
                fail_count += 1
                if changed or fail_count == 1 or fail_count % 6 == 0:
                    level = logging.WARNING
                    if state.status.upper() in {"ACCESS_DENIED", "AUTH_FAILED"}:
                        level = logging.ERROR
                    log.log(
                        level,
                        "zt_status network_id=%s node_id=%s status=%s msg=%s retry=%s ips=%s",
                        network_id,
                        node_id,
                        state.status,
                        msg,
                        fail_count,
                        ",".join(state.assigned_ips),
                    )

            last_state = state
        except Exception:
            fail_count += 1
            log.exception(
                "zt_monitor_error network_id=%s node_id=%s retry=%s",
                network_id,
                node_id,
                fail_count,
            )

        await asyncio.sleep(poll_interval_s)

