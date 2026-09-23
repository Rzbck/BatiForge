param(
    [string]$Root = "E:\_Project\_ProjectPython\BatiForge",
    [string]$Workspace = "espace-des-forges",
    [Parameter(Mandatory=$true)][string]$BlendPath,
    [string]$ShareDir = "",
    [string]$BlenderExe = ""
)

$ErrorActionPreference = "Stop"
Set-Location $Root

if (-not (Test-Path -LiteralPath $BlendPath)) { throw "Blend absent : $BlendPath" }
$BlendPath = (Resolve-Path -LiteralPath $BlendPath).Path

if (-not $BlenderExe) {
    $CmdBlender = Get-Command blender.exe -ErrorAction SilentlyContinue
    if ($CmdBlender) { $BlenderExe = $CmdBlender.Source }
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

$Runtime = "$Root\workspaces\$Workspace\70_facade\blender-live"
$CommandFile = "$Runtime\command.json"
$AckFile = "$Runtime\ack.json"
$HostScript = "$Root\scripts\blender\batiforge_live_host.py"
New-Item -ItemType Directory -Force -Path $Runtime | Out-Null
if (-not (Test-Path -LiteralPath $HostScript)) { throw "Host Blender absent : $HostScript" }

function Get-LiveHostPid {
    if (-not (Test-Path -LiteralPath $AckFile)) { return $null }
    try {
        $Ack = Get-Content -LiteralPath $AckFile -Raw | ConvertFrom-Json
        $PidValue = [int]$Ack.pid
        $P = Get-Process -Id $PidValue -ErrorAction SilentlyContinue
        if ($P -and $P.ProcessName -like "blender*") { return $PidValue }
    } catch {}
    return $null
}

$HostPid = Get-LiveHostPid
if (-not $HostPid) {
    # An arbitrary Blender process cannot be injected into safely. Close only Blender
    # instances that were launched on this BatiForge workspace, then start the managed host.
    $WorkspaceNeedle = "$Root\workspaces\$Workspace"
    $Existing = @(Get-CimInstance Win32_Process -Filter "Name='blender.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -and $_.CommandLine.Contains($WorkspaceNeedle) })
    foreach ($P in $Existing) {
        Write-Host "Fermeture ancienne fenetre BatiForge Blender PID $($P.ProcessId)..." -ForegroundColor Yellow
        Stop-Process -Id $P.ProcessId -Force -ErrorAction SilentlyContinue
    }

    Remove-Item $AckFile,$CommandFile -Force -ErrorAction SilentlyContinue
    Write-Host "Demarrage du host Blender BatiForge..." -ForegroundColor Cyan
    Start-Process -FilePath $BlenderExe -ArgumentList @(
        "--python", "`"$HostScript`"",
        "--",
        "--command-file", "`"$CommandFile`"",
        "--ack-file", "`"$AckFile`"",
        "--initial-blend", "`"$BlendPath`""
    ) | Out-Null

    $Deadline = (Get-Date).AddSeconds(25)
    do {
        Start-Sleep -Milliseconds 400
        $HostPid = Get-LiveHostPid
    } while (-not $HostPid -and (Get-Date) -lt $Deadline)
    if (-not $HostPid) { throw "Le host Blender n'a pas repondu dans les 25 s." }
    Write-Host "Blender host PID : $HostPid" -ForegroundColor Green
} else {
    $RequestId = [guid]::NewGuid().ToString("N")
    [ordered]@{
        request_id = $RequestId
        blend_path = $BlendPath
    } | ConvertTo-Json | Set-Content -LiteralPath $CommandFile -Encoding utf8

    $Deadline = (Get-Date).AddSeconds(15)
    $Loaded = $false
    do {
        Start-Sleep -Milliseconds 300
        if (Test-Path -LiteralPath $AckFile) {
            try {
                $Ack = Get-Content -LiteralPath $AckFile -Raw | ConvertFrom-Json
                if ($Ack.request_id -eq $RequestId) {
                    if ($Ack.status -ne "loaded") { throw "Blender host error : $($Ack.error)" }
                    $Loaded = $true
                }
            } catch {
                if ($_.Exception.Message -like "Blender host error*") { throw }
            }
        }
    } while (-not $Loaded -and (Get-Date) -lt $Deadline)
    if (-not $Loaded) { throw "Blender ouvert mais le nouveau .blend n'a pas ete charge dans les 15 s." }
    Write-Host "Projet remplace dans la meme fenetre Blender : $BlendPath" -ForegroundColor Green
}

if ($ShareDir -and (Test-Path -LiteralPath $ShareDir)) {
    Start-Process explorer.exe $ShareDir
    Write-Host "Dossier a partager : $ShareDir" -ForegroundColor Cyan
}
