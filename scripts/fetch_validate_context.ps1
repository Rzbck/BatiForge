param(
    [string]$Root = "E:\_Project\_ProjectPython\BatiForge",
    [string]$Workspace = "espace-des-forges",
    [double]$MarginM = 25.0,
    [double]$CellSizeM = 0.5
)

$ErrorActionPreference = "Stop"
Set-Location $Root

$Python = "$Root\.venv\Scripts\python.exe"
$Work = "$Root\workspaces\$Workspace"
$Foot = "$Work\40_mesh\footprint-v1\rnb-footprint.json"
$TileDir = "$Work\10_lidar\context_tiles"
$Manifest = "$TileDir\context-lidar-fetch.json"

foreach ($Path in @($Python,$Foot)) {
    if (-not (Test-Path -LiteralPath $Path)) { throw "Absent : $Path" }
}

Write-Host "`n===== BATIFORGE OFFICIAL CONTEXT LIDAR =====" -ForegroundColor Cyan
Write-Host "Workspace : $Workspace"
Write-Host "Margin    : $MarginM m"
Write-Host "Source    : IGN Geoplateforme WFS / official LiDAR HD tiles"

& $Python -m batiforge.reconstruction.lidar_context_fetch `
    --footprint-json $Foot `
    --output-dir $TileDir `
    --margin-m $MarginM `
    --manifest $Manifest
if ($LASTEXITCODE -ne 0) { throw "Telechargement LiDAR contexte echoue." }

$M = Get-Content -LiteralPath $Manifest -Raw | ConvertFrom-Json
Write-Host "`n===== TUILES OFFICIELLES =====" -ForegroundColor Green
$Rows = foreach ($Tile in $M.tiles) {
    [PSCustomObject]@{
        Status = $Tile.status
        Fichier = $Tile.name
        MB = [math]::Round([double]$Tile.bytes / 1MB, 2)
        Projection = $Tile.projection
    }
}
$Rows | Format-Table -AutoSize

Write-Host "`n===== RECONSTRUCTION CONTEXTE =====" -ForegroundColor Cyan
& "$Root\scripts\validate_context_ground.ps1" `
    -Root $Root `
    -Workspace $Workspace `
    -MarginM $MarginM `
    -CellSizeM $CellSizeM
if ($LASTEXITCODE -ne 0) { throw "Validation contexte echouee." }
