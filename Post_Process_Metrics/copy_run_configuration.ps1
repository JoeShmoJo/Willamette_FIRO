# Collect only configuration markers and their referenced JSON/CSV artifacts.
[CmdletBinding()]
param(
    [string]$Repo = 'C:\Projects\A_Recent_Projects\Willamette_FIRO_GIT',
    [string]$Model = 'C:\Projects\A_Recent_Projects\JYTHON\NWP_Willamette_Master_2026_11_17_ReloadFix'
)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $Repo
$Model = (Resolve-Path -LiteralPath $Model).Path.TrimEnd('\')
$Destination = Join-Path $Repo 'POST_PROCESS_METRICS\model_metadata'
$Files = @()
foreach ($Run in @('Day_Baseline_Proxy', 'Day_Alternative_Proxy')) {
    $Folder = Join-Path $Model "rss\$Run"
    if (!(Test-Path -LiteralPath $Folder)) { throw "Run folder missing: $Folder" }
    # The adapter searches up to five levels, including shared rss/watershed markers.
    for ($Level = 0; $Level -lt 5; $Level++) {
        $Markers = @(Get-ChildItem -LiteralPath $Folder -Filter '*config-active.json' -File)
        foreach ($Marker in $Markers) {
            $Files += $Marker
            $Pointer = Get-Content -LiteralPath $Marker.FullName -Raw | ConvertFrom-Json
            if ($Pointer.directory) {
                $Set = [IO.Path]::GetFullPath((Join-Path $Folder $Pointer.directory))
                if (!$Set.StartsWith($Model + '\', [StringComparison]::OrdinalIgnoreCase)) {
                    throw "Configuration points outside the model: $Set"
                }
                if (!(Test-Path -LiteralPath $Set -PathType Container)) {
                    throw "Referenced configuration folder missing: $Set"
                }
                $Files += Get-ChildItem -LiteralPath $Set -Recurse -File |
                    Where-Object { $_.Extension -in @('.json', '.csv') }
            }
        }
        if ($Folder -eq $Model) { break }
        $Folder = Split-Path -Parent $Folder
    }
}
if (!$Files.Count) { throw 'No active configuration markers found; report this result.' }
$Manifest = @()
foreach ($File in ($Files | Sort-Object FullName -Unique)) {
    $Relative = $File.FullName.Substring($Model.Length).TrimStart('\')
    $Target = Join-Path $Destination $Relative
    $Hash = (Get-FileHash -LiteralPath $File.FullName -Algorithm SHA256).Hash
    if (Test-Path -LiteralPath $Target) {
        if ((Get-FileHash -LiteralPath $Target -Algorithm SHA256).Hash -ne $Hash) {
            throw "Existing copy differs; preserve or rename it first: $Target"
        }
    } else {
        New-Item -ItemType Directory -Path (Split-Path -Parent $Target) -Force | Out-Null
        Copy-Item -LiteralPath $File.FullName -Destination $Target
    }
    $Manifest += [PSCustomObject]@{ RelativePath=$Relative; SHA256=$Hash }
}
$Manifest | Export-Csv -LiteralPath (Join-Path $Destination 'run_configuration_manifest.csv') -NoTypeInformation
Write-Host "Copied/verified $($Manifest.Count) configuration artifacts."
git status --short
