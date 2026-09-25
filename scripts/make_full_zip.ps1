# Builds lehar-release-full.zip (Phase 15.1) - the SAME contents as
# lehar-release.zip (see make_release_zip.ps1 for the allowlist/exclude
# rationale) PLUS the real backend\.env, for sharing privately with a
# trusted recipient who should not have to obtain their own Groq key.
#
# Phase 15.2: backend\.env is the ONE file the app (and its Groq key) is
# configured from in BOTH modes - docker-compose.yml's "api" service loads it
# via env_file - so this zip's assistant works for the recipient whether
# START.bat picks Docker or the no-Docker fallback. The root .env is
# deliberately NOT included: it only holds this machine's Postgres/Grafana
# passwords and JWT_SECRET, and the recipient's START.bat generates their
# own.
#
# WARNING: this zip contains real secrets (backend\.env, including
# LLM_CLOUD_API_KEY). Never commit it, never upload it anywhere public -
# share the file directly with one trusted person only.
#
# Usage (from anywhere):
#   powershell -ExecutionPolicy Bypass -File scripts\make_full_zip.ps1
# or just double-click scripts\make_full_zip.bat.
#
# Output: lehar-release-full.zip at the project root.

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$ZipPath = Join-Path $ProjectRoot "lehar-release-full.zip"
$StagingDir = Join-Path $env:TEMP "lehar-release-full-staging"
$RealEnvPath = Join-Path $ProjectRoot "backend\.env"

Write-Output "Project root: $ProjectRoot"
Write-Output "Staging dir:  $StagingDir"

if (-not (Test-Path $RealEnvPath)) {
    throw "backend\.env not found - this script requires the real .env to build the full zip"
}

if (Test-Path $StagingDir) {
    Remove-Item -Recurse -Force $StagingDir
}
New-Item -ItemType Directory -Path $StagingDir | Out-Null

# Same allowlist as make_release_zip.ps1 - keep folder layout identical so
# START.bat/STARTUP-NO-DOCKER.bat sit at the same level as the normal
# release zip.
$IncludeDirs = @("backend", "frontend", "data", "docs", "monitoring", "scripts")
$IncludeFiles = @(
    ".env.example", ".gitattributes", ".dockerignore",
    "docker-compose.yml",
    "START.bat", "STOP.bat", "STARTUP-NO-DOCKER.bat", "start.sh",
    "README.md", "ARCHITECTURE.md", "CLAUDE.md", "PROGRESS.md",
    "pyproject.toml"
)

# Same excludes as make_release_zip.ps1 - the real backend\.env is copied
# in separately, deliberately, after this pass.
$ExcludeDirs = @(
    ".venv", "venv", "env",
    "mlruns", "mlartifacts",
    "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache", "htmlcov",
    ".vscode", ".idea"
)
$ExcludeFiles = @(
    ".env", "*.env",
    "*.db", "*.sqlite", "*.sqlite3",
    "*.pyc", ".coverage",
    "Thumbs.db", ".DS_Store"
)

Write-Output "Copying project files (allowlist: $($IncludeDirs -join ', '), + top-level docs/config)..."
foreach ($dir in $IncludeDirs) {
    $src = Join-Path $ProjectRoot $dir
    if (-not (Test-Path $src)) { continue }
    $dst = Join-Path $StagingDir $dir
    $robocopyArgs = @(
        $src, $dst,
        "/E", "/XD"
    ) + $ExcludeDirs + @("/XF") + $ExcludeFiles + @("/NFL", "/NDL", "/NJH", "/NJS", "/NP")
    robocopy @robocopyArgs | Out-Null
    # robocopy exit codes 0-7 are all success (bit flags for files copied
    # etc.); 8+ means a real failure.
    if ($LASTEXITCODE -ge 8) {
        throw "robocopy failed copying $dir (exit code $LASTEXITCODE)"
    }
}
foreach ($file in $IncludeFiles) {
    $src = Join-Path $ProjectRoot $file
    if (Test-Path $src) {
        Copy-Item $src (Join-Path $StagingDir $file) -Force
    }
}

# Deliberate addition vs. the normal release zip: the real backend\.env,
# at the same relative path it lives at in the project.
Write-Output "Adding real backend\.env (this is the private/full zip)..."
Copy-Item $RealEnvPath (Join-Path $StagingDir "backend\.env") -Force

# Phase 15.2: a working assistant is the point of this zip - say whether the
# packaged backend\.env actually carries a key (never printing the value).
$keyLine = Get-Content (Join-Path $StagingDir "backend\.env") | Where-Object { $_ -match '^LLM_CLOUD_API_KEY=' } | Select-Object -First 1
$keyValue = if ($keyLine) { ($keyLine -replace '^LLM_CLOUD_API_KEY=', '').Trim().Trim('"') } else { "" }
if ([string]::IsNullOrWhiteSpace($keyValue)) {
    Write-Output "WARNING: backend\.env has no LLM_CLOUD_API_KEY - the recipient's AI assistant will stay offline."
} else {
    Write-Output "backend\.env includes LLM_CLOUD_API_KEY (value not shown) - reaches the app with or without Docker."
}

# Sanity checks - verified, not trusted blindly:
#  - .env.example survived
#  - the real backend\.env IS present (this zip is meant to include it)
#  - no other .env (e.g. the root one), no .git, no .venv, no *.db, no
#    mlruns made it into the staging copy
foreach ($expected in @(".env.example", "backend\.env.example", "backend\.env")) {
    if (-not (Test-Path (Join-Path $StagingDir $expected))) {
        throw "Expected $expected in the staging copy but it's missing"
    }
}
$leaked = Get-ChildItem -Path $StagingDir -Recurse -Force -File |
    Where-Object { ($_.Name -eq ".env" -and $_.FullName -ne (Join-Path $StagingDir "backend\.env")) -or $_.Extension -in @(".db", ".sqlite", ".sqlite3") }
if ($leaked) {
    throw "Refusing to package - found files that should have been excluded: $($leaked.FullName -join ', ')"
}
if (Test-Path (Join-Path $StagingDir ".venv")) {
    throw "Refusing to package - .venv made it into the staging copy"
}
if (Test-Path (Join-Path $StagingDir ".git")) {
    throw "Refusing to package - .git made it into the staging copy"
}
if (Test-Path (Join-Path $StagingDir "mlruns")) {
    throw "Refusing to package - mlruns made it into the staging copy"
}

$runMeFirst = Join-Path $ProjectRoot "RUN-ME-FIRST.txt"
if (-not (Test-Path $runMeFirst)) {
    throw "RUN-ME-FIRST.txt not found at project root - create it before zipping"
}
Copy-Item $runMeFirst (Join-Path $StagingDir "RUN-ME-FIRST.txt") -Force

Write-Output "Compressing to $ZipPath ..."
if (Test-Path $ZipPath) {
    Remove-Item -Force $ZipPath
}
Compress-Archive -Path (Join-Path $StagingDir "*") -DestinationPath $ZipPath -CompressionLevel Optimal

Remove-Item -Recurse -Force $StagingDir

$sizeMb = [math]::Round((Get-Item $ZipPath).Length / 1MB, 1)
Write-Output ""
Write-Output "Done: $ZipPath ($sizeMb MB)"
Write-Output ""
Write-Output "=============================================================="
Write-Output "WARNING: lehar-release-full.zip CONTAINS SECRETS (.env) -"
Write-Output "share only privately, never upload publicly or commit."
Write-Output "=============================================================="
