param(
    [string]$Root = "E:\_Project\_ProjectPython\BatiForge",
    [string]$Workspace = "espace-des-forges",
    [string]$SamModelId = "facebook/sam2.1-hiera-small",
    [string]$BlenderExe = ""
)

$ErrorActionPreference = "Stop"
Set-Location $Root

$Work = "$Root\workspaces\$Workspace"
$FacadeRoot = "$Work\70_facade"
$V3 = "$FacadeRoot\opening-multiview-v3"
$Multiview = "$V3\detections\multiview-detections.json"
$Page05 = "$FacadeRoot\evidence\derived\pdf_photo_assets\page-05-image-01.jpeg"
$Building = "$Work\50_roofer\sweep-detail-20260923-115605\c070\export\roofer-c070-local.obj"
$BaseBlend = "$FacadeRoot\preview\batiforge-facade-preview.blend"
$Registration = "$Root\examples\$Workspace\facade-registration-page05-v4.json"
$Out = "$FacadeRoot\facade-detail-v4"
$Share = "$Out\SHARE"
$DetailJson = "$Out\facade-detail-v4.json"
$Overlay = "$Out\page05-registration-overlay.png"
$Blend = "$Out\batiforge-facade-detail-v4.blend"
$Overview = "$Out\facade-detail-v4-overview.png"
$Front = "$Out\facade-detail-v4-front.png"
$Side = "$Out\facade-detail-v4-side.png"
$BlenderScript = "$Root\scripts\blender\build_facade_detail_v4.py"
$OpenBlender = "$Root\scripts\open_batiforge_blender.ps1"
$Uv = (Get-Command uv.exe -ErrorAction Stop).Source

if (-not (Test-Path -LiteralPath $Multiview) -or -not (Test-Path -LiteralPath $Page05)) {
    Write-Host "Evidence V3 absente : construction automatique..." -ForegroundColor Yellow
    & "$Root\scripts\build_facade_multiview_v3.ps1" -Root $Root -Workspace $Workspace -CandidateCount 3
    if ($LASTEXITCODE -ne 0) { throw "Preparation multivue V3 echouee." }
}

foreach ($Path in @($Multiview,$Page05,$Building,$BaseBlend,$Registration,$BlenderScript,$OpenBlender)) {
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
Remove-Item "$Share\*",$DetailJson,$Overlay,$Blend,$Overview,$Front,$Side -Recurse -Force -ErrorAction SilentlyContinue

$env:HF_HOME = "E:\_Project\_ProjectPython\cache\huggingface"
$env:HF_HUB_DISABLE_TELEMETRY = "1"

Write-Host "`n===== BATIFORGE FACADE DETAIL V4 =====" -ForegroundColor Cyan
Write-Host "Reference principale : photo EXTERIEURE extraite de la page 5"
Write-Host "Strategie             : 3 plans reels (pignon / nef haute / bas-cote)"
Write-Host "Placement             : homographies calibrees, PAS classement par ratio"
Write-Host "Forme                 : SAM2 quand fiable, arche pointee sinon"
Write-Host "Gate                   : STOP si la structure minimale n'est pas retrouvee"

Write-Host "`n===== 1. RECONSTRUCTION PROJECTIVE =====" -ForegroundColor Cyan
& $Uv run `
    --with "torch>=2.8,<3" `
    --with "torchvision>=0.23,<1" `
    --with "transformers>=4.56,<6" `
    --with "pillow>=11,<13" `
    --with "opencv-python-headless>=4.10,<5" `
    --with "numpy>=2,<3" `
    python -m batiforge.reconstruction.facade_projective_detail `
        --source-image $Page05 `
        --multiview-json $Multiview `
        --building-obj $Building `
        --registration-json $Registration `
        --output-json $DetailJson `
        --overlay $Overlay `
        --sam-model-id $SamModelId
if ($LASTEXITCODE -ne 0) { throw "Facade V4 refusee : fidelity gate ou reconstruction en echec." }

$D = Get-Content -LiteralPath $DetailJson -Raw | ConvertFrom-Json
Write-Host "Ouvertures acceptees :" $D.opening_count -ForegroundColor Green
Write-Host "Pignon                :" $D.counts.front_gable
Write-Host "Nef haute             :" $D.counts.side_upper
Write-Host "Bas-cote              :" $D.counts.side_lower

Write-Host "`n===== 2. GEOMETRIE BLENDER =====" -ForegroundColor Cyan
& $BlenderExe --background --factory-startup --python $BlenderScript -- `
    --base-blend $BaseBlend `
    --detail-json $DetailJson `
    --output-blend $Blend `
    --overview $Overview `
    --front $Front `
    --side $Side
if ($LASTEXITCODE -ne 0) { throw "Construction Blender V4 echouee." }

Write-Host "`n===== 3. DOSSIER SHARE =====" -ForegroundColor Cyan
Copy-Item -LiteralPath $Page05 -Destination "$Share\00-source-page5-exterior.jpg" -Force
Copy-Item -LiteralPath $Overlay -Destination "$Share\01-registration-overlay.png" -Force
Copy-Item -LiteralPath $Overview -Destination "$Share\02-overview.png" -Force
Copy-Item -LiteralPath $Front -Destination "$Share\03-front.png" -Force
Copy-Item -LiteralPath $Side -Destination "$Share\04-side.png" -Force
Copy-Item -LiteralPath $DetailJson -Destination "$Share\facade-detail-v4.json" -Force
Copy-Item -LiteralPath $Registration -Destination "$Share\facade-registration-page5-v4.json" -Force
Copy-Item -LiteralPath $Blend -Destination "$Share\batiforge-facade-detail-v4.blend" -Force

@"
BATIFORGE FACADE DETAIL V4

Cette passe abandonne les rectangles projetes sur un mur choisi par ratio.
Reference principale : photo exterieure extraite de la PAGE 5.

A partager :
- 01-registration-overlay.png
- 02-overview.png
- 03-front.png
- 04-side.png
- facade-detail-v4.json
- batiforge-facade-detail-v4.blend si necessaire

Le pignon, la nef haute et le bas-cote sont traites comme TROIS plans distincts.
SAM2 sert uniquement au contour; la position 3D vient de la calibration projective et du c070.
Si le fidelity gate echoue, aucune geometrie de facade n'est produite.
"@ | Set-Content -LiteralPath "$Share\README-SHARE.txt" -Encoding utf8

if (git status --porcelain) {
    git status --short
    throw "Worktree non CLEAN. Les sorties doivent rester sous workspace gitignore."
}

Write-Host "`n===== RESULTAT V4 =====" -ForegroundColor Green
Write-Host "Blend : $Blend"
Write-Host "Share : $Share" -ForegroundColor Cyan
Write-Host "Status: CLEAN"

& $OpenBlender `
    -Root $Root `
    -Workspace $Workspace `
    -BlendPath $Blend `
    -ShareDir $Share `
    -BlenderExe $BlenderExe
