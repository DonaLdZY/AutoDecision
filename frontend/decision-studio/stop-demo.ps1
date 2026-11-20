# Compatibility entry: stop only the verified Decision Studio frontend.
& (Join-Path $PSScriptRoot '../../scripts/studio.ps1') -Action down -FrontendOnly
exit $LASTEXITCODE
