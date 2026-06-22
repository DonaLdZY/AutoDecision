param(
  [string]$Name = "",
  [int]$Lines = 80,
  [switch]$Follow
)

$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$logDir = Join-Path $root ".dev-state\logs"

if (-not (Test-Path $logDir)) {
  Write-Host "Log directory not found: $logDir"
  exit 0
}

if ([string]::IsNullOrWhiteSpace($Name)) {
  Write-Host "Available logs:"
  Get-ChildItem $logDir -Filter "*.log" | Sort-Object Name | Select-Object -ExpandProperty Name
  Write-Host ""
  Write-Host "Examples:"
  Write-Host "  powershell -ExecutionPolicy Bypass -File .\scripts\dev-logs.ps1 autorealize-api"
  Write-Host "  powershell -ExecutionPolicy Bypass -File .\scripts\dev-logs.ps1 gateway-api -Follow"
  exit 0
}

$paths = @()
$stdout = Join-Path $logDir "$Name.stdout.log"
$stderr = Join-Path $logDir "$Name.stderr.log"
$single = Join-Path $logDir "$Name.log"

if (Test-Path $stdout) { $paths += $stdout }
if (Test-Path $stderr) { $paths += $stderr }
if (Test-Path $single) { $paths += $single }

if ($paths.Count -eq 0) {
  Write-Host "No log files found for: $Name"
  Write-Host "Use without a name to list available logs."
  exit 0
}

Write-Host "Showing logs for: $Name"
foreach ($path in $paths) {
  Write-Host ""
  Write-Host "===== $path ====="
  if ($Follow) {
    Get-Content -Path $path -Tail $Lines -Wait
  } else {
    Get-Content -Path $path -Tail $Lines
  }
}
