# Restore a custom-format pg_dump into an EMPTY PostgreSQL database.
#
# This intentionally does not pass --clean: it will never drop existing tables. Restore
# into a fresh database (for example a new Neon project/branch) so a mistake cannot erase
# production data.
#
# Usage:
#   .\scripts\restore-postgres.ps1 -DatabaseUrl "postgresql://..." -BackupFile ".\backups\rims-....dump"
#
# You must type RESTORE to proceed unless -ConfirmRestore is supplied.
#
# For a database on the same Windows host, use host.docker.internal instead of 127.0.0.1:
# pg_restore runs inside a container, so 127.0.0.1 would point at the container itself.

[CmdletBinding()]
param(
    [string]$DatabaseUrl,
    [Parameter(Mandatory = $true)]
    [string]$BackupFile,
    [switch]$ConfirmRestore
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker is required (the script uses the postgres:17 image for pg_restore)."
}

if (-not (Test-Path -LiteralPath $BackupFile)) {
    throw "Backup file not found: $BackupFile"
}
$backupItem = Get-Item -LiteralPath $BackupFile

if (-not $DatabaseUrl) {
    $secure = Read-Host -AsSecureString "Paste the TARGET (empty) PostgreSQL connection string"
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

if (-not $ConfirmRestore) {
    Write-Host "This will write into the target database:"
    Write-Host "  Backup: $($backupItem.FullName)"
    Write-Host "The target must be empty. Existing tables are NOT dropped."
    $answer = Read-Host "Type RESTORE to continue"
    if ($answer -ne "RESTORE") {
        throw "Restore cancelled."
    }
}

$mountDirectory = $backupItem.DirectoryName
$fileName = $backupItem.Name

$env:PGURL = $DatabaseUrl
$env:BACKUP_FILE = $fileName
try {
    Write-Host "Restoring $fileName ..."
    docker run --rm `
        -e PGURL `
        -e BACKUP_FILE `
        -v "${mountDirectory}:/backup" `
        postgres:17 `
        sh -c 'pg_restore --no-owner --no-privileges --exit-on-error --single-transaction --dbname "$PGURL" "/backup/$BACKUP_FILE"'
    if ($LASTEXITCODE -ne 0) {
        throw "pg_restore failed with exit code $LASTEXITCODE."
    }
}
finally {
    Remove-Item Env:\PGURL -ErrorAction SilentlyContinue
    Remove-Item Env:\BACKUP_FILE -ErrorAction SilentlyContinue
}

Write-Host "Restore complete."
