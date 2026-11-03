$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$MinerUStartScript = Join-Path $ProjectRoot "start-mineru.ps1"
$RuntimeDirectory = Join-Path $ProjectRoot "tmp"
$SupervisorLog = Join-Path $RuntimeDirectory "service-supervisor.log"
$PlatformLog = Join-Path $RuntimeDirectory "platform-service.log"
$PlatformErrorLog = Join-Path $RuntimeDirectory "platform-service.error.log"

Set-Location -LiteralPath $ProjectRoot
New-Item -ItemType Directory -Path $RuntimeDirectory -Force | Out-Null

function Write-SupervisorLog {
    param([Parameter(Mandatory = $true)][string]$Message)
    Add-Content -LiteralPath $SupervisorLog -Value "[$(Get-Date -Format o)] $Message"
}

function Test-LocalPort {
    param([Parameter(Mandatory = $true)][int]$Port)
    return $null -ne (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
}

function Wait-LocalPort {
    param(
        [Parameter(Mandatory = $true)][int]$Port,
        [Parameter(Mandatory = $true)][int]$TimeoutSeconds
    )
    $Deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $Deadline) {
        if (Test-LocalPort -Port $Port) {
            return $true
        }
        Start-Sleep -Seconds 2
    }
    return $false
}

Write-SupervisorLog -Message "Service supervisor started."
while ($true) {
    try {
        if (-not (Test-LocalPort -Port 8001)) {
            Write-SupervisorLog -Message "MinerU is unavailable; starting it."
            Start-Process powershell.exe -WindowStyle Hidden -ArgumentList @(
                "-NoProfile",
                "-ExecutionPolicy", "Bypass",
                "-File", $MinerUStartScript
            ) -WorkingDirectory $ProjectRoot
            if (-not (Wait-LocalPort -Port 8001 -TimeoutSeconds 120)) {
                Write-SupervisorLog -Message "MinerU did not open port 8001 within 120 seconds."
            }
        }

        if (-not (Test-LocalPort -Port 8000)) {
            Write-SupervisorLog -Message "Platform is unavailable; starting it."
            Start-Process -FilePath $Python -WindowStyle Hidden -ArgumentList @(
                "-m", "uvicorn", "app.main:app",
                "--host", "127.0.0.1",
                "--port", "8000"
            ) -WorkingDirectory $ProjectRoot `
                -RedirectStandardOutput $PlatformLog `
                -RedirectStandardError $PlatformErrorLog
            if (-not (Wait-LocalPort -Port 8000 -TimeoutSeconds 60)) {
                Write-SupervisorLog -Message "Platform did not open port 8000 within 60 seconds."
            }
        }
    }
    catch {
        Write-SupervisorLog -Message "Supervisor check failed: $($_.Exception.Message)"
    }
    Start-Sleep -Seconds 10
}
