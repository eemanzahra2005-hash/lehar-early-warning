# Phase 14: auto-creates the .env files a fresh checkout needs, with a real
# random JWT_SECRET (and Postgres/Grafana passwords for the Docker path) —
# so a stranger running START.bat / STARTUP-NO-DOCKER.bat never has to
# create or edit a .env file by hand. NEVER touches a .env that already
# exists (never overwrites a real config/secret a user already set) beyond
# filling in still-missing AI assistant settings in backend\.env below
# (Phase 15, Phase 15.2).
#
# Usage: powershell -NoProfile -ExecutionPolicy Bypass -File scripts\ensure_env.ps1

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot

function New-RandomSecret {
    # 48 random bytes, base64-encoded. Uses the instance Create()+GetBytes(byte[])
    # API, NOT the static RandomNumberGenerator.GetBytes(int) convenience method —
    # that overload was only added in .NET 6 and does not exist in the .NET
    # Framework that Windows PowerShell 5.1 (the "powershell" on every stock
    # Windows install, as opposed to PowerShell 7+'s "pwsh") runs on; calling it
    # there throws "does not contain a method named 'GetBytes'" — a real bug
    # found by actually running this script on a fresh machine.
    $bytes = New-Object byte[] 48
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $rng.GetBytes($bytes)
    [Convert]::ToBase64String($bytes)
}

function New-RandomPassword {
    # Alphanumeric only (no +/=) so it's safe to drop straight into a
    # docker-compose .env value with zero quoting concerns.
    [guid]::NewGuid().ToString("N")
}

# --- backend\.env: the app's own settings, in BOTH modes ---
# Read directly by the no-Docker (host) server, and loaded into the Docker
# "api" container by docker-compose.yml's env_file (Phase 15.2).
$backendEnv = Join-Path $RepoRoot "backend\.env"
$backendExample = Join-Path $RepoRoot "backend\.env.example"
if (-not (Test-Path $backendEnv)) {
    Write-Output "Creating backend\.env (first run) with a new random JWT_SECRET..."
    Copy-Item $backendExample $backendEnv
    $content = Get-Content $backendEnv
    $content = $content -replace '^JWT_SECRET=.*', ("JWT_SECRET=" + (New-RandomSecret))
    Set-Content -Path $backendEnv -Value $content
}

# --- root .env: `docker compose` variable substitution only (Docker path) ---
# Postgres/Grafana passwords, the container's JWT_SECRET, PORT. Not app
# settings - those belong in backend\.env above.
$rootEnv = Join-Path $RepoRoot ".env"
$rootExample = Join-Path $RepoRoot ".env.example"
if (-not (Test-Path $rootEnv)) {
    Write-Output "Creating .env (first run) with new random secrets..."
    Copy-Item $rootExample $rootEnv
    $content = Get-Content $rootEnv
    $content = $content -replace '^JWT_SECRET=.*', ("JWT_SECRET=" + (New-RandomSecret))
    $content = $content -replace '^POSTGRES_PASSWORD=.*', ("POSTGRES_PASSWORD=" + (New-RandomPassword))
    $content = $content -replace '^GF_SECURITY_ADMIN_PASSWORD=.*', ("GF_SECURITY_ADMIN_PASSWORD=" + (New-RandomPassword))
    Set-Content -Path $rootEnv -Value $content
}

# --- AI assistant setup (Phase 15; one-file rule since Phase 15.2) ---
# backend\.env is the ONE place for LLM_PROVIDER / LLM_CLOUD_API_KEY, in both
# modes. Before Phase 15.2 the Docker container only saw these via the ROOT
# .env, so a key added to backend\.env (as the docs said) stayed "offline"
# in Docker mode. Values are never printed.
function Get-EnvValue {
    param([string]$Path, [string]$Key)
    $line = Get-Content $Path | Where-Object { $_ -match "^$Key=" } | Select-Object -First 1
    if ($null -eq $line) { return $null }
    return ($line -replace "^$Key=", '').Trim('"')
}

function Set-EnvValue {
    param([string]$Path, [string]$Key, [string]$Value)
    $content = @(Get-Content $Path)
    if ($content -match "^$Key=") {
        $content = $content -replace "^$Key=.*", "$Key=$Value"
    } else {
        $content += "$Key=$Value"
    }
    Set-Content -Path $Path -Value $content
}

# Existing installs (and the 24 Aug workaround) may still have these in the
# root .env, which no longer reaches the container. Carry each one over into
# backend\.env - only when backend\.env has no value of its own - so a
# setup that works today keeps working after this change.
if (Test-Path $rootEnv) {
    foreach ($key in @("LLM_CLOUD_API_KEY", "LLM_PROVIDER")) {
        $rootValue = Get-EnvValue -Path $rootEnv -Key $key
        $backendValue = Get-EnvValue -Path $backendEnv -Key $key
        if ((-not [string]::IsNullOrWhiteSpace($rootValue)) -and [string]::IsNullOrWhiteSpace($backendValue)) {
            Set-EnvValue -Path $backendEnv -Key $key -Value $rootValue
            Write-Output "Moved $key from .env into backend\.env (the one file the app reads it from, with or without Docker)."
        }
    }
}

# If no Groq key is configured yet, ask once (a stranger otherwise has no
# way to discover LLM_CLOUD_API_KEY exists) - Read-Host -AsSecureString
# never echoes the typed key back to the console. Pressing Enter skips
# cleanly; everything except the chatbot works without a key.
$existingKey = Get-EnvValue -Path $backendEnv -Key "LLM_CLOUD_API_KEY"
if ([string]::IsNullOrWhiteSpace($existingKey)) {
    Write-Output ""
    Write-Output "Paste your Groq API key for the AI assistant (press Enter to skip - everything except the chatbot still works):"
    $plainKey = $null
    if ([Console]::IsInputRedirected) {
        # stdin isn't a real console (piped/redirected input, a scheduled
        # task, this project's own automated verification, ...) - Read-Host
        # would otherwise block waiting for a line that may never come.
        # Treat exactly like pressing Enter to skip; a real double-click
        # from Explorer always has a real console attached, so this never
        # affects the normal user path.
        Write-Output "(no interactive console detected - skipping automatically)"
    } else {
        try {
            $secure = Read-Host -AsSecureString
            if ($secure.Length -gt 0) {
                $bstr = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
                try {
                    $plainKey = [System.Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
                } finally {
                    [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
                }
            }
        } catch {
            # Belt-and-braces: still never crash setup even if IsInputRedirected
            # missed a non-interactive case (e.g. "powershell -NonInteractive").
            $plainKey = $null
        }
    }
    if (-not [string]::IsNullOrWhiteSpace($plainKey)) {
        # backend\.env only - it reaches the app in Docker mode (env_file) and
        # no-Docker mode alike, so there is no second copy to keep in sync.
        Set-EnvValue -Path $backendEnv -Key "LLM_CLOUD_API_KEY" -Value $plainKey
        Write-Output "Saved to backend\.env - the AI assistant will use your Groq key (with or without Docker)."
    } else {
        Write-Output "Skipped - add one later by editing backend\.env (LLM_CLOUD_API_KEY=...), then run STOP.bat and START.bat."
    }
}
