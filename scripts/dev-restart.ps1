param(
  [ValidateSet(
    "frontend", "frontend-ui", "ui",
    "gateway", "gateway-api", "backend",
    "autorealize", "autorealize-api",
    "automl", "automl-api",
    "mlevolve", "mlevolve-api",
    "autoreport", "autoreport-api"
  )]
  [string]$Only = "",
  [switch]$Force,
  [switch]$Wait,
  [switch]$Open
)

$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$stateDir = Join-Path $root ".dev-state"
$logDir = Join-Path $stateDir "logs"
$pidFile = Join-Path $stateDir "pids.json"

$serviceDefs = @{
  "autorealize-api" = @{
    port = 18101
    workdir = Join-Path $root "core\AutoRealize"
    file = "python"
    args = @("-m", "uvicorn", "autorealize.service_api:app", "--host", "127.0.0.1", "--port", "18101")
    health = "http://127.0.0.1:18101/health"
  }
  "automl-api" = @{
    port = 18102
    workdir = Join-Path $root "core\ML-Master-Alter"
    file = "python"
    args = @("-m", "uvicorn", "service_api:app", "--host", "127.0.0.1", "--port", "18102")
    health = "http://127.0.0.1:18102/health"
  }
  "mlevolve-api" = @{
    port = 18103
    workdir = Join-Path $root "core\MLEvolve-Alter"
    file = "python"
    args = @("-m", "uvicorn", "service_api:app", "--host", "127.0.0.1", "--port", "18103")
    health = "http://127.0.0.1:18103/health"
  }
  "autoreport-api" = @{
    port = 18104
    workdir = Join-Path $root "core\AutoReport"
    file = "python"
    args = @("-m", "uvicorn", "service_api:app", "--host", "127.0.0.1", "--port", "18104")
    health = "http://127.0.0.1:18104/health"
  }
  "gateway-api" = @{
    port = 18080
    workdir = Join-Path $root "frontend\backend"
    file = "python"
    args = @("-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", "18080")
    health = "http://127.0.0.1:18080/api/health"
  }
  "frontend-ui" = @{
    port = 5173
    workdir = Join-Path $root "frontend\ui"
    file = "npm"
    args = @("run", "dev", "--", "--host", "127.0.0.1", "--port", "5173")
    health = "http://127.0.0.1:5173"
  }
}

$aliases = @{
  "frontend" = "frontend-ui"
  "frontend-ui" = "frontend-ui"
  "ui" = "frontend-ui"
  "gateway" = "gateway-api"
  "gateway-api" = "gateway-api"
  "backend" = "gateway-api"
  "autorealize" = "autorealize-api"
  "autorealize-api" = "autorealize-api"
  "automl" = "automl-api"
  "automl-api" = "automl-api"
  "mlevolve" = "mlevolve-api"
  "mlevolve-api" = "mlevolve-api"
  "autoreport" = "autoreport-api"
  "autoreport-api" = "autoreport-api"
}

function Resolve-Exe {
  param([string]$Kind)
  if ($Kind -eq "npm") {
    $npmCmd = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if ($null -eq $npmCmd) {
      $npmCmd = Get-Command npm -ErrorAction Stop
    }
    return $npmCmd.Source
  }
  return (Get-Command python -ErrorAction Stop).Source
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

function Stop-ProcessTree {
  param([int]$ProcId)
  try {
    taskkill /PID $ProcId /T /F | Out-Null
    return $true
  } catch {
    return $false
  }
}

function Wait-HttpReady {
  param(
    [string]$Name,
    [string]$Url,
    [int]$TimeoutSec = 45
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

function Read-State {
  if (-not (Test-Path $pidFile)) {
    return [pscustomobject]@{
      started_at = (Get-Date).ToString("s")
      root = [string]$root
      processes = @()
    }
  }
  try {
    return (Get-Content -Raw $pidFile | ConvertFrom-Json)
  } catch {
    return [pscustomobject]@{
      started_at = (Get-Date).ToString("s")
      root = [string]$root
      processes = @()
    }
  }
}

function Write-State {
  param([object]$State)
  New-Item -ItemType Directory -Force -Path $stateDir | Out-Null
  $State | ConvertTo-Json -Depth 6 | Set-Content -Encoding UTF8 $pidFile
}

function Start-ServiceProc {
  param([string]$Name)
  $def = $serviceDefs[$Name]
  $port = [int]$def.port
  $workdir = [string]$def.workdir
  $filePath = Resolve-Exe -Kind ([string]$def.file)
  $args = [string[]]$def.args

  New-Item -ItemType Directory -Force -Path $logDir | Out-Null
  $stdoutLog = Join-Path $logDir "$Name.stdout.log"
  $stderrLog = Join-Path $logDir "$Name.stderr.log"
  if (Test-Path $stdoutLog) { Remove-Item -Force $stdoutLog }
  if (Test-Path $stderrLog) { Remove-Item -Force $stderrLog }

  $proc = Start-Process -FilePath $filePath `
    -ArgumentList $args `
    -WorkingDirectory $workdir `
    -WindowStyle Hidden `
    -RedirectStandardOutput $stdoutLog `
    -RedirectStandardError $stderrLog `
    -PassThru

  return [pscustomobject]@{
    name = $Name
    pid = $proc.Id
    port = $port
    workdir = $workdir
    cmd = "$filePath $($args -join ' ')"
    stdout = $stdoutLog
    stderr = $stderrLog
  }
}

if (-not $Only) {
  $down = Join-Path $PSScriptRoot "dev-down.ps1"
  $up = Join-Path $PSScriptRoot "dev-up.ps1"

  Write-Host "Stopping AutoDecision dev services..."
  & $down

  Write-Host ""
  Write-Host "Starting AutoDecision dev services..."
  $argsForUp = @()
  if ($Force) { $argsForUp += "-Force" }
  if ($Wait) { $argsForUp += "-Wait" }
  if ($Open) { $argsForUp += "-Open" }
  & $up @argsForUp
  exit $LASTEXITCODE
}

$serviceName = $aliases[$Only]
if (-not $serviceName) {
  throw "Unknown service: $Only"
}
$def = $serviceDefs[$serviceName]
$port = [int]$def.port

Write-Host "Restarting only: $serviceName"

$state = Read-State
$existing = @($state.processes | Where-Object { $_.name -eq $serviceName })
foreach ($p in $existing) {
  try {
    $procId = [int]$p.pid
    if (Stop-ProcessTree -ProcId $procId) {
      Write-Host "Stopped state PID $procId for $serviceName"
    }
  } catch {
  }
}

$listeners = @(Get-ListeningPids -Port $port)
foreach ($procId in $listeners) {
  if (($existing | Where-Object { [int]$_.pid -eq [int]$procId }).Count -gt 0) {
    continue
  }
  if ($Force -or $serviceName -eq "frontend-ui") {
    if (Stop-ProcessTree -ProcId ([int]$procId)) {
      Write-Host "Stopped listener PID $procId on port $port"
    }
  } else {
    throw "Port $port is still in use by PID $procId. Re-run with -Force to stop it."
  }
}

Start-Sleep -Milliseconds 300
$started = Start-ServiceProc -Name $serviceName

$remaining = @($state.processes | Where-Object { $_.name -ne $serviceName })
$state.processes = @($remaining + $started)
$state.root = [string]$root
if (-not $state.started_at) {
  $state.started_at = (Get-Date).ToString("s")
}
Write-State -State $state

Write-Host "Started: $serviceName (PID $($started.pid), port $port)"
Write-Host "Logs:"
Write-Host "  stdout: $($started.stdout)"
Write-Host "  stderr: $($started.stderr)"

if ($Wait) {
  Wait-HttpReady -Name $serviceName -Url ([string]$def.health) -TimeoutSec 45
  Write-Host "Health check passed: $($def.health)"
}

if ($Open -and $serviceName -eq "frontend-ui") {
  Start-Process "http://127.0.0.1:5173"
}
