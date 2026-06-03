param(
  [switch]$Force
)

$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$stateDir = Join-Path $root ".dev-state"
$logDir = Join-Path $stateDir "logs"
$pidFile = Join-Path $stateDir "pids.json"

$autoRealizeDir = Join-Path $root "core\AutoRealize"
$autoMlDir = Join-Path $root "core\ML-Master-Alter"
$mlevolveDir = Join-Path $root "core\MLEvolve-Alter"
$gatewayDir = Join-Path $root "frontend\backend"
$uiDir = Join-Path $root "frontend\ui"

$pythonExe = (Get-Command python -ErrorAction Stop).Source
$npmCmd = Get-Command npm.cmd -ErrorAction SilentlyContinue
if ($null -eq $npmCmd) {
  $npmCmd = Get-Command npm -ErrorAction Stop
}
$npmExe = $npmCmd.Source

function Test-PortInUse {
  param([int]$Port)
  try {
    $conns = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction Stop
    return ($conns.Count -gt 0)
  } catch {
    return $false
  }
}

function Get-ListeningPids {
  param([int]$Port)
  try {
    $rows = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction Stop
    return @($rows | Select-Object -ExpandProperty OwningProcess -Unique | Where-Object { $_ -and $_ -ne 0 })
  } catch {
    return @()
  }
}

function Start-HiddenProc {
  param(
    [string]$Name,
    [string]$WorkDir,
    [int]$Port,
    [string]$FilePath,
    [string[]]$ArgumentList
  )

  $ownerPids = @(Get-ListeningPids -Port $Port)
  if (($ownerPids.Count -gt 0) -and -not $Force) {
    throw "Port $Port is already in use by PID(s): $($ownerPids -join ', '). Use -Force or run scripts/dev-down.ps1 first."
  }
  if (($ownerPids.Count -gt 0) -and $Force) {
    foreach ($ownerId in $ownerPids) {
      try {
        taskkill /PID $ownerId /T /F | Out-Null
        Start-Sleep -Milliseconds 300
      } catch {
      }
    }
  }

  $stdoutLog = Join-Path $logDir "$Name.stdout.log"
  $stderrLog = Join-Path $logDir "$Name.stderr.log"
  if (Test-Path $stdoutLog) { Remove-Item -Force $stdoutLog }
  if (Test-Path $stderrLog) { Remove-Item -Force $stderrLog }

  $proc = Start-Process -FilePath $FilePath `
    -ArgumentList $ArgumentList `
    -WorkingDirectory $WorkDir `
    -WindowStyle Hidden `
    -RedirectStandardOutput $stdoutLog `
    -RedirectStandardError $stderrLog `
    -PassThru

  $cmdText = "$FilePath $($ArgumentList -join ' ')"
  return @{
    name = $Name
    pid = $proc.Id
    port = $Port
    workdir = $WorkDir
    cmd = $cmdText
    stdout = $stdoutLog
    stderr = $stderrLog
  }
}

function Wait-HttpReady {
  param(
    [string]$Name,
    [string]$Url,
    [int]$TimeoutSec = 25
  )
  $deadline = (Get-Date).AddSeconds($TimeoutSec)
  while ((Get-Date) -lt $deadline) {
    try {
      $resp = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 2
      if ($resp.StatusCode -ge 200 -and $resp.StatusCode -lt 500) {
        return
      }
    } catch {
    }
    Start-Sleep -Milliseconds 500
  }
  throw "$Name health check failed: $Url not ready in ${TimeoutSec}s"
}

function Test-StaleStateFile {
  param([string]$StateFilePath)
  if (-not (Test-Path $StateFilePath)) {
    return $false
  }
  try {
    $raw = Get-Content -Raw $StateFilePath
    $obj = $raw | ConvertFrom-Json
  } catch {
    return $true
  }
  $procs = @($obj.processes)
  if ($procs.Count -eq 0) {
    return $true
  }

  $aliveCount = 0
  $listenCount = 0
  foreach ($p in $procs) {
    $pidVal = 0
    $portVal = 0
    try { $pidVal = [int]$p.pid } catch {}
    try { $portVal = [int]$p.port } catch {}
    if ($pidVal -gt 0) {
      try {
        $null = Get-Process -Id $pidVal -ErrorAction Stop
        $aliveCount += 1
      } catch {
      }
    }
    if ($portVal -gt 0) {
      $owners = @(Get-ListeningPids -Port $portVal)
      if ($owners.Count -gt 0) {
        $listenCount += 1
      }
    }
  }
  return ($aliveCount -eq 0 -and $listenCount -eq 0)
}

New-Item -ItemType Directory -Force -Path $stateDir | Out-Null
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

if (Test-Path $pidFile) {
  if (Test-StaleStateFile -StateFilePath $pidFile) {
    Write-Host "Detected stale state file after restart, removing: $pidFile"
    Remove-Item -Force $pidFile
  }
}

if (Test-Path $pidFile) {
  Write-Host "Detected existing state file: $pidFile"
  Write-Host "Run scripts/dev-down.ps1 first."
  if (-not $Force) {
    throw "State file exists. Abort. Use -Force to continue."
  }
}

$jobs = @()

try {
  Write-Host "Using python: $pythonExe"
  Write-Host "Using npm:    $npmExe"

  $jobs += Start-HiddenProc -Name "autorealize-api" -WorkDir $autoRealizeDir -Port 18101 -FilePath $pythonExe -ArgumentList @("-m", "uvicorn", "autorealize.service_api:app", "--host", "127.0.0.1", "--port", "18101")
  $jobs += Start-HiddenProc -Name "automl-api" -WorkDir $autoMlDir -Port 18102 -FilePath $pythonExe -ArgumentList @("-m", "uvicorn", "service_api:app", "--host", "127.0.0.1", "--port", "18102")
  $jobs += Start-HiddenProc -Name "mlevolve-api" -WorkDir $mlevolveDir -Port 18103 -FilePath $pythonExe -ArgumentList @("-m", "uvicorn", "service_api:app", "--host", "127.0.0.1", "--port", "18103")
  $jobs += Start-HiddenProc -Name "gateway-api" -WorkDir $gatewayDir -Port 18080 -FilePath $pythonExe -ArgumentList @("-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", "18080")
  $jobs += Start-HiddenProc -Name "frontend-ui" -WorkDir $uiDir -Port 5173 -FilePath $npmExe -ArgumentList @("run", "dev", "--", "--host", "127.0.0.1", "--port", "5173")

  Wait-HttpReady -Name "AutoRealize API" -Url "http://127.0.0.1:18101/health" -TimeoutSec 30
  Wait-HttpReady -Name "AutoML API" -Url "http://127.0.0.1:18102/health" -TimeoutSec 30
  Wait-HttpReady -Name "MLEvolve API" -Url "http://127.0.0.1:18103/health" -TimeoutSec 30
  Wait-HttpReady -Name "Gateway API" -Url "http://127.0.0.1:18080/api/health" -TimeoutSec 30
  Wait-HttpReady -Name "Frontend UI" -Url "http://127.0.0.1:5173" -TimeoutSec 45
} catch {
  Write-Host "Startup failed: $($_.Exception.Message)"
  foreach ($j in $jobs) {
    try { taskkill /PID ([int]$j.pid) /T /F | Out-Null } catch {}
  }
  throw
}

$payload = @{
  started_at = (Get-Date).ToString("s")
  root = [string]$root
  processes = $jobs
}

$payload | ConvertTo-Json -Depth 5 | Set-Content -Encoding UTF8 $pidFile

Write-Host ""
Write-Host "All services started in background:"
Write-Host "1) AutoRealize API: http://127.0.0.1:18101/health"
Write-Host "2) AutoML API:      http://127.0.0.1:18102/health"
Write-Host "3) MLEvolve API:    http://127.0.0.1:18103/health"
Write-Host "4) Gateway API:     http://127.0.0.1:18080/api/health"
Write-Host "5) Frontend UI:     http://127.0.0.1:5173"
Write-Host "Logs: .dev-state/logs/*.log"
Write-Host ""
Write-Host "Stop all: powershell -ExecutionPolicy Bypass -File .\scripts\dev-down.ps1"
