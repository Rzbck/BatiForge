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
$LidarRoot = "$Work\10_lidar"
$Foot = "$Work\40_mesh\footprint-v1\rnb-footprint.json"
$Roof = "$Work\40_mesh\roof-planes-v1\roof-planes.json"
$Out = "$Work\60_context\context-ground-v2"
$Json = "$Out\context-ground.json"
$Obj = "$Out\context-ground.obj"
$Ply = "$Out\context-ground.ply"

foreach ($Path in @($Python,$Foot,$Roof,$LidarRoot)) {
    if (-not (Test-Path -LiteralPath $Path)) { throw "Absent : $Path" }
}

$Candidates = @(
    Get-ChildItem -LiteralPath $LidarRoot -Recurse -File -ErrorAction SilentlyContinue |
        Where-Object {
            $_.Extension -in @('.laz','.las') -and
            $_.Name -notmatch 'building|context-3m'
        } |
        Sort-Object FullName -Unique
)
if ($Candidates.Count -eq 0) {
    throw "Aucune source LAS/LAZ de contexte sous $LidarRoot"
}

$GroundZ = [double](Get-Content -LiteralPath $Roof -Raw | ConvertFrom-Json).georeference.ground_z
New-Item -ItemType Directory -Force -Path $Out | Out-Null
Remove-Item $Json,$Obj,$Ply -Force -ErrorAction SilentlyContinue

Write-Host "`n===== BATIFORGE CONTEXT GROUND V2 =====" -ForegroundColor Cyan
Write-Host "Sources candidates : $($Candidates.Count)"
Write-Host "Margin             : $MarginM m"
Write-Host "Grid               : $CellSizeM m"
Write-Host "Ground             : $GroundZ m IGN69"

& $Python -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { throw "Tests echoues." }

$Args = @(
    '-m', 'batiforge.reconstruction.context_ground'
)
foreach ($Source in $Candidates) {
    $Args += @('--lidar', $Source.FullName)
}
$Args += @(
    '--footprint-json', $Foot,
    '--ground-z', ([string]::Format([Globalization.CultureInfo]::InvariantCulture, '{0:R}', $GroundZ)),
    '--margin-m', ([string]::Format([Globalization.CultureInfo]::InvariantCulture, '{0:R}', $MarginM)),
    '--cell-size-m', ([string]::Format([Globalization.CultureInfo]::InvariantCulture, '{0:R}', $CellSizeM)),
    '--ground-class', '2',
    '--min-points-per-cell', '1',
    '--output-json', $Json,
    '--output-obj', $Obj,
    '--output-ply', $Ply
)

& $Python @Args
if ($LASTEXITCODE -ne 0) { throw "Generation contexte echouee." }

$C = Get-Content -LiteralPath $Json -Raw | ConvertFrom-Json

Write-Host "`n===== SOURCES RETENUES =====" -ForegroundColor Cyan
$Rows = foreach ($S in $C.source.sources) {
    [PSCustomObject]@{
        Fichier = [IO.Path]::GetFileName($S.lidar_path)
        Overlap = [math]::Round([double]$S.crop_overlap_ratio,3)
        PointsCrop = $S.cropped_all_point_count
        Ground2 = if ($S.classification_histogram.PSObject.Properties.Name -contains '2') { $S.classification_histogram.'2' } else { 0 }
    }
}
$Rows | Format-Table -AutoSize

Write-Host "`n===== RESULTAT =====" -ForegroundColor Green
Write-Host "Sources overlap    :" $C.source.overlapping_source_count
Write-Host "Points crop total  :" $C.source.cropped_all_point_count
Write-Host "Ground brut        :" $C.source.raw_ground_point_count_before_dedup
Write-Host "Ground deduplique  :" $C.source.deduplicated_ground_point_count
Write-Host "Cells              :" "$($C.grid.occupied_cell_count)/$($C.grid.cell_count)"
Write-Host "Coverage           :" ([math]::Round([double]$C.grid.coverage_ratio,3))
Write-Host "Vertices           :" $C.mesh.vertex_count
Write-Host "Faces              :" $C.mesh.face_count
Write-Host "Z local            :" "$($C.mesh.local_z_min_m) -> $($C.mesh.local_z_max_m) m"
Write-Host "Classes crop       :" ($C.source.classification_histogram | ConvertTo-Json -Compress)

Get-Item $Json,$Obj,$Ply | Select-Object Name,Length,FullName | Format-Table -AutoSize

if (git status --porcelain) {
    git status --short
    throw "Worktree non CLEAN."
}
Write-Host "Status : CLEAN" -ForegroundColor Green
Write-Host "`nOBJ CONTEXTE V2 : $Obj" -ForegroundColor Green
Start-Process explorer.exe "/select,$Obj"
