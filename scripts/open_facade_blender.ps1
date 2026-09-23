param(
    [string]$Root = "E:\_Project\_ProjectPython\BatiForge",
    [string]$Workspace = "espace-des-forges",
    [string]$BuildingObj = "",
    [string]$TerrainObj = "",
    [string]$BlenderExe = ""
)

$ErrorActionPreference = "Stop"
Set-Location $Root

$Work = "$Root\workspaces\$Workspace"
$PreviewScript = "$Root\scripts\blender_preview.py"
$BlendOut = "$Work\70_facade\blender\facade-preview.blend"

if (-not (Test-Path -LiteralPath $PreviewScript)) {
    throw "Absent : $PreviewScript"
}

if (-not $BuildingObj) {
    $BuildingCandidate = Get-ChildItem -LiteralPath "$Work\50_roofer" -Recurse -File -Filter "roofer-c070-local.obj" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if (-not $BuildingCandidate) {
        $BuildingCandidate = Get-ChildItem -LiteralPath "$Work\50_roofer" -Recurse -File -Filter "roofer-lod22-local.obj" -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending |
            Select-Object -First 1
    }
    if (-not $BuildingCandidate) {
        throw "Aucun OBJ Roofer local trouve sous $Work\50_roofer"
    }
    $BuildingObj = $BuildingCandidate.FullName
}

if (-not (Test-Path -LiteralPath $BuildingObj)) {
    throw "Batiment absent : $BuildingObj"
}

if (-not $TerrainObj) {
    $TerrainCandidate = Get-ChildItem -LiteralPath "$Work\60_context" -Recurse -File -Filter "context-surface.obj" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if ($TerrainCandidate) {
        $TerrainObj = $TerrainCandidate.FullName
    }
}

if ($TerrainObj -and -not (Test-Path -LiteralPath $TerrainObj)) {
    throw "Terrain absent : $TerrainObj"
}

if (-not $BlenderExe) {
    $Known = @(
        "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe",
        "C:\Program Files\Blender Foundation\Blender 5.1\blender.exe",
        "C:\Program Files\Blender Foundation\Blender 5.0\blender.exe",
        "C:\Program Files\Blender Foundation\Blender 4.5\blender.exe",
        "C:\Program Files\Blender Foundation\Blender 4.4\blender.exe"
    )
    $BlenderExe = $Known | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if (-not $BlenderExe) {
        $Command = Get-Command blender.exe -ErrorAction SilentlyContinue
        if ($Command) { $BlenderExe = $Command.Source }
    }
}

if (-not $BlenderExe -or -not (Test-Path -LiteralPath $BlenderExe)) {
    throw "Blender introuvable. Passe -BlenderExe avec le chemin de blender.exe."
}

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $BlendOut) | Out-Null

Write-Host "`n===== BATIFORGE BLENDER FACADE PREVIEW =====" -ForegroundColor Cyan
Write-Host "Blender  :" $BlenderExe
Write-Host "Building :" $BuildingObj
Write-Host "Terrain  :" $(if ($TerrainObj) { $TerrainObj } else { "<none>" })
Write-Host "Blend    :" $BlendOut
Write-Host "Import   : exact numeric XYZ, no OBJ axis reinterpretation"

$Args = [System.Collections.Generic.List[string]]::new()
$Args.Add("--python")
$Args.Add($PreviewScript)
$Args.Add("--")
$Args.Add("--building")
$Args.Add($BuildingObj)
if ($TerrainObj) {
    $Args.Add("--terrain")
    $Args.Add($TerrainObj)
}
$Args.Add("--save")
$Args.Add($BlendOut)

$Psi = [System.Diagnostics.ProcessStartInfo]::new()
$Psi.FileName = $BlenderExe
$Psi.UseShellExecute = $false
foreach ($Arg in $Args) {
    $null = $Psi.ArgumentList.Add($Arg)
}
$Process = [System.Diagnostics.Process]::Start($Psi)
if (-not $Process) { throw "Impossible de lancer Blender." }

Write-Host "Blender lance (PID $($Process.Id))." -ForegroundColor Green
