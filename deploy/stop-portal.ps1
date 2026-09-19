#requires -Version 7.0
[CmdletBinding(SupportsShouldProcess)]
param([switch]$Force)
$ErrorActionPreference = 'Stop'
$portalRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$portalStatePath = Join-Path $portalRoot 'data\portal-runtime\processes.json'
if (-not (Test-Path -LiteralPath $portalStatePath)) { Write-Output '没有由启动脚本登记的进程。'; return }
if (-not $Force) {
    Push-Location $portalRoot
    try {
        & '.\.venv\Scripts\python.exe' -X utf8 -c 'from app.portal.settings import PortalSettings; from app.portal.repository import PortalRepository; import sys; s=PortalRepository(PortalSettings.from_env().db_path); sys.exit(1 if any(j["status"]=="running" for j in s.jobs()) else 0)'
        if ($LASTEXITCODE -ne 0) { throw '存在运行中任务；等待完成，或明确使用 -Force 中断。恢复后不会盲目重发工作流。' }
    } finally { Pop-Location }
}
$state = Get-Content -LiteralPath $portalStatePath -Raw -Encoding utf8 | ConvertFrom-Json
foreach ($entry in @($state.processes)[($state.processes.Count-1)..0]) {
    $process = Get-Process -Id $entry.id -ErrorAction SilentlyContinue
    if ($process -and $process.StartTime.ToUniversalTime().Ticks -eq ([DateTimeOffset]$entry.started_at).UtcDateTime.Ticks) {
        if ($PSCmdlet.ShouldProcess("$($entry.role) PID=$($entry.id)", '停止已登记的进程及子进程')) {
            & taskkill /PID $entry.id /T /F | Out-Null
            if ($LASTEXITCODE -ne 0) { Write-Warning "进程 $($entry.id) 已退出或停止失败。" }
        }
    }
}
if (-not $WhatIfPreference) {
    $state.status='stopped'
    $state | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $portalStatePath -Encoding utf8
}
