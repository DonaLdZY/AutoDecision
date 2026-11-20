param([switch]$FrontendOnly)
& (Join-Path $PSScriptRoot '../../scripts/studio.ps1') -Action down -FrontendOnly:$FrontendOnly
exit $LASTEXITCODE
