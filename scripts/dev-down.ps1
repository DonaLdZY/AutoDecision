$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$stateDir = Join-Path $root ".dev-state"
$pidFile = Join-Path $stateDir "pids.json"
$knownPorts = @(18101, 18103, 18104, 18080, 5173)

function Stop-ProcessTree {
  param([int]$ProcId)
  try {
    taskkill /PID $ProcId /T /F | Out-Null
    return $true
  } catch {
    return $false
  }
}

function Get-ListeningPidsByPort {
  param([int[]]$Ports)
  $map = @{}
  foreach ($port in $Ports) {
    try {
      $rows = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction Stop
      $pids = @($rows | Select-Object -ExpandProperty OwningProcess -Unique | Where-Object { $_ -and $_ -ne 0 })
      if ($pids.Count -gt 0) {
        $map[$port] = $pids
      }
    } catch {
    }
  }
  return $map
}

function Cleanup-ManagedPorts {
  param([int[]]$Ports)
  $orphanMap = Get-ListeningPidsByPort -Ports $Ports
  if ($orphanMap.Count -eq 0) {
    return
  }
  Write-Host "Found listeners on managed ports. Cleaning up..."
  foreach ($entry in $orphanMap.GetEnumerator()) {
    $port = [int]$entry.Key
    foreach ($procId in @($entry.Value)) {
      $ok = Stop-ProcessTree -ProcId ([int]$procId)
      if ($ok) {
        Write-Host "Stopped orphan PID $procId on port $port"
      } else {
        Write-Host "Failed to stop orphan PID $procId on port $port"
      }
    }
  }
}

if (-not (Test-Path $pidFile)) {
  Write-Host "State file not found: $pidFile"
  $orphanMap = Get-ListeningPidsByPort -Ports $knownPorts
  if ($orphanMap.Count -eq 0) {
    Write-Host "No listeners on managed ports (18101/18103/18104/18080/5173)."
    exit 0
  }
  Cleanup-ManagedPorts -Ports $knownPorts
  exit 0
}

$raw = Get-Content -Raw $pidFile
$state = $raw | ConvertFrom-Json
$procs = @($state.processes)

foreach ($p in $procs) {
  $procId = [int]$p.pid
  $name = [string]$p.name
  if (Stop-ProcessTree -ProcId $procId) {
    Write-Host "Stopped: $name (PID $procId)"
  } else {
    Write-Host "Not running: $name (PID $procId)"
  }
}

Remove-Item -Force $pidFile
Write-Host "State file removed."
Cleanup-ManagedPorts -Ports $knownPorts
