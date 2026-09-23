param(
    [string]$Root = "E:\_Project\_ProjectPython\BatiForge",
    [string]$Workspace = "espace-des-forges",
    [string]$Manifest = "examples\espace-des-forges\facade-web-sources.json"
)

$ErrorActionPreference = "Stop"
Set-Location $Root

$Python = "$Root\.venv\Scripts\python.exe"
$ManifestPath = Join-Path $Root $Manifest
$Out = "$Root\workspaces\$Workspace\70_facade\evidence\web_original"

foreach ($Path in @($Python,$ManifestPath)) {
    if (-not (Test-Path -LiteralPath $Path)) { throw "Absent : $Path" }
}

Write-Host "`n===== BATIFORGE FACADE WEB EVIDENCE =====" -ForegroundColor Cyan
Write-Host "Workspace : $Workspace"
Write-Host "Manifest  : $ManifestPath"
Write-Host "Output    : $Out"
Write-Host "Mode      : web-only / provenance-first"

& $Python -m unittest tests.test_facade_web_evidence -v
if ($LASTEXITCODE -ne 0) { throw "Tests facade web evidence echoues." }

& $Python -m batiforge.reconstruction.facade_web_evidence `
    --manifest $ManifestPath `
    --output-dir $Out
if ($LASTEXITCODE -ne 0) { throw "Collecte facade web echouee." }

$Resolved = Join-Path $Out "web-evidence-resolved.json"
$M = Get-Content -LiteralPath $Resolved -Raw | ConvertFrom-Json

Write-Host "`n===== RESULTAT =====" -ForegroundColor Green
Write-Host "Sources cataloguees :" $M.catalogued_count
Write-Host "Sources telechargees:" $M.downloaded_count

$Rows = foreach ($S in $M.sources) {
    [PSCustomObject]@{
        Id = $S.id
        Kind = $S.kind
        Status = $S.status
        Usage = $S.geometry_usage
        Local = $S.local_path
    }
}
$Rows | Format-Table -AutoSize

if (git status --porcelain) {
    git status --short
    throw "Worktree non CLEAN. Les donnees web doivent rester sous workspace gitignore."
}
Write-Host "Status : CLEAN" -ForegroundColor Green
Write-Host "`nMANIFEST RESOLU : $Resolved" -ForegroundColor Green
Start-Process explorer.exe $Out
