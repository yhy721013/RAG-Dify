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
        & '.\.venv\Scripts\python.exe' -X utf8 -c 'from app.portal.settings import bootstrap_settings; from app.portal.repository import PortalRepository; import sys; s=PortalRepository(bootstrap_settings()[0].db_path); sys.exit(1 if s.path.is_file() and any(j["status"]=="running" for j in s.jobs()) else 0)'
        if ($LASTEXITCODE -ne 0) { throw '存在运行中任务；等待完成，或明确使用 -Force 中断。恢复后不会盲目重发工作流。' }
    } finally { Pop-Location }
}
$state = Get-Content -LiteralPath $portalStatePath -Raw -Encoding utf8 | ConvertFrom-Json
$processEntries = @($state.processes)
# 门户崩溃或开发重载后，已登记的隧道可能不再属于新门户的子进程树。
$tunnelStatePath = Join-Path $portalRoot 'data\portal-runtime\managed-tunnel.json'
if (Test-Path -LiteralPath $tunnelStatePath) {
    $tunnelState = Get-Content -LiteralPath $tunnelStatePath -Raw -Encoding utf8 | ConvertFrom-Json
    if ($tunnelState.id -and $tunnelState.role -eq 'portal-tunnel' -and $tunnelState.origin -eq 'http://127.0.0.1:8002') {
        $processEntries += $tunnelState
    }
}
foreach ($entry in $processEntries[($processEntries.Count-1)..0]) {
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
