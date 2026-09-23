param(
    [string]$Root = "E:\_Project\_ProjectPython\BatiForge",
    [string]$Workspace = "espace-des-forges",
    [string]$ModelId = "IDEA-Research/grounding-dino-base",
    [int]$CandidateCount = 6,
    [double]$BoxThreshold = 0.24,
    [double]$TextThreshold = 0.20,
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
$Out = "$FacadeRoot\opening-candidates-v2"
$Share = "$Out\SHARE"
$CandidateJson = "$Out\facade-opening-candidates-v2.json"
$BlenderScript = "$Root\scripts\blender\build_facade_opening_candidates.py"
$OpenBlender = "$Root\scripts\open_batiforge_blender.ps1"
$Uv = (Get-Command uv.exe -ErrorAction Stop).Source

foreach ($Path in @($Image,$Building,$BaseBlend,$BlenderScript,$OpenBlender)) {
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

New-Item -ItemType Directory -Force -Path $Out,$Share | Out-Null
Remove-Item "$Out\candidate-*.png","$Out\candidate-*.blend",$CandidateJson,"$Share\*" -Force -ErrorAction SilentlyContinue

$env:HF_HOME = "E:\_Project\_ProjectPython\cache\huggingface"
$env:HF_HUB_DISABLE_TELEMETRY = "1"

Write-Host "`n===== BATIFORGE FACADE OPENINGS V2 =====" -ForegroundColor Cyan
Write-Host "Detector : Grounding DINO zero-shot"
Write-Host "Model    : $ModelId"
Write-Host "Image    : $Image"
Write-Host "Building : $Building"
Write-Host "HF cache : $env:HF_HOME"
Write-Host "Rule     : if zero openings -> STOP, no useless Blender candidates"

& $Uv run `
    --with "torch>=2.8,<3" `
    --with "transformers>=4.56,<5" `
    --with "pillow>=11,<13" `
    python -m unittest tests.test_facade_opening_grounding -v
if ($LASTEXITCODE -ne 0) { throw "Tests Grounding DINO facade echoues." }

& $Uv run `
    --with "torch>=2.8,<3" `
    --with "transformers>=4.56,<5" `
    --with "pillow>=11,<13" `
    python -m batiforge.reconstruction.facade_opening_grounding `
        --image $Image `
        --building-obj $Building `
        --output-dir $Out `
        --model-id $ModelId `
        --top-walls ([math]::Max(1,[math]::Ceiling($CandidateCount / 2.0))) `
        --box-threshold ([string]::Format([Globalization.CultureInfo]::InvariantCulture, '{0:R}', $BoxThreshold)) `
        --text-threshold ([string]::Format([Globalization.CultureInfo]::InvariantCulture, '{0:R}', $TextThreshold))
if ($LASTEXITCODE -ne 0) { throw "Detection Grounding DINO facade echouee." }

if (-not (Test-Path -LiteralPath $CandidateJson)) { throw "JSON candidats absent : $CandidateJson" }
$M = Get-Content -LiteralPath $CandidateJson -Raw | ConvertFrom-Json
$OpeningCount = [int]$M.segmentation.opening_count
if ($OpeningCount -lt 1) { throw "STOP : zero ouverture detectee. Aucun rendu candidat ne sera fabrique." }

$Available = @($M.candidate_mappings).Count
$RenderCount = [math]::Min($CandidateCount, $Available)
if ($RenderCount -lt 1) { throw "Aucun mapping facade candidat." }

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

$Overlay = [string]$M.segmentation.overlay_path
Copy-Item -LiteralPath $Image -Destination "$Share\00-source.jpg" -Force
Copy-Item -LiteralPath $Overlay -Destination "$Share\01-detection-overlay.png" -Force
Copy-Item -LiteralPath $CandidateJson -Destination "$Share\facade-opening-candidates-v2.json" -Force
for ($i = 1; $i -le $RenderCount; $i++) {
    $Tag = "{0:D2}" -f $i
    Copy-Item -LiteralPath "$Out\candidate-$Tag.png" -Destination "$Share\candidate-$Tag.png" -Force
}
Copy-Item -LiteralPath "$Out\candidate-01.blend" -Destination "$Share\candidate-01.blend" -Force

@"
BATIFORGE - A PARTAGER DANS LE CHAT

1. 01-detection-overlay.png
2. candidate-01.png ... candidate-$('{0:D2}' -f $RenderCount).png
3. facade-opening-candidates-v2.json
4. candidate-01.blend seulement si necessaire

Source originale : 00-source.jpg
Openings detectees : $OpeningCount
Detector : $ModelId
"@ | Set-Content -LiteralPath "$Share\README-SHARE.txt" -Encoding utf8

Write-Host "`n===== RESULTAT V2 =====" -ForegroundColor Green
Write-Host "Device IA          :" $M.segmentation.device
Write-Host "Ouvertures detect. :" $OpeningCount
Write-Host "Detections brutes  :" $M.segmentation.raw_detection_count
Write-Host "Plans verticaux    :" $M.wall_count
Write-Host "Mappings rendus    :" $RenderCount
Write-Host "Overlay            :" $Overlay
Write-Host "Dossier SHARE      :" $Share -ForegroundColor Cyan

$Rows = for ($i = 0; $i -lt $RenderCount; $i++) {
    $C = $M.candidate_mappings[$i]
    [PSCustomObject]@{
        Rank = $i + 1
        Candidate = $C.candidate_id
        Wall = ("{0:N2} x {1:N2} m" -f [double]$C.wall.width_m,[double]$C.wall.height_m)
        Openings = @($C.openings).Count
        Render = "$Share\candidate-$('{0:D2}' -f ($i+1)).png"
    }
}
$Rows | Format-Table -AutoSize

if (git status --porcelain) {
    git status --short
    throw "Worktree non CLEAN. Les sorties doivent rester sous workspace gitignore."
}
Write-Host "Status : CLEAN" -ForegroundColor Green

& $OpenBlender `
    -Root $Root `
    -Workspace $Workspace `
    -BlendPath "$Out\candidate-01.blend" `
    -ShareDir $Share `
    -BlenderExe $BlenderExe
