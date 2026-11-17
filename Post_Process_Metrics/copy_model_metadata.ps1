# Run from PowerShell. Copies metadata only; never changes the source model.
[CmdletBinding()]
param(
    [string]$Repo = 'C:\Projects\A_Recent_Projects\Willamette_FIRO_GIT',
    [string]$Model = 'C:\Projects\A_Recent_Projects\JYTHON\NWP_Willamette_Master_2026_11_17_ReloadFix'
)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $Repo
# Use the spelling currently tracked in Git, including on case-sensitive machines.
$Destination = Join-Path $Repo 'Post_Process_Metrics\model_metadata'
$Manifest = @()
$Sources = @()
foreach ($Folder in @('scripts\alt_config', 'scripts\externalRules', 'scripts\externalSVs')) {
    $SourceFolder = Join-Path $Model $Folder
    if (!(Test-Path -LiteralPath $SourceFolder)) {
        Write-Warning "Missing metadata folder: $SourceFolder"
        continue
    }
    $Filter = if ($Folder -eq 'scripts\alt_config') { '*.txt' } else { '*.csv' }
    $Sources += Get-ChildItem -LiteralPath $SourceFolder -Filter $Filter -File -Recurse
}
foreach ($Folder in @('rss', 'rss\Day_Baseline_Proxy', 'rss\Day_Alternative_Proxy')) {
    $SourceFolder = Join-Path $Model $Folder
    if (Test-Path -LiteralPath $SourceFolder) {
        $Sources += Get-ChildItem -LiteralPath $SourceFolder -Filter 'modelReport_*.json' -File
    }
}
if (!$Sources.Count) { throw 'No model metadata found. Check the model path.' }
$ModelRoot = (Resolve-Path -LiteralPath $Model).Path.TrimEnd('\')
foreach ($File in ($Sources | Sort-Object FullName -Unique)) {
    $Relative = $File.FullName.Substring($ModelRoot.Length).TrimStart('\')
    $Target = Join-Path $Destination $Relative
    $Hash = (Get-FileHash -LiteralPath $File.FullName -Algorithm SHA256).Hash
    if (Test-Path -LiteralPath $Target) {
        if ((Get-FileHash -LiteralPath $Target -Algorithm SHA256).Hash -ne $Hash) {
            throw "Existing copy differs; preserve or rename it before retrying: $Target"
        }
    } else {
        New-Item -ItemType Directory -Path (Split-Path -Parent $Target) -Force | Out-Null
        Copy-Item -LiteralPath $File.FullName -Destination $Target
    }
    $Manifest += [PSCustomObject]@{
        RelativePath = $Relative
        SHA256 = $Hash
        SourceLastWriteUTC = $File.LastWriteTimeUtc.ToString('o')
    }
}
$Manifest | Export-Csv -LiteralPath (Join-Path $Destination 'manifest.csv') -NoTypeInformation
Write-Host "Copied/verified $($Manifest.Count) metadata files in $Destination"
Write-Host 'Review alt_config paths for additional tables outside these folders.'
Write-Host 'Reports must correspond to the DSS run; a later model compute can replace them.'
git status --short
