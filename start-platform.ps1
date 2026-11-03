$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$VirtualEnvironment = Join-Path $ProjectRoot ".venv"
$Python = Join-Path $VirtualEnvironment "Scripts\python.exe"
$SupervisorScript = Join-Path $ProjectRoot "platform-supervisor.ps1"

Set-Location -LiteralPath $ProjectRoot

if (-not (Test-Path -LiteralPath $Python)) {
    Write-Host "Creating local runtime..." -ForegroundColor Cyan
    python -m venv $VirtualEnvironment
}

Write-Host "Checking required components..." -ForegroundColor Cyan
& $Python -c "import fastapi, uvicorn, sqlalchemy, pypdf, httpx, openpyxl"
if ($LASTEXITCODE -ne 0) {
    & $Python -m pip install --disable-pip-version-check -e ".[test]"
    if ($LASTEXITCODE -ne 0) {
        throw "Platform dependencies could not be installed."
    }
}

$Supervisor = Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -like "*$SupervisorScript*"
} | Select-Object -First 1
if ($null -eq $Supervisor) {
    Write-Host "Starting background service supervisor..." -ForegroundColor Cyan
    Start-Process powershell.exe -WindowStyle Hidden -ArgumentList @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", $SupervisorScript
    ) -WorkingDirectory $ProjectRoot
}

$Deadline = (Get-Date).AddSeconds(90)
while ((Get-Date) -lt $Deadline) {
    $PlatformListener = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
    if ($null -ne $PlatformListener) {
        Write-Host "Platform URL: http://127.0.0.1:8000" -ForegroundColor Green
        Write-Host "The platform will continue running in the background." -ForegroundColor DarkGray
        Start-Process "http://127.0.0.1:8000"
        exit 0
    }
    Start-Sleep -Seconds 2
}

throw "The platform did not start within 90 seconds. Check tmp\service-supervisor.log."
