#requires -Version 7.0
param([switch]$InstallMinerU)
$ErrorActionPreference = 'Stop'
$portalRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$portalPython = Join-Path $portalRoot '.venv\Scripts\python.exe'
. (Join-Path $PSScriptRoot 'startup-help.ps1')
Push-Location $portalRoot
try {
    if (-not (Test-Path -LiteralPath $portalPython)) {
        & py -3.12 -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw '请先安装 Python 3.12 和 Windows Python Launcher。' }
    }
    $portalUv = Join-Path $portalRoot '.venv\Scripts\uv.exe'
    if (-not (Test-Path -LiteralPath $portalUv)) {
        & $portalPython -m pip install 'uv==0.12.16'
        if ($LASTEXITCODE -ne 0) { throw 'uv 安装失败。' }
    }
    & $portalUv sync --locked
    if ($LASTEXITCODE -ne 0) { throw '锁定依赖安装失败。' }
    if ($InstallMinerU) {
        $mineruPython = Join-Path $portalRoot '.venv-mineru\Scripts\python.exe'
        if (-not (Test-Path -LiteralPath $mineruPython)) {
            & $portalUv venv --python 3.12 .venv-mineru
            if ($LASTEXITCODE -ne 0) { throw 'MinerU 虚拟环境创建失败。' }
        }
        & $portalUv pip sync --python $mineruPython ingestion/mineru-requirements.txt
        if ($LASTEXITCODE -ne 0) { throw 'MinerU 锁定依赖安装失败。' }
    }
    & $portalPython -X utf8 -m app.portal.cli init
    if ($LASTEXITCODE -ne 0) { throw '配置初始化失败。' }
    Write-Output '初始化完成。运行 deploy/start-portal.ps1 后，在页面“首次配置与诊断”中填写自己的 Dify 配置。'
} catch {
    Write-PortalStartupHelp -ProjectRoot $portalRoot -Phase '初始化'
    throw
} finally { Pop-Location }
