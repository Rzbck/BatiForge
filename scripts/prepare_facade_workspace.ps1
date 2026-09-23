param(
    [string]$Root = "E:\_Project\_ProjectPython\BatiForge",
    [string]$Workspace = "espace-des-forges"
)

$ErrorActionPreference = "Stop"
Set-Location $Root

$Work = "$Root\workspaces\$Workspace"
$Facade = "$Work\70_facade"
$Dirs = @(
    "$Facade\images_raw",
    "$Facade\images_selected",
    "$Facade\colmap",
    "$Facade\diagnostics",
    "$Facade\blender"
)

foreach ($Dir in $Dirs) {
    New-Item -ItemType Directory -Force -Path $Dir | Out-Null
}

$Manifest = "$Facade\capture-session.json"
if (-not (Test-Path -LiteralPath $Manifest)) {
    $Payload = [ordered]@{
        schema_version = 1
        workspace = $Workspace
        source = "user_capture"
        provenance = "user-owned originals"
        status = "awaiting_images"
        created_utc = [DateTime]::UtcNow.ToString("o")
        originals_dir = "$Facade\images_raw"
        selected_dir = "$Facade\images_selected"
        notes = @(
            "Keep original image bytes and EXIF when available.",
            "Do not treat imagery as metric truth until COLMAP output is registered to the RNB/LiDAR frame.",
            "No generated facade geometry before image coverage and reconstruction quality gates pass."
        )
    }
    $Payload | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $Manifest -Encoding utf8
}

Write-Host "`n===== BATIFORGE FACADE WORKSPACE =====" -ForegroundColor Cyan
Write-Host "Workspace : $Workspace"
Write-Host "Raw photos:" "$Facade\images_raw"
Write-Host "Selected  :" "$Facade\images_selected"
Write-Host "COLMAP    :" "$Facade\colmap"
Write-Host "Blender   :" "$Facade\blender"
Write-Host "Manifest  :" $Manifest
Write-Host "`nPut untouched facade photos in images_raw." -ForegroundColor Green

if (git status --porcelain) {
    git status --short
    throw "Worktree non CLEAN after workspace preparation. Generated workspace content must stay gitignored."
}
Write-Host "Status    : CLEAN" -ForegroundColor Green
