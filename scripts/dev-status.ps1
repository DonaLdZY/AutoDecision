$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$stateDir = Join-Path $root ".dev-state"
$pidFile = Join-Path $stateDir "pids.json"

$healthUrls = @{
  "autorealize-api" = "http://127.0.0.1:18101/health"
  "algoevolve-api" = "http://127.0.0.1:18103/health"
  "autoreport-api" = "http://127.0.0.1:18104/health"
  "gateway-api" = "http://127.0.0.1:18080/api/health"
  "frontend-ui" = "http://127.0.0.1:5173"
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

function Test-ProcessAlive {
  param([int]$ProcId)
  try {
    $null = Get-Process -Id $ProcId -ErrorAction Stop
    return $true
  } catch {
    return $false
  }
}

function Test-HttpHealth {
  param([string]$Url)
  try {
    $resp = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 2
    return "$($resp.StatusCode)"
  } catch {
    return "not-ready"
  }
}

if (-not (Test-Path $pidFile)) {
  Write-Host "State file not found: $pidFile"
  Write-Host "Run scripts/dev-up.ps1 first, or check managed ports manually."
  exit 0
}

$state = (Get-Content -Raw $pidFile) | ConvertFrom-Json
$rows = @()

foreach ($p in @($state.processes)) {
  $name = [string]$p.name
  $procId = [int]$p.pid
  $port = [int]$p.port
  $listeners = @(Get-ListeningPids -Port $port)
  $url = [string]$healthUrls[$name]

  $rows += [PSCustomObject]@{
    Name = $name
    PID = $procId
    Process = $(if (Test-ProcessAlive -ProcId $procId) { "alive" } else { "dead" })
    Port = $port
    ListenerPID = $(if ($listeners.Count -gt 0) { $listeners -join "," } else { "-" })
    Health = $(if ($url) { Test-HttpHealth -Url $url } else { "-" })
  }
}

Write-Host "AutoDecision dev services"
Write-Host "Root: $root"
Write-Host "Started at: $($state.started_at)"
Write-Host ""
$rows | Format-Table -AutoSize
Write-Host ""
Write-Host "Logs: powershell -ExecutionPolicy Bypass -File .\scripts\dev-logs.ps1"
Write-Host "Stop: powershell -ExecutionPolicy Bypass -File .\scripts\dev-down.ps1"
