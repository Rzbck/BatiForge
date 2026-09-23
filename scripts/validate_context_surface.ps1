param(
    [string]$Root = "E:\_Project\_ProjectPython\BatiForge",
    [string]$Workspace = "espace-des-forges",
    [double]$MarginM = 25.0,
    [double]$CellSizeM = 0.5,
    [int]$RelaxIterations = 80,
    [double]$RelaxWeight = 0.65
)

$ErrorActionPreference = "Stop"
Set-Location $Root

$Python = "$Root\.venv\Scripts\python.exe"
$Work = "$Root\workspaces\$Workspace"
$LidarRoot = "$Work\10_lidar\context_tiles"
$Foot = "$Work\40_mesh\footprint-v1\rnb-footprint.json"
$Roof = "$Work\40_mesh\roof-planes-v1\roof-planes.json"
$Out = "$Work\60_context\context-surface-v1"
$Json = "$Out\context-surface.json"
$Obj = "$Out\context-surface.obj"
$Ply = "$Out\context-surface.ply"

foreach ($Path in @($Python,$Foot,$Roof,$LidarRoot)) {
    if (-not (Test-Path -LiteralPath $Path)) { throw "Absent : $Path" }
}

$Candidates = @(
    Get-ChildItem -LiteralPath $LidarRoot -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Extension -in @('.laz','.las') } |
        Sort-Object FullName -Unique
)
if ($Candidates.Count -eq 0) {
    throw "Aucune dalle LiDAR officielle dans $LidarRoot"
}

$GroundZ = [double](Get-Content -LiteralPath $Roof -Raw | ConvertFrom-Json).georeference.ground_z
New-Item -ItemType Directory -Force -Path $Out | Out-Null
Remove-Item $Json,$Obj,$Ply -Force -ErrorAction SilentlyContinue

Write-Host "`n===== BATIFORGE CONTEXT SURFACE V1 =====" -ForegroundColor Cyan
Write-Host "Sources            : $($Candidates.Count) official tiles"
Write-Host "Margin             : $MarginM m"
Write-Host "Grid               : $CellSizeM m"
Write-Host "Ground             : $GroundZ m IGN69"
Write-Host "Relax iterations   : $RelaxIterations"
Write-Host "Relax weight       : $RelaxWeight"

& $Python -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { throw "Tests echoues." }

$Args = @('-m', 'batiforge.reconstruction.context_surface')
foreach ($Source in $Candidates) {
    $Args += @('--lidar', $Source.FullName)
}
$Args += @(
    '--footprint-json', $Foot,
    '--ground-z', ([string]::Format([Globalization.CultureInfo]::InvariantCulture, '{0:R}', $GroundZ)),
    '--margin-m', ([string]::Format([Globalization.CultureInfo]::InvariantCulture, '{0:R}', $MarginM)),
    '--cell-size-m', ([string]::Format([Globalization.CultureInfo]::InvariantCulture, '{0:R}', $CellSizeM)),
    '--ground-class', '2',
    '--relax-iterations', "$RelaxIterations",
    '--relax-weight', ([string]::Format([Globalization.CultureInfo]::InvariantCulture, '{0:R}', $RelaxWeight)),
    '--output-json', $Json,
    '--output-obj', $Obj,
    '--output-ply', $Ply
)

& $Python @Args
if ($LASTEXITCODE -ne 0) { throw "Generation surface contexte echouee." }

$C = Get-Content -LiteralPath $Json -Raw | ConvertFrom-Json

Write-Host "`n===== RESULTAT =====" -ForegroundColor Green
Write-Host "Ground points      :" $C.source.deduplicated_ground_point_count
Write-Host "Cells mesurees     :" $C.grid.measured_cell_count
Write-Host "Cells inferees     :" $C.grid.inferred_cell_count
Write-Host "Coverage mesuree   :" ([math]::Round([double]$C.grid.measured_coverage_ratio,3))
Write-Host "Coverage finale    :" ([math]::Round([double]$C.grid.final_coverage_ratio,3))
Write-Host "Max fill distance  :" "$($C.grid.max_fill_distance_cells) cells / $($C.grid.max_fill_distance_m) m"
Write-Host "Vertices           :" $C.mesh.vertex_count
Write-Host "Faces              :" $C.mesh.face_count
Write-Host "Z local            :" "$($C.mesh.local_z_min_m) -> $($C.mesh.local_z_max_m) m"

Get-Item $Json,$Obj,$Ply | Select-Object Name,Length,FullName | Format-Table -AutoSize

if (git status --porcelain) {
    git status --short
    throw "Worktree non CLEAN."
}
Write-Host "Status : CLEAN" -ForegroundColor Green
Write-Host "`nOBJ SURFACE PROPRE : $Obj" -ForegroundColor Green
Start-Process explorer.exe "/select,$Obj"
