param(
    [string]$OutputDir = "generated-client"
)

$openapiPath = Join-Path (Resolve-Path ".").Path "data/openapi.json"
if (-not (Test-Path $openapiPath)) {
    python scripts/export_openapi.py
}

openapi-python-client generate --path $openapiPath --output-path $OutputDir
