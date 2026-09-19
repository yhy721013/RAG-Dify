#requires -Version 7.0
$ErrorActionPreference = 'Stop'
$portalRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
Push-Location $portalRoot
try {
    & '.\.venv\Scripts\python.exe' -X utf8 -m app.portal.cli doctor
    if ($LASTEXITCODE -ne 0) { throw '配置检查失败。' }
    if (Test-Path -LiteralPath '.venv-mineru\Scripts\mineru.exe') {
        & '.\.venv-mineru\Scripts\mineru.exe' version --json
    }
    Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
        Where-Object LocalPort -In @(8001, 8002) | Select-Object LocalAddress, LocalPort, OwningProcess
} finally { Pop-Location }
