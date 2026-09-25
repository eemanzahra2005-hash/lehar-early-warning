# Builds lehar-release.zip (Phase 13) - a shareable, self-contained copy of
# everything needed to run LEHAR on another machine via
# Docker Compose: application code, frontend, trained model artifacts,
# compose/monitoring config, START.bat/STOP.bat/start.sh, docs, and
# RUN-ME-FIRST.txt. Excludes .venv, .env (real secrets), .git, mlruns/
# mlartifacts, and caches - none of those are needed to RUN the app, and
# .env in particular must never be redistributed (see CLAUDE.md rule 3).
#
# Usage (from anywhere):
#   powershell -ExecutionPolicy Bypass -File scripts\make_release_zip.ps1
# or just double-click scripts\make_release_zip.bat.
#
# Output: lehar-release.zip at the project root.

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$ZipPath = Join-Path $ProjectRoot "lehar-release.zip"
$StagingDir = Join-Path $env:TEMP "lehar-release-staging"

Write-Output "Project root: $ProjectRoot"
Write-Output "Staging dir:  $StagingDir"

if (Test-Path $StagingDir) {
    Remove-Item -Recurse -Force $StagingDir
}
New-Item -ItemType Directory -Path $StagingDir | Out-Null

# ALLOWLIST of top-level project entries to include, rather than "copy
# everything and exclude a blocklist" - a project root can accumulate
# random stray files over time (scratch output, a broken redirect from a
# past session, an editor swap file) that have nothing to do with running
# the app; a blocklist only catches the ones we thought to name, an
# allowlist can't leak anything we didn't explicitly ask for. Verified
# during Phase 13 development: a blocklist approach let a garbled stray
# file from an earlier session ("ersuserDesktop...activate.bat", a captured
# terminal pager screen, clearly accidental debris) sneak into the zip.
$IncludeDirs = @("backend", "frontend", "data", "docs", "monitoring", "scripts")
$IncludeFiles = @(
    ".env.example", ".gitattributes", ".dockerignore",
    "docker-compose.yml",
    "START.bat", "STOP.bat", "STARTUP-NO-DOCKER.bat", "start.sh",
    "README.md", "ARCHITECTURE.md", "CLAUDE.md", "PROGRESS.md",
    "pyproject.toml"
)

# Within backend/ and frontend/, still exclude local dev state / caches /
# secrets - see backend/Dockerfile's .dockerignore for the same list used
# when building the Docker image.
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

# Sanity checks - verified, not trusted blindly:
#  - .env.example survived (robocopy's "*.env" exclude pattern does NOT
#    match ".env.example", which must end in exactly ".env")
#  - no real .env, no .git, no .venv, no *.db made it into the staging
#    copy - a redistributed secret or a stale local database would be a
#    real problem, not just clutter
foreach ($expected in @(".env.example", "backend\.env.example")) {
    if (-not (Test-Path (Join-Path $StagingDir $expected))) {
        throw "Expected $expected in the staging copy but it's missing"
    }
}
$leaked = Get-ChildItem -Path $StagingDir -Recurse -Force -File |
    Where-Object { $_.Name -eq ".env" -or $_.Extension -in @(".db", ".sqlite", ".sqlite3") }
if ($leaked) {
    throw "Refusing to package - found files that should have been excluded: $($leaked.FullName -join ', ')"
}
if (Test-Path (Join-Path $StagingDir ".venv")) {
    throw "Refusing to package - .venv made it into the staging copy"
}
if (Test-Path (Join-Path $StagingDir ".git")) {
    throw "Refusing to package - .git made it into the staging copy"
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
