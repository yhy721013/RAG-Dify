"""本机进程启动器：固定模块、固定回环端口，运行记录供 PS7 停止脚本核对。"""
import argparse
import json
import os
import socket
import subprocess
import sys
import time
import html
from io import StringIO
from datetime import datetime, timezone

import httpx
from dotenv import dotenv_values

from app.errors import DomainError
from app.portal.settings import PortalSettings, bootstrap_settings
from app.portal.repository import PortalRepository
from app.portal.setup import SetupManager, atomic_text, fingerprint
from app.repository import digest
from app.safe_diagnostics import public_error
from app.settings import ROOT
from ingestion.sync_dify import atomic_json


def process_alive(entry):
    identity = int(entry["id"])
    # 精确创建时间比较由 .NET 完成（Python datetime 仅保留六位小数）。
    source_stamp = entry["started_at"]
    if any(char not in "0123456789-:T.Z+" for char in source_stamp):
        raise DomainError("process_identity_error", "进程登记时间无效")
    command = (f"$p=Get-Process -Id {identity} -ErrorAction SilentlyContinue; "
               f"if ($p -and $p.StartTime.ToUniversalTime().Ticks -eq ([DateTimeOffset]'{source_stamp}').UtcDateTime.Ticks) {{ 'owned' }}")
    result = subprocess.run(["pwsh", "-NoProfile", "-Command", command], capture_output=True, text=True,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    return result.returncode == 0 and result.stdout.strip() == "owned"


def stop_owned(entry):
    if process_alive(entry):
        result = subprocess.run(["taskkill", "/PID", str(int(entry["id"])), "/T", "/F"], capture_output=True,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode:
            raise DomainError("process_stop_failed", "无法停止已登记进程：" + entry.get("role", "service"))


def launch_role(role, directory, stamp):
    modules = {"portal": ["uvicorn", "app.portal.main:app", "--host", "127.0.0.1", "--port", "8001", "--workers", "1"],
               "evidence": ["uvicorn", "app.portal.evidence_api:app", "--host", "127.0.0.1", "--port", "8002", "--workers", "1"],
               "worker": ["app.portal.worker"]}
    stdout_path, stderr_path = directory / f"{stamp}-{role}.out.log", directory / f"{stamp}-{role}.err.log"
    with stdout_path.open("ab") as stdout, stderr_path.open("ab") as stderr:
        child = subprocess.Popen([sys.executable, "-X", "utf8", "-m", *modules[role]], cwd=ROOT,
            stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr, creationflags=subprocess.CREATE_NO_WINDOW)
    result = subprocess.run(["pwsh", "-NoProfile", "-Command",
        f"(Get-Process -Id {child.pid}).StartTime.ToUniversalTime().ToString('o')"], capture_output=True, text=True,
        check=True, creationflags=subprocess.CREATE_NO_WINDOW)
    return {"role": role, "id": child.pid, "started_at": result.stdout.strip(),
            "stdout": str(stdout_path), "stderr": str(stderr_path)}


def launch_apply(identity):
    if len(identity) != 32 or any(c not in "0123456789abcdef" for c in identity):
        raise DomainError("input_error", "配置操作 ID 不合法")
    subprocess.Popen([sys.executable, "-X", "utf8", "-m", "app.portal.services", "apply", "--identity", identity],
        cwd=ROOT, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)


def apply_configuration(identity):
    config, _ = bootstrap_settings()
    store = PortalRepository(config.db_path)
    manager = SetupManager(config, store)
    config_before = manager.env.read_text(encoding="utf-8-sig") if manager.env.exists() else ""
    state_path = manager.runtime / "processes.json"
    candidate = config
    services_touched = False
    applied_text = None
    try:
        candidate, meta = manager.read_draft(identity)
        draft_text = manager.draft.read_text(encoding="utf-8")
        frozen = PortalSettings.from_values({**dotenv_values(stream=StringIO(draft_text)), **os.environ})
        if fingerprint(frozen) != meta["fingerprint"] or digest(config_before) != meta["base_revision"]:
            raise DomainError("configuration_conflict", "配置或草稿已在应用前变化，请重新保存")
        if store.state("maintenance") != identity:
            raise DomainError("configuration_conflict", "配置应用锁与请求不一致")
        state = json.loads(state_path.read_text(encoding="utf-8-sig"))
        roles = [e["role"] for e in state["processes"]]
        if "portal" not in roles or len(set(roles)) != len(roles) or set(roles) - {"portal", "worker", "evidence"}:
            raise DomainError("process_identity_error", "需要由启动脚本登记的本实例服务进程")
        atomic_json(manager.apply_path, {"id": identity, "status": "restarting", "fingerprint": meta["fingerprint"]})
        # 保留门户进程，以便在重启工作进程时继续显示状态；根目录/数据库不变。
        for entry in state["processes"]:
            if entry["role"] in {"worker", "evidence"}:
                services_touched = True
                stop_owned(entry)
        if manager.file_revision() != meta["base_revision"]:
            raise DomainError("configuration_conflict", "服务重启期间配置被外部修改，已保留该修改；请重新启动并核对")
        atomic_text(manager.env, draft_text)
        applied_text = draft_text
        services_touched = True
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
        state["processes"] = [e for e in state["processes"] if e["role"] == "portal"]
        for role in ("evidence", "worker"):
            state["processes"].append(launch_role(role, manager.runtime, stamp))
            atomic_json(state_path, state)
        deadline = time.monotonic() + 25
        started = datetime.now(timezone.utc)
        with httpx.Client(timeout=2, trust_env=False) as client:
            while time.monotonic() < deadline:
                try:
                    response = client.get(candidate.evidence_local_url + "/health")
                    beat = store.state("worker_heartbeat")
                    if response.status_code in {200, 503} and response.json().get("database") and beat and datetime.fromisoformat(beat) >= started:
                        break
                except (httpx.HTTPError, ValueError):
                    pass
                time.sleep(.5)
            else:
                raise DomainError("startup_failed", "应用后的证据服务或 worker 未就绪，正在恢复原配置")
        if manager.file_revision() != digest(applied_text):
            raise DomainError("configuration_conflict", "启动期间配置被外部修改，已保留该修改；请重新启动并核对")
        atomic_json(manager.apply_path, {"id": identity, "status": "succeeded", "fingerprint": meta["fingerprint"], "finished_at": datetime.now(timezone.utc).isoformat()})
        manager.draft.unlink(missing_ok=True)
        manager.meta.unlink(missing_ok=True)
    except Exception as error:
        restored = manager.file_revision() == digest(config_before)
        try:
            # 只撤销本次写入；不能用旧副本覆盖编辑器或其他进程的新修改。
            if applied_text is not None and manager.file_revision() == digest(applied_text):
                atomic_text(manager.env, config_before)
                restored = True
        except Exception:
            restored = False
        recovery_error = None
        if services_touched and restored:
            try:
                state = json.loads(state_path.read_text(encoding="utf-8-sig"))
                for entry in state["processes"]:
                    if entry["role"] != "portal":
                        stop_owned(entry)
                state["processes"] = [e for e in state["processes"] if e["role"] == "portal"]
                for role in ("evidence", "worker"):
                    state["processes"].append(launch_role(role, manager.runtime, "rollback-" + str(int(time.time()))))
                atomic_json(state_path, state)
            except Exception as failure:
                recovery_error = public_error(failure, (*config.secret_values(), *candidate.secret_values()))
        atomic_json(manager.apply_path, {"id": identity, "status": "failed", "configuration_restored": restored,
            "error": public_error(error, (*config.secret_values(), *candidate.secret_values())), "recovery_error": recovery_error})
    finally:
        if store.state("maintenance") == identity:
            store.set_state("maintenance", "")


def startup_report(error):
    directory = ROOT / "data/portal-runtime"
    directory.mkdir(parents=True, exist_ok=True)
    detail = public_error(error)
    try:
        detail = public_error(error, PortalSettings.from_env().secret_values())
    except Exception:
        pass
    page = '<!doctype html><meta charset="utf-8"><title>测试台启动诊断</title><h1>本地测试台未能启动</h1><pre>' + html.escape(json.dumps(detail, ensure_ascii=False, indent=2)) + '</pre><p>先确认 PowerShell 7、Python 3.12 和本项目 .venv；勿停止未登记的其他程序。修复后重跑 deploy/start-portal.ps1。</p>'
    path = directory / "startup-diagnostics.html"
    atomic_text(path, page)
    return path


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
    config, configuration_error = bootstrap_settings()
    with worker_lock(config.data_root / "worker.lock"):
        pass
    directory = ROOT / "data/portal-runtime"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "processes.json"
    if path.exists():
        previous = json.loads(path.read_text(encoding="utf-8-sig"))
        if previous.get("status") not in {"stopped"}:
            raise DomainError("process_state_exists", "已有进程登记，请先执行 stop-portal.ps1 核对并停止旧进程")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    state = {"status": "starting", "processes": [], "portal_url": "http://127.0.0.1:8001"}
    for role in (("portal",) if configuration_error else ("portal", "evidence", "worker")):
        state["processes"].append(launch_role(role, directory, stamp))
        atomic_json(path, state)
    deadline = time.monotonic() + 15
    with httpx.Client(trust_env=False, timeout=2) as client:
        while time.monotonic() < deadline:
            try:
                portal = client.get("http://127.0.0.1:8001/api/status")
                if portal.status_code == 200 and portal.json().get("configuration_error"):
                    state["status"] = "setup_required"
                    atomic_json(path, state)
                    print("配置需要修复，请打开 http://127.0.0.1:8001 的首次配置页面。")
                    return
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
    parser.add_argument("action", choices=["start", "apply"])
    parser.add_argument("--identity")
    args = parser.parse_args()
    try:
        if args.action == "apply":
            apply_configuration(args.identity)
        else:
            start()
    except Exception as error:
        print("启动失败，诊断说明：" + str(startup_report(error)))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
