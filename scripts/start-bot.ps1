$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot '.venv/Scripts/python.exe'
$dataDir = Join-Path $projectRoot 'data'
$pidPath = Join-Path $dataDir 'bot.pid'
$outPath = Join-Path $dataDir 'bot.stdout.log'
$errPath = Join-Path $dataDir 'bot.stderr.log'
if (-not (Test-Path -LiteralPath $python)) { throw '未找到项目 Python 虚拟环境。' }
New-Item -ItemType Directory -Force -Path $dataDir | Out-Null
if (Test-Path -LiteralPath $pidPath) {
    $existingPid = [int](Get-Content -LiteralPath $pidPath -Raw)
    $existing = Get-Process -Id $existingPid -ErrorAction SilentlyContinue
    if ($existing -and $existing.Path -eq $python) {
        Write-Output "机器人已在运行：PID $existingPid"
        return
    }
    Remove-Item -LiteralPath $pidPath
}
$config = Get-Content -LiteralPath (Join-Path $projectRoot 'config.json') -Raw -Encoding UTF8 | ConvertFrom-Json
if (-not $config.auto_send_enabled -or -not $config.focus_send_enabled) {
    throw '自动发送及焦点提示确认未启用，拒绝启动。'
}
if ($config.api_base_url -eq 'http://127.0.0.1:11434/v1') {
    & (Join-Path $PSScriptRoot 'start-local-model.ps1')
}
$process = Start-Process -FilePath $python -ArgumentList '-X', 'utf8', '-u', '-m', 'wechat_ai', '--config', 'config.json', 'run' -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput $outPath -RedirectStandardError $errPath
Set-Content -LiteralPath $pidPath -Value $process.Id
Start-Sleep -Seconds 3
if ($process.HasExited) {
    Remove-Item -LiteralPath $pidPath
    Get-Content -LiteralPath $errPath -Tail 15
    throw '机器人启动后退出。'
}
Write-Output "机器人已启动：PID $($process.Id)。日志：$errPath"
