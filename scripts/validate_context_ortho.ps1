param(
    [string]$Root = "E:\_Project\_ProjectPython\BatiForge",
    [string]$Workspace = "espace-des-forges",
    [string]$Layer = "ORTHOIMAGERY.ORTHOPHOTOS",
    [double]$GsdM = 0.20
)

$ErrorActionPreference = "Stop"
Set-Location $Root

$Python = "$Root\.venv\Scripts\python.exe"
$Work = "$Root\workspaces\$Workspace"
$ContextDir = "$Work\60_context\context-ground-v3"
$ContextJson = "$ContextDir\context-ground.json"
$SourceObj = "$ContextDir\context-ground.obj"
$Out = "$Work\60_context\context-ortho-v1"
$Image = "$Out\ign-orthophoto.jpg"
$Obj = "$Out\context-ground-ortho.obj"
$Mtl = "$Out\context-ground-ortho.mtl"
$Json = "$Out\context-ortho.json"

foreach ($Path in @($Python,$ContextJson,$SourceObj)) {
    if (-not (Test-Path -LiteralPath $Path)) { throw "Absent : $Path" }
}

New-Item -ItemType Directory -Force -Path $Out | Out-Null
Remove-Item $Image,$Obj,$Mtl,$Json -Force -ErrorAction SilentlyContinue

Write-Host "`n===== BATIFORGE CONTEXT ORTHOPHOTO V1 =====" -ForegroundColor Cyan
Write-Host "Layer : $Layer"
Write-Host "GSD   : $GsdM m"
Write-Host "Source: IGN Geoplateforme WMS-Raster"

& $Python -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { throw "Tests echoues." }

$GsdInvariant = [string]::Format(
    [Globalization.CultureInfo]::InvariantCulture,
    '{0:R}',
    $GsdM
)

& $Python -m batiforge.reconstruction.context_ortho `
    --context-json $ContextJson `
    --source-obj $SourceObj `
    --output-image $Image `
    --output-obj $Obj `
    --output-mtl $Mtl `
    --output-json $Json `
    --layer $Layer `
    --gsd-m $GsdInvariant

if ($LASTEXITCODE -ne 0) { throw "Generation orthophoto contexte echouee." }

$C = Get-Content -LiteralPath $Json -Raw | ConvertFrom-Json
$I = $C.orthophoto.image
$B = $C.orthophoto.bbox_abs_xy

Write-Host "`n===== RESULTAT =====" -ForegroundColor Green
Write-Host "Layer       :" $C.orthophoto.layer
Write-Host "Image       :" "$($I.width_px)x$($I.height_px) px"
Write-Host "GSD effectif:" "$([math]::Round([double]$I.effective_gsd_x_m,3)) x $([math]::Round([double]$I.effective_gsd_y_m,3)) m"
Write-Host "BBOX L93    :" "$($B.min_x), $($B.min_y) -> $($B.max_x), $($B.max_y)"
Write-Host "Vertices    :" $C.mesh.vertex_count
Write-Host "UV          :" $C.mesh.uv_count
Write-Host "Faces       :" $C.mesh.face_count

Get-Item $Image,$Obj,$Mtl,$Json |
    Select-Object Name,Length,FullName |
    Format-Table -AutoSize

if (git status --porcelain) {
    git status --short
    throw "Worktree non CLEAN."
}

Write-Host "Status : CLEAN" -ForegroundColor Green
Write-Host "`nOBJ TEXTURE : $Obj" -ForegroundColor Green
Write-Host "IMAGE       : $Image" -ForegroundColor Green
Start-Process explorer.exe "/select,$Obj"
