#Requires -Version 5.1
$ErrorActionPreference = 'Stop'

# Cleanse Windows release script.
# Builds the Windows backend + Electron app, then uploads NSIS + ZIP
# artifacts and latest.yml to the existing GitHub release for this version.
#
# Usage (from repo root):
#   pwsh -File scripts/release.ps1
#
# Assumes:
#   - `gh` CLI is installed and authenticated
#   - The macOS release has already created the tag (v<version>) on GitHub
#   - You are on master with no uncommitted changes

$Version = (Get-Content (Join-Path $PSScriptRoot '..\package.json') | ConvertFrom-Json).version
$Tag = "v$Version"

Write-Host "=== Cleanse Windows Release $Tag ==="
Write-Host ''

$branch = git branch --show-current
if ($branch -ne 'master') {
    Write-Error "Must be on master branch (currently on '$branch')"
    exit 1
}

if ((git diff-index --quiet HEAD -- 2>$null; $LASTEXITCODE) -ne 0) {
    Write-Error 'Uncommitted changes detected. Commit or stash first.'
    exit 1
}

$gh = Get-Command gh -ErrorAction SilentlyContinue
if (-not $gh) {
    Write-Error 'gh CLI not found. Install from https://cli.github.com/ (or winget install GitHub.cli).'
    exit 1
}

# Clean previous Windows artifacts
$DistDir = Join-Path $PSScriptRoot '..\dist'
Get-ChildItem $DistDir -Filter '*.exe' -ErrorAction SilentlyContinue | Remove-Item -Force
Get-ChildItem $DistDir -Filter 'latest.yml' -ErrorAction SilentlyContinue | Remove-Item -Force
Get-ChildItem $DistDir -Filter 'cleanse-*-x64.zip' -ErrorAction SilentlyContinue | Remove-Item -Force

Write-Host '=== Building Windows (x64) ==='
npm run build:win
if ($LASTEXITCODE -ne 0) { throw 'build:win failed' }

$artifacts = @()
$artifacts += Get-ChildItem $DistDir -Filter "*-$Version-x64.exe" -ErrorAction SilentlyContinue
$artifacts += Get-ChildItem $DistDir -Filter "*-$Version-x64.zip" -ErrorAction SilentlyContinue
$latestYml = Get-ChildItem $DistDir -Filter 'latest.yml' -ErrorAction SilentlyContinue | Select-Object -First 1

if (-not $artifacts) {
    Write-Error 'No Windows artifacts found in dist/. Build output unexpected.'
    exit 1
}
if (-not $latestYml) {
    Write-Error 'dist\latest.yml not generated. electron-builder publish config may be missing.'
    exit 1
}

Write-Host ''
Write-Host 'Artifacts to upload:'
foreach ($a in $artifacts) {
    '{0} ({1:N1} MB)' -f $a.Name, ($a.Length / 1MB) | Write-Host
}
$latestYml.Name | Write-Host

# Upload to existing release (mac release already created it)
$uploadPaths = @()
$uploadPaths += $artifacts | ForEach-Object { $_.FullName }
$uploadPaths += $latestYml.FullName

Write-Host ''
Write-Host "Uploading to GitHub release $Tag..."
& gh release upload $Tag @uploadPaths --clobber
if ($LASTEXITCODE -ne 0) { throw "gh release upload failed ($LASTEXITCODE)" }

Write-Host ''
Write-Host "Windows artifacts uploaded to $Tag!"
Write-Host "https://github.com/djnewage/cleanse/releases/tag/$Tag"
