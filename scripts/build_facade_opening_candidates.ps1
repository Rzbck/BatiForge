param(
    [string]$Root = "E:\_Project\_ProjectPython\BatiForge",
    [string]$Workspace = "espace-des-forges",
    [string]$ModelId = "Marco333/segformer-b0-facade-cmp",
    [int]$CandidateCount = 6,
    [string]$BlenderExe = ""
)

$ErrorActionPreference = "Stop"
Set-Location $Root

$Work = "$Root\workspaces\$Workspace"
$FacadeRoot = "$Work\70_facade"
$Evidence = "$FacadeRoot\evidence"
$Image = "$Evidence\web_original\vellut-forges-exterior-49769001212.jpg"
$Building = "$Work\50_roofer\sweep-detail-20260923-115605\c070\export\roofer-c070-local.obj"
$BaseBlend = "$FacadeRoot\preview\batiforge-facade-preview.blend"
$Out = "$FacadeRoot\opening-candidates-v1"
$CandidateJson = "$Out\facade-opening-candidates.json"
$BlenderScript = "$Root\scripts\blender\build_facade_opening_candidates.py"
$Uv = (Get-Command uv.exe -ErrorAction Stop).Source

if (-not (Test-Path -LiteralPath $Image)) {
    Write-Host "Evidence web absente : preparation automatique..." -ForegroundColor Yellow
    & "$Root\scripts\prepare_facade_web_pipeline.ps1" -Root $Root -Workspace $Workspace -PdfDpi 180
    if ($LASTEXITCODE -ne 0) { throw "Preparation evidence web echouee." }
}

foreach ($Path in @($Image,$Building,$BaseBlend,$BlenderScript)) {
    if (-not (Test-Path -LiteralPath $Path)) { throw "Absent : $Path" }
}

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
if (-not $BlenderExe -or -not (Test-Path -LiteralPath $BlenderExe)) { throw "Blender introuvable." }

New-Item -ItemType Directory -Force -Path $Out | Out-Null
Remove-Item "$Out\candidate-*.png","$Out\candidate-*.blend",$CandidateJson -Force -ErrorAction SilentlyContinue

$env:HF_HOME = "E:\_Project\_ProjectPython\cache\huggingface"
$env:HF_HUB_DISABLE_TELEMETRY = "1"

Write-Host "`n===== BATIFORGE FACADE OPENING CANDIDATES V1 =====" -ForegroundColor Cyan
Write-Host "Image    : $Image"
Write-Host "Building : $Building"
Write-Host "Model    : $ModelId"
Write-Host "HF cache : $env:HF_HOME"
Write-Host "Status   : EXPERIMENTAL candidate geometry - no wall cuts"

& $Uv run `
    --with "torch>=2.8,<3" `
    --with "transformers>=4.56,<5" `
    --with "pillow>=11,<13" `
    --with "scipy>=1.16,<2" `
    python -m unittest tests.test_facade_opening_candidates -v
if ($LASTEXITCODE -ne 0) { throw "Tests facade opening candidates echoues." }

& $Uv run `
    --with "torch>=2.8,<3" `
    --with "transformers>=4.56,<5" `
    --with "pillow>=11,<13" `
    --with "scipy>=1.16,<2" `
    python -m batiforge.reconstruction.facade_opening_candidates `
        --image $Image `
        --building-obj $Building `
        --output-dir $Out `
        --model-id $ModelId `
        --top-walls ([math]::Max(1,[math]::Ceiling($CandidateCount / 2.0)))
if ($LASTEXITCODE -ne 0) { throw "Detection facade/openings echouee." }

if (-not (Test-Path -LiteralPath $CandidateJson)) { throw "JSON candidats absent : $CandidateJson" }
$M = Get-Content -LiteralPath $CandidateJson -Raw | ConvertFrom-Json
$Available = @($M.candidate_mappings).Count
$RenderCount = [math]::Min($CandidateCount, $Available)
if ($RenderCount -lt 1) { throw "Aucun mapping de facade candidat." }

for ($i = 1; $i -le $RenderCount; $i++) {
    $Tag = "{0:D2}" -f $i
    $Blend = "$Out\candidate-$Tag.blend"
    $Render = "$Out\candidate-$Tag.png"
    & $BlenderExe --background --factory-startup --python $BlenderScript -- `
        --base-blend $BaseBlend `
        --candidates-json $CandidateJson `
        --candidate-index $i `
        --output-blend $Blend `
        --output-render $Render
    if ($LASTEXITCODE -ne 0) { throw "Blender candidate $i echoue." }
}

Write-Host "`n===== RESULTAT =====" -ForegroundColor Green
Write-Host "Device IA         :" $M.segmentation.device
Write-Host "Ouvertures detect.:" $M.segmentation.opening_count
Write-Host "Plans verticaux   :" $M.wall_count
Write-Host "Mappings rendus   :" $RenderCount
Write-Host "Overlay IA        :" $M.segmentation.overlay_path
Write-Host "JSON              :" $CandidateJson

$Rows = for ($i = 0; $i -lt $RenderCount; $i++) {
    $C = $M.candidate_mappings[$i]
    [PSCustomObject]@{
        Rank = $i + 1
        Candidate = $C.candidate_id
        Score = [math]::Round([double]$C.aspect_score,4)
        Wall = ("{0:N2} x {1:N2} m" -f [double]$C.wall.width_m,[double]$C.wall.height_m)
        Openings = @($C.openings).Count
        Render = "$Out\candidate-$('{0:D2}' -f ($i+1)).png"
    }
}
$Rows | Format-Table -AutoSize

if (git status --porcelain) {
    git status --short
    throw "Worktree non CLEAN. Les sorties doivent rester sous workspace gitignore."
}
Write-Host "Status : CLEAN" -ForegroundColor Green
Write-Host "`nIMPORTANT : les panneaux sont des hypotheses de mapping, PAS encore des ouvertures metriques acceptees." -ForegroundColor Yellow
Start-Process explorer.exe $Out
Start-Process -FilePath $BlenderExe -ArgumentList @("$Out\candidate-01.blend")
