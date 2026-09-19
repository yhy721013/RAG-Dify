"""本机进程启动器：固定模块、固定回环端口，运行记录供 PS7 停止脚本核对。"""
import argparse
import json
import os
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone

import httpx

from app.errors import DomainError
from app.portal.settings import PortalSettings
from app.settings import ROOT
from ingestion.sync_dify import atomic_json


def start():
    if not (ROOT / ".env.portal").is_file():
        raise DomainError("configuration_error", "请先执行 deploy/init-portal.ps1")
    if os.name != "nt":
        raise DomainError("configuration_error", "启动器首版仅支持 Windows；其他系统请按运行手册分别启动")
    for port in (8001, 8002):
        with socket.socket() as probe:
            if probe.connect_ex(("127.0.0.1", port)) == 0:
                raise DomainError("port_in_use", f"端口 {port} 已被占用，未更改现有服务")
    from app.portal.worker import worker_lock
    with worker_lock(PortalSettings.from_env().data_root / "worker.lock"):
        pass
    directory = ROOT / "data/portal-runtime"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "processes.json"
    if path.exists():
        previous = json.loads(path.read_text(encoding="utf-8-sig"))
        if previous.get("status") not in {"stopped"}:
            raise DomainError("process_state_exists", "已有进程登记，请先执行 stop-portal.ps1 核对并停止旧进程")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    specs = {"portal": ["uvicorn", "app.portal.main:app", "--host", "127.0.0.1", "--port", "8001", "--workers", "1"],
             "evidence": ["uvicorn", "app.portal.evidence_api:app", "--host", "127.0.0.1", "--port", "8002", "--workers", "1"],
             "worker": ["app.portal.worker"]}
    state = {"status": "starting", "processes": [], "portal_url": "http://127.0.0.1:8001"}
    for role, arguments in specs.items():
        with (directory / f"{stamp}-{role}.out.log").open("ab") as stdout, (directory / f"{stamp}-{role}.err.log").open("ab") as stderr:
            child = subprocess.Popen([sys.executable, "-X", "utf8", "-m", *arguments], cwd=ROOT,
                stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr, creationflags=subprocess.CREATE_NO_WINDOW)
        # 用系统创建时间防止 PID 重用；输出只含本次子进程时间，不读取环境或凭据。
        result = subprocess.run(["pwsh", "-NoProfile", "-Command",
            f"(Get-Process -Id {child.pid}).StartTime.ToUniversalTime().ToString('o')"],
            capture_output=True, text=True, check=True, creationflags=subprocess.CREATE_NO_WINDOW)
        state["processes"].append({"role": role, "id": child.pid, "started_at": result.stdout.strip()})
        atomic_json(path, state)
    deadline = time.monotonic() + 15
    with httpx.Client(trust_env=False, timeout=2) as client:
        while time.monotonic() < deadline:
            try:
                portal = client.get("http://127.0.0.1:8001/api/status")
                evidence = client.get("http://127.0.0.1:8002/health")
                heartbeat = portal.json().get("worker_heartbeat") if portal.status_code == 200 else None
                worker_ready = bool(heartbeat) and (datetime.now(timezone.utc) - datetime.fromisoformat(heartbeat)).total_seconds() < 15
                if (portal.status_code == 200 and evidence.status_code in {200, 503}
                    and evidence.json().get("database") is True and worker_ready):
                    state["status"] = "running"
                    atomic_json(path, state)
                    print("页面、证据服务及 worker 已启动：http://127.0.0.1:8001。")
                    return
            except httpx.HTTPError:
                pass
            time.sleep(.25)
    raise DomainError("startup_failed", "页面未就绪，进程登记与日志已保留")


def main():
    parser = argparse.ArgumentParser(description="本机测试台进程启动器")
    parser.add_argument("action", choices=["start"])
    parser.parse_args()
    try:
        start()
    except DomainError as error:
        print(str(error))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
