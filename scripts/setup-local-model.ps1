$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$ollama = Join-Path $projectRoot 'runtime/ollama/ollama.exe'
if (-not (Test-Path -LiteralPath $ollama)) {
    throw '未找到 Ollama 便携版。'
}
& (Join-Path $PSScriptRoot 'start-local-model.ps1')
$env:OLLAMA_HOST = '127.0.0.1:11434'
& $ollama pull 'deepseek-r1:8b'
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& (Join-Path $projectRoot '.venv/Scripts/python.exe') -m wechat_ai --config (Join-Path $projectRoot 'config.json') test-model
exit $LASTEXITCODE
