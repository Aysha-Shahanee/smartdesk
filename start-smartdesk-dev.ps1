[CmdletBinding()]
param(
    [switch]$SkipGitHubWebhookUpdate
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$projectRoot = $PSScriptRoot
$backendDir = Join-Path $projectRoot 'backend'
$frontendDir = Join-Path $projectRoot 'frontend'
$runtimeDir = Join-Path $projectRoot '.smartdesk-dev'
$stateFile = Join-Path $runtimeDir 'processes.json'
$backendUrl = 'http://127.0.0.1:8000'
$frontendUrl = 'http://localhost:5173'
$webhookPath = '/api/v1/integrations/github/webhook'
$processRecords = [System.Collections.Generic.List[object]]::new()
$ownsState = $false
$python = $null

function Get-DotEnvValue {
    param([string]$Path, [string]$Name)

    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    foreach ($line in Get-Content -LiteralPath $Path) {
        if ($line -notmatch '^\s*([^#][^=]*)=(.*)$') { continue }
        if ($Matches[1].Trim() -ne $Name) { continue }
        $value = $Matches[2].Trim()
        if ($value.Length -ge 2 -and
            (($value.StartsWith('"') -and $value.EndsWith('"')) -or
             ($value.StartsWith("'") -and $value.EndsWith("'")))) {
            $value = $value.Substring(1, $value.Length - 2)
        }
        return $value
    }
    return $null
}

function Get-ConfiguredValue {
    param([string]$Name)

    $processValue = [Environment]::GetEnvironmentVariable($Name, 'Process')
    if (-not [string]::IsNullOrWhiteSpace($processValue)) { return $processValue }
    return Get-DotEnvValue -Path (Join-Path $backendDir '.env') -Name $Name
}

function Resolve-Executable {
    param([string]$Description, [string[]]$Candidates, [string]$CommandName)

    foreach ($candidate in $Candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }
    if ($CommandName) {
        $command = Get-Command $CommandName -ErrorAction SilentlyContinue
        if ($command) { return $command.Source }
    }
    throw "$Description was not found. Install/configure it locally before running this launcher."
}

function Save-ProcessState {
    New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null
    @{
        project_root = $projectRoot
        created_at = [DateTimeOffset]::UtcNow.ToString('o')
        processes = @($processRecords)
    } | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $stateFile -Encoding UTF8
}

function Register-DevProcess {
    param([System.Diagnostics.Process]$Process, [string]$Role)

    $Process.Refresh()
    $processRecords.Add([pscustomobject]@{
        role = $Role
        pid = $Process.Id
        process_name = $Process.ProcessName
        started_at = $Process.StartTime.ToUniversalTime().ToString('o')
    })
    $script:ownsState = $true
    Save-ProcessState
}

function Start-LoggedProcess {
    param(
        [string]$Role,
        [string]$FilePath,
        [string[]]$ArgumentList,
        [string]$WorkingDirectory
    )

    $stdout = Join-Path $runtimeDir "$Role.stdout.log"
    $stderr = Join-Path $runtimeDir "$Role.stderr.log"
    $process = Start-Process -FilePath $FilePath -ArgumentList $ArgumentList `
        -WorkingDirectory $WorkingDirectory -PassThru -WindowStyle Hidden `
        -RedirectStandardOutput $stdout -RedirectStandardError $stderr
    Register-DevProcess -Process $process -Role $Role
    return $process
}

function Stop-StartedProcesses {
    if (Test-Path -LiteralPath (Join-Path $projectRoot 'stop-smartdesk-dev.ps1')) {
        & (Join-Path $projectRoot 'stop-smartdesk-dev.ps1') -Quiet -KeepLogs
    }
}

function Wait-HttpStatus {
    param(
        [string]$Url,
        [int[]]$ExpectedStatus,
        [int]$TimeoutSeconds = 60,
        [string]$Method = 'GET',
        [string]$Body = $null
    )

    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        $request = [Net.HttpWebRequest]::Create($Url)
        $request.Proxy = $null
        $request.Method = $Method
        $request.Timeout = 5000
        $request.ReadWriteTimeout = 5000
        try {
            if (-not [string]::IsNullOrEmpty($Body)) {
                $bytes = [Text.Encoding]::UTF8.GetBytes($Body)
                $request.ContentType = 'application/json'
                $request.ContentLength = $bytes.Length
                $stream = $request.GetRequestStream()
                try { $stream.Write($bytes, 0, $bytes.Length) } finally { $stream.Dispose() }
            }
            $response = $request.GetResponse()
            try { $status = [int]$response.StatusCode } finally { $response.Dispose() }
        } catch [Net.WebException] {
            $status = if ($_.Exception.Response) {
                [int]$_.Exception.Response.StatusCode
            } else {
                0
            }
        }
        if ($ExpectedStatus -contains $status) { return $status }
        Start-Sleep -Milliseconds 500
    } while ([DateTime]::UtcNow -lt $deadline)
    throw "Timed out waiting for $Url to return status $($ExpectedStatus -join ' or ')."
}

function New-GitHubAppJwt {
    param([string]$AppId, [string]$PrivateKey)

    $inputJson = @{ app_id = $AppId; private_key = $PrivateKey } | ConvertTo-Json -Compress
    $jwtCode = @'
import json, sys
from github_data_collection.github_app import create_app_jwt
config = json.load(sys.stdin)
sys.stdout.write(create_app_jwt(config['app_id'], config['private_key']))
'@
    try {
        $jwt = $inputJson | & $script:python -c $jwtCode
        if ($LASTEXITCODE -ne 0 -or $jwt -notmatch '^[^.]+\.[^.]+\.[^.]+$') {
            throw 'Existing GitHub App JWT helper could not create a valid token.'
        }
        return $jwt
    } finally {
        $inputJson = $null
    }
}

function Update-GitHubAppWebhookUrl {
    param([string]$WebhookUrl, [string]$AppId, [string]$PrivateKey)

    $jwt = New-GitHubAppJwt -AppId $AppId -PrivateKey $PrivateKey
    $headers = @{
        Accept = 'application/vnd.github+json'
        Authorization = "Bearer $jwt"
        'X-GitHub-Api-Version' = '2022-11-28'
        'User-Agent' = 'SmartDesk-Local-Dev-Launcher'
    }
    try {
        # Fetch first to prove this JWT addresses the intended current App.
        $before = Invoke-RestMethod -Uri 'https://api.github.com/app/hook/config' `
            -Headers $headers -Method Get -TimeoutSec 20

        # PATCH only the URL. Omitting secret/content_type/insecure_ssl preserves them;
        # permissions, events and callback/setup URLs are not part of this endpoint.
        $body = @{ url = $WebhookUrl } | ConvertTo-Json -Compress
        $after = Invoke-RestMethod -Uri 'https://api.github.com/app/hook/config' `
            -Headers $headers -Method Patch -ContentType 'application/json' `
            -Body $body -TimeoutSec 20
        if ($after.url -ne $WebhookUrl) {
            throw 'GitHub returned a different webhook URL than requested.'
        }
        if ($before.content_type -ne $after.content_type -or
            [string]$before.insecure_ssl -ne [string]$after.insecure_ssl) {
            throw 'GitHub changed a webhook setting other than the URL.'
        }
    } finally {
        $jwt = $null
        $headers.Authorization = $null
    }
}

try {
    if (Test-Path -LiteralPath $stateFile) {
        throw 'SmartDesk dev launcher state already exists. Run .\stop-smartdesk-dev.ps1 first.'
    }

    $python = Resolve-Executable -Description 'A SmartDesk Python environment' -Candidates @(
        (Join-Path $projectRoot '.venv\Scripts\python.exe'),
        (Join-Path $backendDir '.venv\Scripts\python.exe'),
        (Join-Path $backendDir 'venv\Scripts\python.exe')
    ) -CommandName 'python'
    $cloudflared = Resolve-Executable -Description 'cloudflared' -Candidates @(
        (Join-Path $projectRoot '.tools\cloudflared.exe'),
        (Join-Path $projectRoot '.cloudflared\cloudflared.exe')
    ) -CommandName 'cloudflared'
    $npm = Resolve-Executable -Description 'npm' -Candidates @(
        (Join-Path $projectRoot '.tools\node-v24.18.0-win-x64\npm.cmd')
    ) -CommandName 'npm'

    foreach ($port in 8000, 5173) {
        $listeners = @(
            Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue |
                Where-Object { $null -ne $_ }
        )
        if ($listeners.Count -gt 0) {
            throw "Port $port is already in use. Stop the existing process before running this launcher."
        }
    }

    $appId = $null
    $privateKey = $null
    if (-not $SkipGitHubWebhookUpdate) {
        $appId = Get-ConfiguredValue 'SMARTDESK_GITHUB_APP_ID'
        $privateKey = Get-ConfiguredValue 'SMARTDESK_GITHUB_APP_PRIVATE_KEY'
        $webhookSecret = Get-ConfiguredValue 'SMARTDESK_GITHUB_WEBHOOK_SECRET'
        $missing = @()
        if ([string]::IsNullOrWhiteSpace($appId)) { $missing += 'SMARTDESK_GITHUB_APP_ID' }
        if ([string]::IsNullOrWhiteSpace($privateKey)) { $missing += 'SMARTDESK_GITHUB_APP_PRIVATE_KEY' }
        if ([string]::IsNullOrWhiteSpace($webhookSecret)) { $missing += 'SMARTDESK_GITHUB_WEBHOOK_SECRET' }
        $webhookSecret = $null
        if ($missing.Count -gt 0) {
            throw "GitHub App webhook update cannot run safely. Missing: $($missing -join ', ') in process environment or backend/.env."
        }
        $privateKey = $privateKey.Replace('\n', "`n")
    }

    New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null

    Write-Host 'Running database migrations...'
    Push-Location $backendDir
    try {
        & $python -m alembic upgrade head
        if ($LASTEXITCODE -ne 0) { throw "Alembic upgrade failed with exit code $LASTEXITCODE." }
    } finally {
        Pop-Location
    }

    $backendProcess = Start-LoggedProcess -Role 'backend' -FilePath $python `
        -ArgumentList @('-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8000') `
        -WorkingDirectory $backendDir

    $nodeDir = Split-Path -Parent $npm
    $oldPath = $env:PATH
    $oldElectronRunAsNode = [Environment]::GetEnvironmentVariable('ELECTRON_RUN_AS_NODE', 'Process')
    try {
        $env:PATH = "$nodeDir;$oldPath"
        [Environment]::SetEnvironmentVariable('ELECTRON_RUN_AS_NODE', $null, 'Process')
        $frontendProcess = Start-LoggedProcess -Role 'frontend' -FilePath $npm `
            -ArgumentList @('run', 'dev') -WorkingDirectory $frontendDir
    } finally {
        $env:PATH = $oldPath
        [Environment]::SetEnvironmentVariable('ELECTRON_RUN_AS_NODE', $oldElectronRunAsNode, 'Process')
    }

    $tunnelProcess = Start-LoggedProcess -Role 'tunnel' -FilePath $cloudflared `
        -ArgumentList @('tunnel', '--url', $backendUrl, '--no-autoupdate') `
        -WorkingDirectory $projectRoot

    Wait-HttpStatus -Url "$backendUrl/" -ExpectedStatus 200 -TimeoutSeconds 240 | Out-Null
    Wait-HttpStatus -Url "$frontendUrl/" -ExpectedStatus 200 -TimeoutSeconds 120 | Out-Null

    $tunnelDeadline = [DateTime]::UtcNow.AddSeconds(90)
    $tunnelUrl = $null
    do {
        $tunnelProcess.Refresh()
        if ($tunnelProcess.HasExited) { throw 'cloudflared exited before producing a tunnel URL.' }
        foreach ($logName in 'tunnel.stdout.log', 'tunnel.stderr.log') {
            $logPath = Join-Path $runtimeDir $logName
            if (-not (Test-Path -LiteralPath $logPath)) { continue }
            $match = Select-String -Path $logPath -Pattern 'https://[a-z0-9-]+\.trycloudflare\.com' -AllMatches |
                Select-Object -Last 1
            if ($match) {
                $tunnelUrl = $match.Matches[-1].Value
                break
            }
        }
        if (-not $tunnelUrl) { Start-Sleep -Milliseconds 500 }
    } while (-not $tunnelUrl -and [DateTime]::UtcNow -lt $tunnelDeadline)
    if (-not $tunnelUrl) { throw 'Timed out waiting for cloudflared to produce a Quick Tunnel URL.' }

    $webhookUrl = "$tunnelUrl$webhookPath"
    Wait-HttpStatus -Url "$tunnelUrl/" -ExpectedStatus 200 -TimeoutSeconds 60 | Out-Null
    Wait-HttpStatus -Url $webhookUrl -ExpectedStatus 401 -TimeoutSeconds 30 -Method POST -Body '{}' | Out-Null

    $webhookUpdated = $false
    if (-not $SkipGitHubWebhookUpdate) {
        Update-GitHubAppWebhookUrl -WebhookUrl $webhookUrl -AppId $appId -PrivateKey $privateKey
        $webhookUpdated = $true
    }
    $privateKey = $null

    Write-Host ''
    Write-Host "Backend:       $backendUrl"
    Write-Host "Frontend:      $frontendUrl"
    Write-Host "Tunnel:        $tunnelUrl"
    Write-Host "GitHub webhook: $webhookUrl"
    if ($SkipGitHubWebhookUpdate) {
        Write-Warning 'GitHub webhook update was explicitly skipped.'
    } elseif ($webhookUpdated) {
        Write-Host 'GitHub webhook URL updated successfully.' -ForegroundColor Green
    }
    Write-Host 'Local backend, public tunnel, and unsigned-webhook checks passed.' -ForegroundColor Green
    Write-Host 'Run .\stop-smartdesk-dev.ps1 to stop only these launcher-owned processes.'
} catch {
    $privateKey = $null
    [Console]::Error.WriteLine("SmartDesk dev startup failed: $($_.Exception.Message)")
    if ($ownsState) { Stop-StartedProcesses }
    exit 1
}
