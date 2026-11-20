param([string]$Name = '', [int]$Lines = 80, [switch]$Follow)
& (Join-Path $PSScriptRoot 'studio.ps1') -Action logs -Name $Name -Lines $Lines -Follow:$Follow
exit $LASTEXITCODE
