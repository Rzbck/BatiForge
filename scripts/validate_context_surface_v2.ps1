param(
    [string]$Root = "E:\_Project\_ProjectPython\BatiForge",
    [string]$Workspace = "espace-des-forges",
    [int]$Iterations = 14,
    [double]$Strength = 0.70,
    [double]$SigmaZM = 0.35,
    [double]$MaxDeltaM = 0.25,
    [string]$Layer = "ORTHOIMAGERY.ORTHOPHOTOS",
    [double]$GsdM = 0.20
)

$ErrorActionPreference = "Stop"
Set-Location $Root

$Python = "$Root\.venv\Scripts\python.exe"
$Work = "$Root\workspaces\$Workspace"
$SourceDir = "$Work\60_context\context-surface-v1"
$SourceJson = "$SourceDir\context-surface.json"
$SourceObj = "$SourceDir\context-surface.obj"
$Out = "$Work\60_context\context-surface-v2"
$Json = "$Out\context-surface.json"
$Obj = "$Out\context-surface.obj"
$Ply = "$Out\context-surface.ply"
$Image = "$Out\ign-orthophoto.jpg"
$TexturedObj = "$Out\context-surface-ortho.obj"
$Mtl = "$Out\context-surface-ortho.mtl"
$OrthoJson = "$Out\context-surface-ortho.json"

foreach ($Path in @($Python,$SourceJson,$SourceObj)) {
    if (-not (Test-Path -LiteralPath $Path)) { throw "Absent : $Path" }
}

New-Item -ItemType Directory -Force -Path $Out | Out-Null
Remove-Item $Json,$Obj,$Ply,$Image,$TexturedObj,$Mtl,$OrthoJson -Force -ErrorAction SilentlyContinue

Write-Host "`n===== BATIFORGE CONTEXT SURFACE V2 - EDGE AWARE =====" -ForegroundColor Cyan
Write-Host "Source        : context-surface-v1"
Write-Host "Iterations    : $Iterations"
Write-Host "Strength      : $Strength"
Write-Host "Sigma Z       : $SigmaZM m"
Write-Host "Max delta     : $MaxDeltaM m"
Write-Host "Ortho layer   : $Layer"
Write-Host "Ortho GSD     : $GsdM m"

& $Python -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { throw "Tests echoues." }

& $Python -m batiforge.reconstruction.context_surface_refine `
    --source-json $SourceJson `
    --source-obj $SourceObj `
    --iterations $Iterations `
    --strength ([string]::Format([Globalization.CultureInfo]::InvariantCulture, '{0:R}', $Strength)) `
    --sigma-z-m ([string]::Format([Globalization.CultureInfo]::InvariantCulture, '{0:R}', $SigmaZM)) `
    --max-delta-m ([string]::Format([Globalization.CultureInfo]::InvariantCulture, '{0:R}', $MaxDeltaM)) `
    --output-json $Json `
    --output-obj $Obj `
    --output-ply $Ply
if ($LASTEXITCODE -ne 0) { throw "Raffinement surface contexte echoue." }

& $Python -m batiforge.reconstruction.context_ortho `
    --context-json $Json `
    --source-obj $Obj `
    --output-image $Image `
    --output-obj $TexturedObj `
    --output-mtl $Mtl `
    --output-json $OrthoJson `
    --layer $Layer `
    --gsd-m ([string]::Format([Globalization.CultureInfo]::InvariantCulture, '{0:R}', $GsdM))
if ($LASTEXITCODE -ne 0) { throw "Texture orthophoto sur surface V2 echouee." }

$M = Get-Content -LiteralPath $Json -Raw | ConvertFrom-Json
$O = Get-Content -LiteralPath $OrthoJson -Raw | ConvertFrom-Json

Write-Host "`n===== MESURES =====" -ForegroundColor Green
Write-Host "Rough median :" "$([math]::Round([double]$M.refinement.roughness_before.median_m,4)) -> $([math]::Round([double]$M.refinement.roughness_after.median_m,4)) m"
Write-Host "Rough P90    :" "$([math]::Round([double]$M.refinement.roughness_before.p90_m,4)) -> $([math]::Round([double]$M.refinement.roughness_after.p90_m,4)) m"
Write-Host "Rough P95    :" "$([math]::Round([double]$M.refinement.roughness_before.p95_m,4)) -> $([math]::Round([double]$M.refinement.roughness_after.p95_m,4)) m"
Write-Host "Disp RMS     :" "$([math]::Round([double]$M.refinement.displacement.rms_m,4)) m"
Write-Host "Disp P95     :" "$([math]::Round([double]$M.refinement.displacement.p95_abs_m,4)) m"
Write-Host "Disp max     :" "$([math]::Round([double]$M.refinement.displacement.max_abs_m,4)) m"
Write-Host "Vertices     :" $M.mesh.vertex_count
Write-Host "Faces        :" $M.mesh.face_count
Write-Host "Ortho        :" "$($O.orthophoto.image.width_px)x$($O.orthophoto.image.height_px) px"

Get-Item $Json,$Obj,$Ply,$Image,$TexturedObj,$Mtl,$OrthoJson |
    Select-Object Name,Length,FullName |
    Format-Table -AutoSize

if (git status --porcelain) {
    git status --short
    throw "Worktree non CLEAN."
}
Write-Host "Status : CLEAN" -ForegroundColor Green
Write-Host "`nOBJ V2 PROPRE   : $Obj" -ForegroundColor Green
Write-Host "OBJ V2 TEXTURE  : $TexturedObj" -ForegroundColor Green
Start-Process explorer.exe "/select,$TexturedObj"
