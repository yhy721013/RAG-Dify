#requires -Version 7.0
$ErrorActionPreference = 'Stop'
$portalRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
Push-Location $portalRoot
try {
    $dirty = git status --porcelain
    if ($dirty) { throw '请先审阅并提交本轮源码；导出只包含 Git HEAD。' }
    $files = git ls-files
    $forbidden = $files | Where-Object { $_ -match '^(data/|test_files/|\.venv|\.env($|\.))' -and $_ -ne '.env.example' }
    if ($forbidden) { throw '发现不应交付的已跟踪文件，请先检查 Git。' }
    $revision = git rev-parse --short HEAD
    $destination = Join-Path $portalRoot 'dist'
    New-Item -ItemType Directory -Path $destination -Force | Out-Null
    $archive = Join-Path $destination "mechanical-safety-rag-$revision.zip"
    & git archive --format=zip "--output=$archive" HEAD
    if ($LASTEXITCODE -ne 0) { throw '源码包导出失败。' }
    Get-FileHash -LiteralPath $archive -Algorithm SHA256 | Select-Object Path,Hash
    Write-Output '只包含当前已跟踪源码；未来推送私有仓库前仍须审计完整 Git 历史。'
} finally { Pop-Location }
