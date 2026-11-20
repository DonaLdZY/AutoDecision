param([switch]$FrontendOnly, [switch]$LegacyUI)
& (Join-Path $PSScriptRoot 'studio.ps1') -Action down -FrontendOnly:$FrontendOnly -LegacyUI:$LegacyUI
exit $LASTEXITCODE
