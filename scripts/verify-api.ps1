# Verify the deployed API, the database, CORS and both pricing models.
#
#   .\scripts\verify-api.ps1
#   .\scripts\verify-api.ps1 -BaseUrl "https://api.rimssuppliesandhardware.co.ke" -SkipQuotes
#
# Quote checks create real quote rows in the production database and call the public
# OSRM/Nominatim services. Use -SkipQuotes when you only want a health check.

[CmdletBinding()]
param(
    [string]$BaseUrl = "https://api.rimssuppliesandhardware.co.ke",
    [string]$VercelOrigin = "https://rims-delivery-ui.vercel.app",
    [switch]$SkipQuotes
)

$ErrorActionPreference = "Stop"
$BaseUrl = $BaseUrl.TrimEnd("/")
$failures = 0
$warnings = 0

function Pass([string]$message) {
    Write-Host "PASS  $message" -ForegroundColor Green
}

function Fail([string]$message) {
    $script:failures++
    Write-Host "FAIL  $message" -ForegroundColor Red
}

function Warn([string]$message) {
    $script:warnings++
    Write-Host "WARN  $message" -ForegroundColor Yellow
}

function Get-Json([string]$path) {
    return Invoke-RestMethod -Method Get -Uri "$BaseUrl$path" -TimeoutSec 60
}

Write-Host "Target: $BaseUrl"
Write-Host ""

try {
    $health = Get-Json "/health"
    if ($health.status -eq "ok") { Pass "/health" } else { Fail "/health returned $($health.status)" }
}
catch {
    Fail "/health: $($_.Exception.Message)"
}
if ($health) {
    if ($health.environment -ne "production") { Warn "/health environment is '$($health.environment)', not production" }
    if ($health.version -ne "1.0.0") { Warn "/health version is $($health.version)" }
}

try {
    $ready = Get-Json "/ready"
    if ($ready.ready -eq $true) { Pass "/ready (database, cache, pricing)" } else { Fail "/ready is degraded: $($ready.checks | ConvertTo-Json -Compress)" }
    if ($ready.checks.database -eq "ok") { Pass "database reachable" } else { Fail "database check: $($ready.checks.database)" }
    if ($ready.pricingConfigured -eq $true) {
        Pass "active pricing version: $($ready.activePricingVersion) ($($ready.destinationCount) destinations)"
    }
    else {
        Fail "no active pricing version is configured"
    }
}
catch {
    Fail "/ready: $($_.Exception.Message)"
}

try {
    $config = Get-Json "/api/v1/public/config"
    if ($config.company.name) { Pass "public config: $($config.company.name)" } else { Fail "public config has no company name" }
}
catch {
    Fail "/api/v1/public/config: $($_.Exception.Message)"
}

try {
    $locations = @(Invoke-RestMethod -Method Get -Uri "$BaseUrl/api/v1/public/locations/search?q=naivasha&limit=3" -TimeoutSec 60)
    if ($locations.Count -gt 0) { Pass "location search returned $($locations.Count) result(s)" } else { Warn "location search returned no results (provider may be rate limiting)" }
}
catch {
    Warn "location search failed: $($_.Exception.Message)"
}

try {
    $preflight = Invoke-WebRequest -Method Options -Uri "$BaseUrl/api/v1/public/config" -Headers @{
        Origin                        = $VercelOrigin
        "Access-Control-Request-Method" = "GET"
    } -TimeoutSec 60
    $allowed = $preflight.Headers["Access-Control-Allow-Origin"]
    if ($allowed -eq $VercelOrigin) {
        Pass "CORS allows $VercelOrigin"
    }
    else {
        Fail "CORS does not allow $VercelOrigin (Access-Control-Allow-Origin: '$allowed')"
    }
}
catch {
    Fail "CORS preflight failed: $($_.Exception.Message)"
}

function Wait-ForQuote([string]$id) {
    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Seconds 3
        $quote = Get-Json "/api/v1/public/quotes/$id"
        if ($quote.status -notin @("processing", "pending")) {
            return $quote
        }
    }
    return $quote
}

function Invoke-QuoteTest([string]$name, [hashtable]$body, [string]$expectedModel) {
    try {
        $payload = $body | ConvertTo-Json -Depth 6
        $created = Invoke-RestMethod -Method Post -Uri "$BaseUrl/api/v1/public/quotes" -ContentType "application/json" -Body $payload -TimeoutSec 60
        $quote = Wait-ForQuote $created.id
        $detail = "status=$($quote.status) model=$($quote.pricingModel) fee=$($quote.fee.amount) failure=$($quote.failure.code)"
        if ($quote.status -eq "completed" -and $quote.pricingModel -eq $expectedModel -and $quote.fee.amount) {
            Pass "$name -> $detail"
        }
        elseif ($quote.status -eq "needs_review" -and $name -eq "distance quote") {
            Warn "$name needs manual review (routing/provider unavailable): $detail"
        }
        else {
            Fail "$name -> $detail"
        }
    }
    catch {
        Fail "${name}: $($_.Exception.Message)"
    }
}

if (-not $SkipQuotes) {
    Write-Host ""
    Invoke-QuoteTest "fixed-destination quote (Olkaria)" @{
        position   = @{ lat = -0.8859869; lng = 36.2695525 }
        label      = "Olkaria, Maiella ward, Naivasha, Nakuru, Kenya"
        locationId = "osm-nominatim:38186639"
        resolved   = $true
        reference  = "verify-api-fixed"
    } "fixed_destination"

    Invoke-QuoteTest "distance quote (Nairobi, outside price list)" @{
        position  = @{ lat = -1.2864; lng = 36.8172 }
        label     = "Nairobi, Kenya"
        resolved  = $true
        reference = "verify-api-distance"
    } "distance_based"
}

Write-Host ""
if ($failures -gt 0) {
    Write-Host "$failures check(s) failed, $warnings warning(s)." -ForegroundColor Red
    exit 1
}
Write-Host "All required checks passed ($warnings warning(s))." -ForegroundColor Green
