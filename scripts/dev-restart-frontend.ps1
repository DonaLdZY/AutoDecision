param([switch]$Wait, [switch]$Open, [switch]$Force)
& (Join-Path $PSScriptRoot 'studio.ps1') -Action restart -Only frontend -Dev -Open:$Open -Force:$Force -Wait:$Wait
exit $LASTEXITCODE
