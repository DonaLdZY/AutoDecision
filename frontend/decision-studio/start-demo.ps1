param([switch]$NoBrowser, [switch]$Dev)
# Compatibility name: starts the real Studio frontend; synthetic demo requires ?demo=1.
& (Join-Path $PSScriptRoot '../../scripts/studio.ps1') -Action up -FrontendOnly -Dev:$Dev -Open:(-not $NoBrowser)
exit $LASTEXITCODE
