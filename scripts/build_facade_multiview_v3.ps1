param(
    [string]$Root = "E:\_Project\_ProjectPython\BatiForge",
    [string]$Workspace = "espace-des-forges",
    [string]$ModelId = "IDEA-Research/grounding-dino-base",
    [int]$CandidateCount = 4,
    [double]$BoxThreshold = 0.24,
    [double]$TextThreshold = 0.20,
    [string]$BlenderExe = ""
)

$ErrorActionPreference = "Stop"
Set-Location $Root

$Work = "$Root\workspaces\$Workspace"
$FacadeRoot = "$Work\70_facade"
$Evidence = "$FacadeRoot\evidence"
$Web = "$Evidence\web_original"
$Pdf = "$Web\tdc-fiche-technique-forges-2025.pdf"
$Vellut = "$Web\vellut-forges-exterior-49769001212.jpg"
$PdfAssets = "$Evidence\derived\pdf_photo_assets"
$Out = "$FacadeRoot\opening-multiview-v3"
$Detections = "$Out\detections"
$Share = "$Out\SHARE"
$Building = "$Work\50_roofer\sweep-detail-20260923-115605\c070\export\roofer-c070-local.obj"
$BaseBlend = "$FacadeRoot\preview\batiforge-facade-preview.blend"
$CandidateJson = "$Out\facade-opening-candidates-v2.json"
$BlenderScript = "$Root\scripts\blender\build_facade_opening_candidates.py"
$OpenBlender = "$Root\scripts\open_batiforge_blender.ps1"
$Uv = (Get-Command uv.exe -ErrorAction Stop).Source

foreach ($Path in @($Pdf,$Vellut,$Building,$BaseBlend,$BlenderScript,$OpenBlender)) {
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

New-Item -ItemType Directory -Force -Path $PdfAssets,$Out,$Detections,$Share | Out-Null
Remove-Item "$PdfAssets\*","$Out\candidate-*.png","$Out\candidate-*.blend",$CandidateJson,"$Share\*" -Recurse -Force -ErrorAction SilentlyContinue

$env:HF_HOME = "E:\_Project\_ProjectPython\cache\huggingface"
$env:HF_HUB_DISABLE_TELEMETRY = "1"

Write-Host "`n===== BATIFORGE FACADE MULTIVIEW V3 =====" -ForegroundColor Cyan
Write-Host "But      : corriger le cote Blender + exploiter chaque photo du PDF"
Write-Host "PDF      : $Pdf"
Write-Host "Web      : $Vellut"
Write-Host "Detector : $ModelId"

Write-Host "`n===== 1. EXTRACTION DES PHOTOS DU PDF =====" -ForegroundColor Cyan
& $Uv run --with "pymupdf>=1.26,<2" `
    python -m batiforge.reconstruction.facade_pdf_assets `
        --pdf $Pdf `
        --output-dir $PdfAssets `
        --pages 5 `
        --min-width 240 `
        --min-height 160
if ($LASTEXITCODE -ne 0) { throw "Extraction photos PDF echouee." }

$PdfImages = @(Get-ChildItem -LiteralPath $PdfAssets -File -ErrorAction SilentlyContinue |
    Where-Object { $_.Extension.ToLowerInvariant() -in @('.jpg','.jpeg','.png','.webp') } |
    Sort-Object Name)
$EvidenceImages = @((Get-Item -LiteralPath $Vellut)) + $PdfImages
Write-Host "Photos PDF extraites : $($PdfImages.Count)" -ForegroundColor Green
Write-Host "Images evidence total: $($EvidenceImages.Count)" -ForegroundColor Green

Write-Host "`n===== 2. CONTACT SHEET SOURCES =====" -ForegroundColor Cyan
$Contact = "$Share\00-evidence-contact-sheet.jpg"
$ContactManifest = "$Share\00-evidence-contact-sheet.json"
& $Uv run --with "pillow>=11,<13" `
    python -m batiforge.reconstruction.facade_contact_sheet `
        --output $Contact `
        --manifest $ContactManifest `
        @($EvidenceImages.FullName)
if ($LASTEXITCODE -ne 0) { throw "Contact sheet echouee." }

Write-Host "`n===== 3. DETECTION SUR TOUTES LES VUES =====" -ForegroundColor Cyan
& $Uv run `
    --with "torch>=2.8,<3" `
    --with "transformers>=4.56,<5" `
    --with "pillow>=11,<13" `
    python -m batiforge.reconstruction.facade_multiview_detect `
        --output-dir $Detections `
        --model-id $ModelId `
        --box-threshold ([string]::Format([Globalization.CultureInfo]::InvariantCulture, '{0:R}', $BoxThreshold)) `
        --text-threshold ([string]::Format([Globalization.CultureInfo]::InvariantCulture, '{0:R}', $TextThreshold)) `
        @($EvidenceImages.FullName)
if ($LASTEXITCODE -ne 0) { throw "Detection multivue echouee." }

Write-Host "`n===== 4. MAPPING 3D DIAGNOSTIC SUR LA VUE EXTERIEURE =====" -ForegroundColor Cyan
& $Uv run `
    --with "torch>=2.8,<3" `
    --with "transformers>=4.56,<5" `
    --with "pillow>=11,<13" `
    python -m batiforge.reconstruction.facade_opening_grounding `
        --image $Vellut `
        --building-obj $Building `
        --output-dir $Out `
        --model-id $ModelId `
        --top-walls 2 `
        --box-threshold ([string]::Format([Globalization.CultureInfo]::InvariantCulture, '{0:R}', $BoxThreshold)) `
        --text-threshold ([string]::Format([Globalization.CultureInfo]::InvariantCulture, '{0:R}', $TextThreshold))
if ($LASTEXITCODE -ne 0) { throw "Mapping diagnostic echoue." }

$M = Get-Content -LiteralPath $CandidateJson -Raw | ConvertFrom-Json
$Available = @($M.candidate_mappings).Count
$RenderCount = [math]::Min($CandidateCount, $Available)
if ($RenderCount -lt 1) { throw "Aucun mapping 3D candidat." }

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

Write-Host "`n===== 5. DOSSIER SHARE =====" -ForegroundColor Cyan
Copy-Item -LiteralPath $Vellut -Destination "$Share\01-vellut-source.jpg" -Force
Copy-Item -LiteralPath ([string]$M.segmentation.overlay_path) -Destination "$Share\02-vellut-detection.png" -Force
Copy-Item -LiteralPath $CandidateJson -Destination "$Share\facade-opening-candidates-v3-diagnostic.json" -Force
Copy-Item -LiteralPath "$Detections\multiview-detections.json" -Destination "$Share\multiview-detections.json" -Force
Copy-Item -LiteralPath "$PdfAssets\pdf-photo-assets.json" -Destination "$Share\pdf-photo-assets.json" -Force

$Index = 0
foreach ($Img in $PdfImages) {
    $Index++
    Copy-Item -LiteralPath $Img.FullName -Destination ("$Share\pdf-photo-{0:D2}{1}" -f $Index,$Img.Extension.ToLowerInvariant()) -Force
}

$OverlayFiles = @(Get-ChildItem -LiteralPath $Detections -Recurse -File -Filter "*-grounding-dino.png" -ErrorAction SilentlyContinue | Sort-Object FullName)
$Index = 0
foreach ($Img in $OverlayFiles) {
    $Index++
    Copy-Item -LiteralPath $Img.FullName -Destination ("$Share\detection-{0:D2}.png" -f $Index) -Force
}

for ($i = 1; $i -le $RenderCount; $i++) {
    $Tag = "{0:D2}" -f $i
    Copy-Item -LiteralPath "$Out\candidate-$Tag.png" -Destination "$Share\candidate-$Tag.png" -Force
}
Copy-Item -LiteralPath "$Out\candidate-01.blend" -Destination "$Share\candidate-01.blend" -Force

@"
BATIFORGE FACADE MULTIVIEW V3 - A PARTAGER

A partager en priorite :
- 00-evidence-contact-sheet.jpg
- 02-vellut-detection.png
- detection-*.png
- candidate-*.png
- multiview-detections.json
- pdf-photo-assets.json

Les candidate-*.png sont DIAGNOSTIQUES : pas encore de booleans/coupes finales.
Cette version corrige la camera Blender pour regarder chaque mur depuis l'EXTERIEUR du batiment.
"@ | Set-Content -LiteralPath "$Share\README-SHARE.txt" -Encoding utf8

Write-Host "`n===== RESULTAT V3 =====" -ForegroundColor Green
Write-Host "Photos PDF extraites :" $PdfImages.Count
Write-Host "Images evidence total:" $EvidenceImages.Count
Write-Host "Overlays detection    :" $OverlayFiles.Count
Write-Host "Mappings Blender      :" $RenderCount
Write-Host "Dossier SHARE         :" $Share -ForegroundColor Cyan

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
