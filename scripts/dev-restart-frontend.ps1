param(
  [switch]$Wait,
  [switch]$Open,
  [switch]$Force
)

$ErrorActionPreference = "Stop"

$restart = Join-Path $PSScriptRoot "dev-restart.ps1"
$argsForRestart = @("-Only", "frontend")
if ($Wait) { $argsForRestart += "-Wait" }
if ($Open) { $argsForRestart += "-Open" }
if ($Force) { $argsForRestart += "-Force" }

& $restart @argsForRestart
