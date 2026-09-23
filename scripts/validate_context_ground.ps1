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
$Out = "$Work\60_context\context-ground-v1"
$Json = "$Out\context-ground.json"
$Obj = "$Out\context-ground.obj"
$Ply = "$Out\context-ground.ply"

foreach ($Path in @($Python,$Foot,$Roof,$LidarRoot)) {
    if (-not (Test-Path -LiteralPath $Path)) { throw "Absent : $Path" }
}

$Candidates = @(
    Get-ChildItem -LiteralPath $LidarRoot -Recurse -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Extension -in @('.laz','.las') } |
        Sort-Object Length -Descending
)
if ($Candidates.Count -eq 0) { throw "Aucun LAS/LAZ sous $LidarRoot" }

$Source = $Candidates |
    Where-Object { $_.Name -match '0940_6540' -and $_.Name -notmatch 'building|context-3m' } |
    Select-Object -First 1
if (-not $Source) {
    $Source = $Candidates |
        Where-Object { $_.Name -notmatch 'building|context-3m' } |
        Select-Object -First 1
}
if (-not $Source) {
    Write-Host "Sources trouvees :" -ForegroundColor Yellow
    $Candidates | Select-Object Name,Length,FullName | Format-Table -AutoSize
    throw "Aucune source LiDAR plus large que building/context-3m."
}

$GroundZ = [double](Get-Content -LiteralPath $Roof -Raw | ConvertFrom-Json).georeference.ground_z
New-Item -ItemType Directory -Force -Path $Out | Out-Null
Remove-Item $Json,$Obj,$Ply -Force -ErrorAction SilentlyContinue

Write-Host "`n===== BATIFORGE CONTEXT GROUND =====" -ForegroundColor Cyan
Write-Host "LiDAR  : $($Source.FullName)"
Write-Host "Taille : $([math]::Round($Source.Length / 1MB,2)) MB"
Write-Host "Margin : $MarginM m"
Write-Host "Grid   : $CellSizeM m"
Write-Host "Ground : $GroundZ m IGN69"

& $Python -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { throw "Tests echoues." }

& $Python -m batiforge.reconstruction.context_ground `
    --lidar $Source.FullName `
    --footprint-json $Foot `
    --ground-z $GroundZ `
    --margin-m $MarginM `
    --cell-size-m $CellSizeM `
    --ground-class 2 `
    --min-points-per-cell 1 `
    --output-json $Json `
    --output-obj $Obj `
    --output-ply $Ply
if ($LASTEXITCODE -ne 0) { throw "Generation contexte echouee." }

$C = Get-Content -LiteralPath $Json -Raw | ConvertFrom-Json
Write-Host "`n===== RESULTAT =====" -ForegroundColor Green
Write-Host "Points crop total :" $C.source.cropped_all_point_count
Write-Host "Points sol classe2:" $C.ground_point_count
Write-Host "Cells             :" "$($C.grid.occupied_cell_count)/$($C.grid.cell_count)"
Write-Host "Coverage          :" ([math]::Round([double]$C.grid.coverage_ratio,3))
Write-Host "Vertices          :" $C.mesh.vertex_count
Write-Host "Faces             :" $C.mesh.face_count
Write-Host "Z local           :" "$($C.mesh.local_z_min_m) -> $($C.mesh.local_z_max_m) m"
Write-Host "Classes crop      :" ($C.source.classification_histogram | ConvertTo-Json -Compress)

Get-Item $Json,$Obj,$Ply | Select-Object Name,Length,FullName | Format-Table -AutoSize

if (git status --porcelain) {
    git status --short
    throw "Worktree non CLEAN."
}
Write-Host "Status : CLEAN" -ForegroundColor Green
Write-Host "`nOBJ CONTEXTE : $Obj" -ForegroundColor Green
Start-Process explorer.exe "/select,$Obj"
