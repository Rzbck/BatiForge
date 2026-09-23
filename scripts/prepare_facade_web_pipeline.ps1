param(
    [string]$Root = "E:\_Project\_ProjectPython\BatiForge",
    [string]$Workspace = "espace-des-forges",
    [int]$PdfDpi = 180
)

$ErrorActionPreference = "Stop"
Set-Location $Root

$Python = "$Root\.venv\Scripts\python.exe"
$FetchScript = "$Root\scripts\fetch_facade_web_evidence.ps1"
$BlenderScript = "$Root\scripts\setup_facade_blender_workspace.ps1"
$EvidenceRoot = "$Root\workspaces\$Workspace\70_facade\evidence"
$WebRoot = "$EvidenceRoot\web_original"
$Resolved = "$WebRoot\web-evidence-resolved.json"
$PdfPages = "$EvidenceRoot\derived\pdf_pages"

foreach ($Path in @($Python,$FetchScript,$BlenderScript)) {
    if (-not (Test-Path -LiteralPath $Path)) { throw "Absent : $Path" }
}

$UvCommand = Get-Command uv.exe -ErrorAction SilentlyContinue
if (-not $UvCommand) { $UvCommand = Get-Command uv -ErrorAction SilentlyContinue }
if (-not $UvCommand) { throw "uv introuvable dans PATH." }
$Uv = $UvCommand.Source

Write-Host "`n===== BATIFORGE WEB-ONLY FACADE PIPELINE =====" -ForegroundColor Cyan
Write-Host "Workspace : $Workspace"
Write-Host "Mode      : web-only / free local tooling"
Write-Host "PDF DPI   : $PdfDpi"

& $FetchScript -Root $Root -Workspace $Workspace
if ($LASTEXITCODE -ne 0) { throw "Collecte web facade echouee." }
if (-not (Test-Path -LiteralPath $Resolved)) { throw "Manifest resolu absent : $Resolved" }

& $Python -m unittest tests.test_facade_pdf_evidence -v
if ($LASTEXITCODE -ne 0) { throw "Tests PDF facade echoues." }

New-Item -ItemType Directory -Force -Path $PdfPages | Out-Null
Remove-Item "$PdfPages\*.png","$PdfPages\pdf-evidence-pages.json" -Force -ErrorAction SilentlyContinue

& $Uv run --frozen --with pymupdf python -m batiforge.reconstruction.facade_pdf_evidence `
    --resolved-manifest $Resolved `
    --output-dir $PdfPages `
    --dpi $PdfDpi
if ($LASTEXITCODE -ne 0) { throw "Extraction des pages PDF facade echouee." }

$ResolvedData = Get-Content -LiteralPath $Resolved -Raw | ConvertFrom-Json
$PdfManifest = "$PdfPages\pdf-evidence-pages.json"
$PdfData = Get-Content -LiteralPath $PdfManifest -Raw | ConvertFrom-Json
$WebImages = @(Get-ChildItem -LiteralPath $WebRoot -File -ErrorAction SilentlyContinue |
    Where-Object { $_.Extension.ToLowerInvariant() -in @('.jpg','.jpeg','.png','.webp','.tif','.tiff') })

Write-Host "`n===== EVIDENCE PREPAREE =====" -ForegroundColor Green
Write-Host "Sources cataloguees :" $ResolvedData.catalogued_count
Write-Host "Sources telechargees:" $ResolvedData.downloaded_count
Write-Host "Candidates pages web:" $ResolvedData.discovered_asset_count
Write-Host "Images web locales   :" $WebImages.Count
Write-Host "Pages PDF rendues    :" $PdfData.rendered_count

$WebImages | Select-Object Name,Length,FullName | Format-Table -AutoSize
Get-ChildItem -LiteralPath $PdfPages -File -Filter "*.png" |
    Select-Object Name,Length,FullName | Format-Table -AutoSize

& $BlenderScript -Root $Root -Workspace $Workspace
if ($LASTEXITCODE -ne 0) { throw "Scene Blender facade echouee." }

if (git status --porcelain) {
    git status --short
    throw "Worktree non CLEAN."
}
Write-Host "`nStatus : CLEAN" -ForegroundColor Green
Write-Host "Evidence root : $EvidenceRoot" -ForegroundColor Green
