param([string]$PythonExecutable = '', [switch]$Dev, [switch]$NoBrowser, [switch]$NoCore)
$options = @{ Action='up'; Open=(-not $NoBrowser); Dev=$Dev; NoCore=$NoCore }
if ($PythonExecutable) { $options.PythonExecutable = $PythonExecutable }
& (Join-Path $PSScriptRoot 'scripts/studio.ps1') @options
exit $LASTEXITCODE
