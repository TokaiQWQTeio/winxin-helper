$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$executable = Join-Path $projectRoot 'runtime/ollama/ollama.exe'
$modelDir = Join-Path $projectRoot 'runtime/models'
if (-not (Test-Path -LiteralPath $executable)) {
    throw '未找到 runtime/ollama/ollama.exe；请先安装 Ollama 便携版。'
}
New-Item -ItemType Directory -Force -Path $modelDir | Out-Null
try {
    $status = Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/version' -TimeoutSec 2
    Write-Output "Ollama 已在运行：$($status.version)；本脚本的资源限制只对新启动的 Ollama 进程生效。"
    return
} catch {
    # No local server is running yet.
}
$env:OLLAMA_MODELS = $modelDir
$env:OLLAMA_HOST = '127.0.0.1:11434'
# Keep the 16 GiB host responsive while WeChat and normal desktop apps run.
$env:OLLAMA_MAX_LOADED_MODELS = '1'
$env:OLLAMA_NUM_PARALLEL = '1'
$env:OLLAMA_CONTEXT_LENGTH = '4096'
$env:OLLAMA_KEEP_ALIVE = '1m'
$process = Start-Process -FilePath $executable -ArgumentList 'serve' -WindowStyle Hidden -PassThru
for ($attempt = 0; $attempt -lt 20; $attempt++) {
    Start-Sleep -Milliseconds 500
    try {
        $status = Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/version' -TimeoutSec 2
        Write-Output "Ollama 已启动：PID $($process.Id)，版本 $($status.version)"
        return
    } catch {
        if ($process.HasExited) { break }
    }
}
throw 'Ollama 未能启动；请检查 Windows 系统日志。'
