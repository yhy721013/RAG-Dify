#requires -Version 7.0
function Write-PortalStartupHelp {
    param([string]$ProjectRoot, [string]$Phase)
    $directory = Join-Path $ProjectRoot 'data/portal-runtime'
    New-Item -ItemType Directory -Path $directory -Force | Out-Null
    $path = Join-Path $directory 'startup-bootstrap.html'
    $safePhase = [System.Net.WebUtility]::HtmlEncode($Phase)
    @"
<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>测试台启动排错</title>
<style>body{max-width:850px;margin:48px auto;padding:0 24px;font:17px/1.7 sans-serif}code{background:#eef;padding:3px}h1{font-size:28px}</style>
<h1>$safePhase 未完成</h1><p>查看终端中本次命令的错误，修复后重试。此页不包含配置、密钥或业务文件。</p>
<ol><li>用 PowerShell 7 执行脚本；运行 <code>pwsh --version</code> 确认。</li>
<li>首次安装需要 Python 3.12、Windows Python Launcher 和网络。运行 <code>py -3.12 --version</code>。</li>
<li>在项目根目录运行 <code>pwsh -File deploy/init-portal.ps1 -InstallMinerU</code>，失败后可以重跑；不会覆盖已有配置。</li>
<li>初始化完成后运行 <code>pwsh -File deploy/start-portal.ps1</code>，打开 <code>http://127.0.0.1:8001</code>。</li>
<li>若 8001/8002 被占用，先核对程序身份；本实例可用 <code>deploy/stop-portal.ps1 -WhatIf</code> 查看。不要停止未知程序。</li>
<li>若 Python 已启动，详细原因见同目录 <a href="startup-diagnostics.html">启动诊断</a>；服务日志也在本目录。</li></ol>
<p>脚本不会更改系统执行策略、关闭 TLS 校验或覆盖其他实例。</p></html>
"@ | Set-Content -LiteralPath $path -Encoding utf8
    Write-Output "启动排错说明：$path"
}
