# Run manually in PowerShell after closing active research operations.
# Restarts only the verified local AutoDecision gateway; keeps Studio on 5178.
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$demoRoot = Join-Path $projectRoot 'runs\chemical-studio-demo-20261019'
$backendRoot = Join-Path $projectRoot 'frontend\backend'
$pythonExecutable = 'C:\Users\donaldzy\.conda\envs\automl\python.exe'
$tasks = @(Invoke-RestMethod 'http://127.0.0.1:18080/api/tasks')
if (@($tasks | Where-Object { $_.status -eq 'running' }).Count) {
  throw 'A task is running. Wait for it to finish before restarting.'
}
$listeners = @(Get-NetTCPConnection -State Listen -LocalPort 18080 | Select-Object -ExpandProperty OwningProcess -Unique)
if ($listeners.Count -ne 1) { throw 'Expected exactly one local gateway process.' }
$targetProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$($listeners[0])"
if ($targetProcess.CommandLine -notmatch 'uvicorn\s+app:app.*--port\s+18080' -or $targetProcess.ExecutablePath -ne $pythonExecutable) {
  throw 'Listener identity did not match the verified AutoDecision gateway.'
}
Stop-Process -Id $targetProcess.ProcessId
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$service = Start-Process -FilePath $pythonExecutable -ArgumentList @('-m', 'uvicorn', 'app:app', '--host', '127.0.0.1', '--port', '18080') `
  -WorkingDirectory $backendRoot -WindowStyle Hidden -PassThru `
  -RedirectStandardOutput (Join-Path $demoRoot "gateway-$stamp.stdout.log") `
  -RedirectStandardError (Join-Path $demoRoot "gateway-$stamp.stderr.log")
Write-Output "AutoDecision gateway started (PID $($service.Id)); Studio remains at http://127.0.0.1:5178."
