param(
    [string]$Root = "E:\_Project\_ProjectPython\BatiForge",
    [string]$Workspace = "espace-des-forges",
    [string]$BuildingObj = "",
    [string]$TerrainObj = "",
    [string]$BlenderExe = ""
)

$ErrorActionPreference = "Stop"
Set-Location $Root

$Work = "$Root\workspaces\$Workspace"
$FacadeRoot = "$Work\70_facade"
$EvidenceRoot = "$FacadeRoot\evidence"
$PhotoRoot = "$EvidenceRoot\photos_original"
$PreviewRoot = "$FacadeRoot\preview"
$Blend = "$PreviewRoot\batiforge-facade-preview.blend"
$Render = "$PreviewRoot\batiforge-facade-preview.png"
$Manifest = "$PreviewRoot\batiforge-facade-preview.json"
$Guide = "$EvidenceRoot\README_CAPTURE.txt"
$BlenderScript = "$Root\scripts\blender\build_facade_preview.py"

foreach ($Dir in @($EvidenceRoot,$PhotoRoot,"$EvidenceRoot\derived","$FacadeRoot\colmap",$PreviewRoot)) {
    New-Item -ItemType Directory -Force -Path $Dir | Out-Null
}
foreach ($Path in @($Work,$BlenderScript)) {
    if (-not (Test-Path -LiteralPath $Path)) { throw "Absent : $Path" }
}

if (-not $BuildingObj) {
    $Preferred = "$Work\50_roofer\sweep-detail-20260923-115605\c070\export\roofer-c070-local.obj"
    if (Test-Path -LiteralPath $Preferred) {
        $BuildingObj = $Preferred
    } else {
        $Hit = Get-ChildItem -LiteralPath "$Work\50_roofer" -Recurse -File -Filter "roofer-c070-local.obj" -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending | Select-Object -First 1
        if (-not $Hit) {
            $Hit = Get-ChildItem -LiteralPath "$Work\50_roofer" -Recurse -File -Filter "roofer-lod22-local.obj" -ErrorAction SilentlyContinue |
                Sort-Object LastWriteTime -Descending | Select-Object -First 1
        }
        if ($Hit) { $BuildingObj = $Hit.FullName }
    }
}

if (-not $TerrainObj) {
    foreach ($Candidate in @(
        "$Work\60_context\context-surface-ortho-v1\context-surface-ortho.obj",
        "$Work\60_context\context-surface-v1\context-surface.obj",
        "$Work\60_context\context-ground-v3\context-ground.obj"
    )) {
        if (Test-Path -LiteralPath $Candidate) { $TerrainObj = $Candidate; break }
    }
}

if (-not $BuildingObj -or -not (Test-Path -LiteralPath $BuildingObj)) { throw "Building OBJ introuvable." }
if (-not $TerrainObj -or -not (Test-Path -LiteralPath $TerrainObj)) { throw "Terrain OBJ introuvable." }

if (-not $BlenderExe) {
    $Cmd = Get-Command blender.exe -ErrorAction SilentlyContinue
    if ($Cmd) { $BlenderExe = $Cmd.Source }
}
if (-not $BlenderExe) {
    $Roots = @("$env:ProgramFiles\Blender Foundation", "${env:ProgramFiles(x86)}\Blender Foundation") |
        Where-Object { $_ -and (Test-Path -LiteralPath $_) }
    $Hit = foreach ($SearchRoot in $Roots) {
        Get-ChildItem -LiteralPath $SearchRoot -Recurse -File -Filter blender.exe -ErrorAction SilentlyContinue
    }
    $Hit = $Hit | Sort-Object FullName -Descending | Select-Object -First 1
    if ($Hit) { $BlenderExe = $Hit.FullName }
}
if (-not $BlenderExe -or -not (Test-Path -LiteralPath $BlenderExe)) { throw "Blender introuvable. Passe -BlenderExe." }

@'
BATIFORGE - CAPTURE FACADE

Objectif : reconstruire portes, fenetres, baies et retraits comme geometrie.

- Garde les originaux intacts dans photos_original.
- Fais le tour du batiment si possible avec 60-80 % de recouvrement entre images.
- Pour chaque facade : frontal + obliques gauche/droite.
- Focale stable, pas de zoom numerique, pas de mode portrait ni filtre.
- Garde le sol et les angles du batiment visibles dans plusieurs images.
- Fais les plans proches portes/fenetres apres les vues generales.
- Evite autant que possible personnes et voitures devant les ouvertures.
- Minimum utile : environ 20-40 photos. Mieux : 50-100 si le tour complet est possible.

Les photos restent non placees dans Blender jusqu'a COLMAP + enregistrement metrique LiDAR/RNB.
'@ | Set-Content -LiteralPath $Guide -Encoding utf8

$Photos = @(Get-ChildItem -LiteralPath $PhotoRoot -Recurse -File -ErrorAction SilentlyContinue |
    Where-Object { $_.Extension.ToLowerInvariant() -in @('.jpg','.jpeg','.png','.tif','.tiff','.heic','.webp') })

Write-Host "`n===== BATIFORGE FACADE + BLENDER =====" -ForegroundColor Cyan
Write-Host "Workspace : $Workspace"
Write-Host "Blender   : $BlenderExe"
Write-Host "Building  : $BuildingObj"
Write-Host "Terrain   : $TerrainObj"
Write-Host "Photos    : $($Photos.Count)"
Write-Host "Photo dir : $PhotoRoot"

Remove-Item $Blend,$Render,$Manifest -Force -ErrorAction SilentlyContinue

& $BlenderExe --background --factory-startup --python $BlenderScript -- `
    --building $BuildingObj `
    --terrain $TerrainObj `
    --evidence-dir $PhotoRoot `
    --output-blend $Blend `
    --output-render $Render `
    --output-manifest $Manifest
if ($LASTEXITCODE -ne 0) { throw "Construction de la scene Blender echouee." }

foreach ($Path in @($Blend,$Render,$Manifest,$Guide)) {
    if (-not (Test-Path -LiteralPath $Path)) { throw "Sortie absente : $Path" }
}

$M = Get-Content -LiteralPath $Manifest -Raw | ConvertFrom-Json
Write-Host "`n===== RESULTAT =====" -ForegroundColor Green
Write-Host "Evidence photos :" $M.facade_evidence_photo_count
Write-Host "BBOX local      :" (($M.bbox_local.min -join ', ') + " -> " + ($M.bbox_local.max -join ', '))
Write-Host "Blend           :" $Blend
Write-Host "Preview PNG     :" $Render
Write-Host "Photos originales:" $PhotoRoot
Write-Host "Guide capture   :" $Guide

if (git status --porcelain) {
    git status --short
    throw "Worktree non CLEAN."
}
Write-Host "Status          : CLEAN" -ForegroundColor Green

Start-Process -FilePath $BlenderExe -ArgumentList @($Blend)
Start-Process explorer.exe "/select,$Render"
