[CmdletBinding()]
param(
    [switch]$Quiet,
    [switch]$KeepLogs
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$projectRoot = $PSScriptRoot
$runtimeDir = Join-Path $projectRoot '.smartdesk-dev'
$stateFile = Join-Path $runtimeDir 'processes.json'

function Wait-ProcessExit {
    param([int]$ProcessId, [int]$TimeoutSeconds = 10)

    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    while ((Get-Process -Id $ProcessId -ErrorAction SilentlyContinue) -and
           [DateTime]::UtcNow -lt $deadline) {
        Start-Sleep -Milliseconds 100
    }
    if (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue) {
        throw "Timed out waiting for tracked PID $ProcessId to exit."
    }
}

function Remove-RuntimeDirectory {
    $lastError = $null
    for ($attempt = 1; $attempt -le 6; $attempt++) {
        try {
            Remove-Item -LiteralPath $runtimeDir -Recurse -Force -ErrorAction Stop
            return
        } catch {
            $lastError = $_
            if ($attempt -lt 6) { Start-Sleep -Milliseconds 300 }
        }
    }

    $remainingFiles = @(Get-ChildItem -LiteralPath $runtimeDir -Recurse -File -ErrorAction SilentlyContinue)
    $nonLogFiles = @($remainingFiles | Where-Object { $_.Extension -ne '.log' })
    if ($remainingFiles.Count -gt 0 -and $nonLogFiles.Count -eq 0) {
        Write-Warning "SmartDesk stopped, but Windows is still releasing stale log file handles in '$runtimeDir'. The logs can be removed later."
        return
    }
    throw $lastError
}

if (-not (Test-Path -LiteralPath $stateFile)) {
    if (-not $Quiet) { Write-Host 'No SmartDesk dev launcher processes are recorded.' }
    exit 0
}

$state = Get-Content -LiteralPath $stateFile -Raw | ConvertFrom-Json
if ($state.project_root -ne $projectRoot) {
    throw 'Refusing to stop processes: launcher state belongs to a different project root.'
}

$stopped = 0
foreach ($record in @($state.processes) | Sort-Object { $_.role -eq 'backend' }) {
    $process = Get-Process -Id ([int]$record.pid) -ErrorAction SilentlyContinue
    if (-not $process) { continue }

    $recordedStart = [DateTimeOffset]::Parse([string]$record.started_at).UtcDateTime
    $actualStart = $process.StartTime.ToUniversalTime()
    if ($process.ProcessName -ne $record.process_name -or
        [Math]::Abs(($actualStart - $recordedStart).TotalSeconds) -gt 2) {
        Write-Warning "Skipping PID $($record.pid): it no longer matches the recorded $($record.role) process."
        continue
    }

    & taskkill.exe /PID ([string]$record.pid) /T /F 2>$null | Out-Null
    Wait-ProcessExit -ProcessId ([int]$record.pid)
    $stopped++
    if (-not $Quiet) { Write-Host "Stopped $($record.role) process tree (PID $($record.pid))." }
}

if ($KeepLogs) {
    Remove-Item -LiteralPath $stateFile -Force
} else {
    # Redirected stdout/stderr handles can outlive taskkill briefly on Windows.
    Remove-Item -LiteralPath $stateFile -Force
    Start-Sleep -Milliseconds 300
    Remove-RuntimeDirectory
}
if (-not $Quiet) { Write-Host "Stopped $stopped SmartDesk dev launcher process tree(s)." }
