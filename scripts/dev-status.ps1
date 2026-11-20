param([switch]$LegacyUI)
& (Join-Path $PSScriptRoot 'studio.ps1') -Action status -LegacyUI:$LegacyUI
exit $LASTEXITCODE
