#requires -Version 7.0
$ErrorActionPreference = 'Stop'
$projectDirectory = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
Push-Location $projectDirectory
try {
    & '.\.venv\Scripts\python.exe' -X utf8 -m app.portal.services start
    if ($LASTEXITCODE -ne 0) { throw '本地服务启动失败，查看 data/portal-runtime 日志。' }
} finally { Pop-Location }
