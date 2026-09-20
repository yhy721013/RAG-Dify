"""只管理门户自己登记的临时隧道；不接管用户已有隧道。"""
import hashlib
import json
import os
import re
import subprocess
import time
from datetime import datetime, timezone

from app.errors import DomainError
from app.portal.services import process_alive, stop_owned
from app.portal.support import tail
from app.safe_diagnostics import scrub
from app.settings import ROOT
from ingestion.sync_dify import atomic_json, sync_lock

VERSION = "2026.9.1"
SHA256 = "2837888cc0f5d58f15b6dc478376de90b4d3ba5241c7947455d1e0a0df429712"
DOWNLOAD_URL = "https://github.com/cloudflare/cloudflared/releases/download/2026.9.1/cloudflared-windows-amd64.exe"


def state_path():
    return ROOT / "data/portal-runtime/managed-tunnel.json"


def status(config):
    path = state_path()
    state = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    return {"managed": bool(state), "status": state.get("status", "not_started"), "public_url": state.get("public_url", ""),
            "configured_url": config.evidence_public_url, "tool_exists": config.cloudflared_executable.is_file(),
            "required_version": VERSION, "download_url": DOWNLOAD_URL, "error": state.get("error"),
            "last_checked_at": state.get("checked_at", "")}


def operate(config, action, tick=lambda: None):
    directory = state_path().parent
    directory.mkdir(parents=True, exist_ok=True)
    with sync_lock(directory / "tunnel-control.lock"):
        state = json.loads(state_path().read_text(encoding="utf-8")) if state_path().exists() else {}
        alive = bool(state.get("id")) and process_alive(state)
        if action == "stop":
            if alive:
                stop_owned(state)
            state.update(status="stopped", checked_at=datetime.now(timezone.utc).isoformat())
            atomic_json(state_path(), state)
            return status(config)
        if action == "check":
            state.update(status="connected" if alive and state.get("public_url") else "stopped", checked_at=datetime.now(timezone.utc).isoformat())
            if state.get("id"):
                atomic_json(state_path(), state)
            return status(config)
        if action != "start":
            raise DomainError("input_error", "未知隧道操作")
        if alive:
            return status(config)
        if os.name != "nt" or not config.cloudflared_executable.is_file():
            raise DomainError("tunnel_tool_missing", "请按向导安装 Windows cloudflared 固定版本")
        with config.cloudflared_executable.open("rb") as stream:
            checksum = hashlib.file_digest(stream, "sha256").hexdigest()
        if checksum != SHA256:
            raise DomainError("tunnel_tool_mismatch", "工具 SHA-256 与项目验证版本不一致；请从向导中的官方地址下载")
        if not config.evidence_api_token:
            raise DomainError("configuration_error", "先配置证据服务密钥，再启动公网隧道")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
        stdout, stderr = directory / (stamp + "-tunnel.out.log"), directory / (stamp + "-tunnel.err.log")
        with stdout.open("ab") as out, stderr.open("ab") as err:
            child = subprocess.Popen([str(config.cloudflared_executable), "tunnel", "--no-autoupdate", "--url",
                config.evidence_local_url, "--metrics", "127.0.0.1:0"], cwd=ROOT, stdin=subprocess.DEVNULL,
                stdout=out, stderr=err, creationflags=subprocess.CREATE_NO_WINDOW)
        created = subprocess.run(["pwsh", "-NoProfile", "-Command", f"(Get-Process -Id {child.pid}).StartTime.ToUniversalTime().ToString('o')"],
            capture_output=True, text=True, check=True, creationflags=subprocess.CREATE_NO_WINDOW).stdout.strip()
        state = {"id": child.pid, "role": "portal-tunnel", "started_at": created, "status": "starting", "public_url": "",
                 "stdout": str(stdout), "stderr": str(stderr), "origin": config.evidence_local_url}
        atomic_json(state_path(), state)
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            tick()
            output = tail(stderr)
            match = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", output)
            if match:
                state["public_url"] = match.group()
            if match and "Registered tunnel connection" in output:
                state.update(status="connected", checked_at=datetime.now(timezone.utc).isoformat())
                atomic_json(state_path(), state)
                return status(config)
            if child.poll() is not None:
                break
            time.sleep(.5)
        state.update(status="failed", error=scrub(tail(stderr), config.secret_values(), 3000), checked_at=datetime.now(timezone.utc).isoformat())
        atomic_json(state_path(), state)
        raise DomainError("tunnel_failed", "临时隧道未连接，详情见任务日志", details={"upstream_message": state["error"]})
