$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot '.venv/Scripts/python.exe'
$pidPath = Join-Path $projectRoot 'data/bot.pid'
if (-not (Test-Path -LiteralPath $pidPath)) {
    Write-Output '没有后台机器人 PID 文件。'
    return
}
$botPid = [int](Get-Content -LiteralPath $pidPath -Raw)
$process = Get-Process -Id $botPid -ErrorAction SilentlyContinue
if (-not $process) {
    Remove-Item -LiteralPath $pidPath
    Write-Output '机器人进程已经停止。'
    return
}
if ($process.Path -ne $python) {
    throw "PID $botPid 不属于项目 Python，已拒绝停止。"
}
Stop-Process -Id $botPid
Remove-Item -LiteralPath $pidPath
Write-Output "已停止机器人：PID $botPid"
