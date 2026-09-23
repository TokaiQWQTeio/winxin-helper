$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw '未找到项目 Python 虚拟环境。' }
Set-Location -LiteralPath $projectRoot
try {
    $existing = Invoke-RestMethod -Uri 'http://127.0.0.1:8765/api/status' -TimeoutSec 2
    if ($existing.bot_name) {
        Write-Output '控制页已在运行。'
        Start-Process 'http://127.0.0.1:8765'
        return
    }
} catch {
    # No control server is listening yet.
}
Write-Output '控制页即将打开：http://127.0.0.1:8765'
& $python -X utf8 -m wechat_ai.web_control
