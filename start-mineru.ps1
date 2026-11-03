$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$MinerUPython = Join-Path $ProjectRoot ".mineru\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $MinerUPython)) {
    throw "MinerU is not installed correctly."
}

Set-Location -LiteralPath $ProjectRoot
$ModelRoot = Join-Path $ProjectRoot ".mineru-models\models"
$PipelineModel = Join-Path $ModelRoot "OpenDataLab--PDF-Extract-Kit-1.0\snapshots\master"
$VlmModel = Join-Path $ModelRoot "OpenDataLab--MinerU2.5-Pro-2605-1.2B\snapshots\master"
foreach ($RequiredPath in @(
    (Join-Path $PipelineModel "models"),
    (Join-Path $VlmModel "config.json"),
    (Join-Path $VlmModel "model.safetensors"),
    (Join-Path $VlmModel "tokenizer.json")
)) {
    if (-not (Test-Path -LiteralPath $RequiredPath)) {
        throw "Required local MinerU model file is missing: $RequiredPath"
    }
}
$LocalConfig = Join-Path $ProjectRoot "tmp\mineru-local-config.json"
New-Item -ItemType Directory -Path (Split-Path -Parent $LocalConfig) -Force | Out-Null
$ConfigJson = @{ "models-dir" = @{ pipeline = $PipelineModel; vlm = $VlmModel } } | ConvertTo-Json -Depth 3
[System.IO.File]::WriteAllText($LocalConfig, $ConfigJson, [System.Text.UTF8Encoding]::new($false))
$env:MINERU_TOOLS_CONFIG_JSON = $LocalConfig
$env:MINERU_MODEL_SOURCE = "local"
$env:MINERU_FORMULA_ENABLE = "false"
$env:MINERU_TABLE_ENABLE = "true"
$env:MINERU_API_MAX_CONCURRENT_REQUESTS = "1"
$env:MINERU_PROCESSING_WINDOW_SIZE = "8"
$env:MINERU_API_OUTPUT_ROOT = Join-Path $ProjectRoot "tmp\mineru-api-output"
$env:FTLANG_SMALL_MODEL = Join-Path $env:USERPROFILE "mineru-runtime-data\lid.176.ftz"
$MinerULog = Join-Path $ProjectRoot "tmp\mineru-service.log"
$MinerUErrorLog = Join-Path $ProjectRoot "tmp\mineru-service.error.log"

Write-Host "MinerU service: http://127.0.0.1:8001" -ForegroundColor Green
Write-Host "Keep this window open while processing scanned reports." -ForegroundColor DarkGray
New-Item -ItemType Directory -Path (Split-Path -Parent $MinerULog) -Force | Out-Null
Start-Process -FilePath $MinerUPython -ArgumentList @(
    "-m", "mineru.cli.fast_api",
    "--host", "127.0.0.1",
    "--port", "8001",
    "--enable-vlm-preload", "false"
) -NoNewWindow -Wait -RedirectStandardOutput $MinerULog -RedirectStandardError $MinerUErrorLog
