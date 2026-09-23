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
$SurfaceDir = "$Work\60_context\context-surface-v1"
$ContextJson = "$SurfaceDir\context-surface.json"
$SourceObj = "$SurfaceDir\context-surface.obj"
$Out = "$Work\60_context\context-surface-ortho-v1"
$Image = "$Out\ign-orthophoto.jpg"
$Obj = "$Out\context-surface-ortho.obj"
$Mtl = "$Out\context-surface-ortho.mtl"
$Json = "$Out\context-surface-ortho.json"

foreach ($Path in @($Python,$ContextJson,$SourceObj)) {
    if (-not (Test-Path -LiteralPath $Path)) { throw "Absent : $Path" }
}

New-Item -ItemType Directory -Force -Path $Out | Out-Null
Remove-Item $Image,$Obj,$Mtl,$Json -Force -ErrorAction SilentlyContinue

Write-Host "`n===== BATIFORGE CONTEXT SURFACE + ORTHO =====" -ForegroundColor Cyan
Write-Host "Surface : context-surface-v1"
Write-Host "Layer   : $Layer"
Write-Host "GSD     : $GsdM m"

& $Python -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { throw "Tests echoues." }

& $Python -m batiforge.reconstruction.context_ortho `
    --context-json $ContextJson `
    --source-obj $SourceObj `
    --output-image $Image `
    --output-obj $Obj `
    --output-mtl $Mtl `
    --output-json $Json `
    --layer $Layer `
    --gsd-m ([string]::Format([Globalization.CultureInfo]::InvariantCulture, '{0:R}', $GsdM))
if ($LASTEXITCODE -ne 0) { throw "Texture orthophoto sur surface contexte echouee." }

$M = Get-Content -LiteralPath $Json -Raw | ConvertFrom-Json
Write-Host "`n===== RESULTAT =====" -ForegroundColor Green
Write-Host "Image       :" "$($M.orthophoto.image.width_px)x$($M.orthophoto.image.height_px) px"
Write-Host "GSD effectif:" "$([math]::Round([double]$M.orthophoto.image.effective_gsd_x_m,3)) x $([math]::Round([double]$M.orthophoto.image.effective_gsd_y_m,3)) m"
Write-Host "Vertices    :" $M.mesh.vertex_count
Write-Host "UV          :" $M.mesh.uv_count
Write-Host "Faces       :" $M.mesh.face_count

Get-Item $Image,$Obj,$Mtl,$Json | Select-Object Name,Length,FullName | Format-Table -AutoSize

if (git status --porcelain) {
    git status --short
    throw "Worktree non CLEAN."
}
Write-Host "Status : CLEAN" -ForegroundColor Green
Write-Host "`nOBJ SURFACE TEXTUREE : $Obj" -ForegroundColor Green
Write-Host "IMAGE                : $Image" -ForegroundColor Green
Start-Process explorer.exe "/select,$Obj"
