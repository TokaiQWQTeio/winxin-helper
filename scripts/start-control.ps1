$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw '未找到项目 Python 虚拟环境。' }
Set-Location -LiteralPath $projectRoot
$controlHost = if ($env:ASSISTANT_CONTROL_BIND) { $env:ASSISTANT_CONTROL_BIND } else { '127.0.0.1' }
$controlUrl = "http://${controlHost}:8765"
try {
    $existing = Invoke-RestMethod -Uri "$controlUrl/api/status" -TimeoutSec 2
    if ($existing.bot_name) {
        Write-Output '控制页已在运行。'
        Start-Process $controlUrl
        return
    }
} catch {
    # No control server is listening yet.
}
Write-Output "控制页即将打开：$controlUrl"
& $python -X utf8 -m wechat_ai.web_control
