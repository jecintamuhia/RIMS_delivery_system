# Print row counts and active pricing versions for a PostgreSQL database.
#
#   .\scripts\check-db.ps1 -DatabaseUrl "postgresql://..."
#
# Prompts for the URL if omitted. Uses the postgres:17 image through Docker; the URL is
# passed as an environment variable, never on the command line.
#
# For a database on the same Windows host, use host.docker.internal instead of 127.0.0.1.

[CmdletBinding()]
param(
    [string]$DatabaseUrl
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker is required (the script uses the postgres:17 image for psql)."
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

$sql = @'
SELECT 'users' AS object, count(*) AS rows FROM users
UNION ALL SELECT 'pricing_versions', count(*) FROM pricing_versions
UNION ALL SELECT 'pricing_rules', count(*) FROM pricing_rules
UNION ALL SELECT 'dynamic_pricing_versions', count(*) FROM dynamic_pricing_versions
UNION ALL SELECT 'destinations', count(*) FROM destinations
UNION ALL SELECT 'destination_aliases', count(*) FROM destination_aliases
UNION ALL SELECT 'delivery_origins', count(*) FROM delivery_origins
UNION ALL SELECT 'quotes', count(*) FROM quotes
UNION ALL SELECT 'quote_calculations', count(*) FROM quote_calculations
ORDER BY object;
SELECT 'active_fixed_version' AS check_name, label AS value FROM pricing_versions WHERE status = 'active';
SELECT 'active_distance_version' AS check_name, label AS value FROM dynamic_pricing_versions WHERE status = 'active';
SELECT 'alembic_head' AS check_name, version_num AS value FROM alembic_version;
'@

$env:PGURL = $DatabaseUrl
$command = @"
psql "`$PGURL" -v ON_ERROR_STOP=1 <<'SQL'
$sql
SQL
"@
try {
    docker run --rm -e PGURL postgres:17 sh -c $command
    if ($LASTEXITCODE -ne 0) {
        throw "psql failed with exit code $LASTEXITCODE."
    }
}
finally {
    Remove-Item Env:\PGURL -ErrorAction SilentlyContinue
}
