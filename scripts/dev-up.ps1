param([string]$PythonExecutable = '', [switch]$Force, [switch]$Wait, [switch]$Open, [switch]$NoCore, [switch]$LegacyUI)
& (Join-Path $PSScriptRoot 'studio.ps1') -Action up -Dev -PythonExecutable $PythonExecutable -Open:$Open -NoCore:$NoCore -LegacyUI:$LegacyUI -Force:$Force -Wait:$Wait
exit $LASTEXITCODE
