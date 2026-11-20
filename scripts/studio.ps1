param(
    [ValidateSet('up','down','restart','status','logs')][string]$Action = 'up',
    [string]$PythonExecutable = '', [switch]$Dev, [switch]$Open,
    [switch]$NoCore, [switch]$FrontendOnly, [switch]$LegacyUI,
    [string]$Only = '', [string]$Name = '', [int]$Lines = 80,
    [switch]$Follow, [switch]$Force, [switch]$Wait
)
$ErrorActionPreference = 'Stop'
# The manager selects the configured service Python. Bootstrap only needs yaml/psutil.
$bootstrapPython = $PythonExecutable
if (-not $bootstrapPython) { $bootstrapPython = $env:AUTODECISION_PYTHON_EXECUTABLE }
if (-not $bootstrapPython) { $bootstrapPython = $env:AUTODECISION_PYTHON }
if (-not $bootstrapPython) { $bootstrapPython = (Get-Command python -ErrorAction Stop).Source }
$managerArgs = @((Join-Path $PSScriptRoot 'studio.py'), $Action)
if ($PythonExecutable) { $managerArgs += @('--python', $PythonExecutable) }
if ($Dev) { $managerArgs += '--dev' }
if ($Open) { $managerArgs += '--open' }
if ($NoCore) { $managerArgs += '--no-core' }
if ($FrontendOnly) { $managerArgs += '--frontend-only' }
if ($LegacyUI) { $managerArgs += '--legacy-ui' }
if ($Only) { $managerArgs += @('--only', $Only) }
if ($Name) { $managerArgs += @('--name', $Name) }
$managerArgs += @('--lines', [string]$Lines)
if ($Follow) { $managerArgs += '--follow' }
if ($Force) { $managerArgs += '--force' }
& $bootstrapPython @managerArgs
exit $LASTEXITCODE
