param([string]$PythonExecutable = '', [switch]$WithCore, [switch]$NoCore, [switch]$Dev, [switch]$NoBrowser)
# Default now includes all three Core services. -WithCore is a compatibility no-op.
& (Join-Path $PSScriptRoot '../../scripts/studio.ps1') -Action up -PythonExecutable $PythonExecutable -NoCore:$NoCore -Dev:$Dev -Open:(-not $NoBrowser)
exit $LASTEXITCODE
