param(
    [switch]$FrontendOnly,
    [string]$PythonExecutable = ''
)

$arguments = @{ Action = 'down'; FrontendOnly = $FrontendOnly }
if ($PythonExecutable) { $arguments.PythonExecutable = $PythonExecutable }
& (Join-Path $PSScriptRoot 'scripts/studio.ps1') @arguments
exit $LASTEXITCODE
