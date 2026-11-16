# Back up the production PostgreSQL database without installing psql/pg_dump.
#
# Uses the official postgres:17 image through Docker. The connection string is passed to
# the container as an environment variable, not on the command line, so it does not appear
# in shell history or process listings.
#
# Usage (from the repository root, or any directory):
#   .\scripts\backup-postgres.ps1 -DatabaseUrl "postgresql://..."
#
# If -DatabaseUrl is omitted the script prompts for it without echoing it. The dump is
# written to .\backups\ and that directory is gitignored.
#
# For a database on the same Windows host (for example a local Docker Postgres), use
# host.docker.internal instead of 127.0.0.1: the command runs inside a container, so
# 127.0.0.1 would point at the container itself.

[CmdletBinding()]
param(
    [string]$DatabaseUrl,
    [string]$OutputDirectory
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker is required (the script uses the postgres:17 image for pg_dump)."
}

if (-not $DatabaseUrl) {
    $secure = Read-Host -AsSecureString "Paste the PostgreSQL connection string"
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try {
        $DatabaseUrl = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    }
}

if (-not $DatabaseUrl) {
    throw "No database URL supplied."
}

$repoRoot = Split-Path -Parent $PSScriptRoot
if (-not $OutputDirectory) {
    $OutputDirectory = Join-Path $repoRoot "backups"
}
$OutputDirectory = (New-Item -ItemType Directory -Force -Path $OutputDirectory).FullName

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$fileName = "rims-$timestamp.dump"
$filePath = Join-Path $OutputDirectory $fileName

$env:PGURL = $DatabaseUrl
$env:BACKUP_FILE = $fileName
try {
    Write-Host "Dumping database to $filePath ..."
    docker run --rm `
        -e PGURL `
        -e BACKUP_FILE `
        -v "${OutputDirectory}:/backup" `
        postgres:17 `
        sh -c 'pg_dump --format=custom --no-owner --no-privileges --dbname "$PGURL" --file "/backup/$BACKUP_FILE"'
    if ($LASTEXITCODE -ne 0) {
        throw "pg_dump failed with exit code $LASTEXITCODE. No backup was created."
    }
}
finally {
    Remove-Item Env:\PGURL -ErrorAction SilentlyContinue
    Remove-Item Env:\BACKUP_FILE -ErrorAction SilentlyContinue
}

$item = Get-Item -LiteralPath $filePath
$hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $filePath).Hash
Write-Host ""
Write-Host "Backup complete."
Write-Host "  File:   $($item.FullName)"
Write-Host "  Size:   $([math]::Round($item.Length / 1MB, 2)) MB"
Write-Host "  SHA256: $hash"
Write-Host ""
Write-Host "Keep this file outside git (backups/ is gitignored). Restore with:"
Write-Host "  .\scripts\restore-postgres.ps1 -DatabaseUrl `"<neon-url>`" -BackupFile `"$($item.FullName)`""
