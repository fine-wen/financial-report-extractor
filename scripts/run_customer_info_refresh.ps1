$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$runtimeRoot = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies'
$pythonExe = Join-Path $runtimeRoot 'python\python.exe'
$nodeExe = Join-Path $runtimeRoot 'node\bin\node.exe'
$packageRoot = Join-Path $runtimeRoot 'node\node_modules'
$junction = Join-Path $projectRoot 'scripts\node_modules'
$outputDir = Join-Path $projectRoot 'outputs\20260929_customer_info_refresh'
$payloadPath = Join-Path $outputDir 'refresh_payload.json'
$snapshotPath = Join-Path $outputDir 'latest_snapshot.json'
$workbookPath = Join-Path $outputDir '客户信息资质汇总.xlsx'

foreach ($needed in @($pythonExe, $nodeExe, $packageRoot)) {
    if (-not (Test-Path -LiteralPath $needed)) {
        throw "缺少工作环境：$needed。请在本机 Codex 工作环境中运行。"
    }
}
if (-not (Test-Path -LiteralPath $junction)) {
    New-Item -ItemType Junction -Path $junction -Target $packageRoot | Out-Null
}
New-Item -ItemType Directory -Path $outputDir -Force | Out-Null

& $pythonExe (Join-Path $projectRoot 'scripts\refresh_customer_info.py') --source (Join-Path $projectRoot '客户信息') --previous $snapshotPath --output $payloadPath
if ($LASTEXITCODE -ne 0) { throw '源文件检查失败，旧汇总表未更新。' }

& $nodeExe (Join-Path $projectRoot 'scripts\build_customer_info_workbook.mjs') $payloadPath $workbookPath $snapshotPath
if ($LASTEXITCODE -ne 0) { throw '汇总表生成失败；请检查错误，旧快照未更新。' }

Write-Host "完成：$workbookPath"
