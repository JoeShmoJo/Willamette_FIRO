# Standalone regression test; no Python or Pester dependency.
$ErrorActionPreference = 'Stop'
$tool = Join-Path (Split-Path -Parent $PSScriptRoot) 'Script-Data-Crosswalk.ps1'
$fixture = Join-Path ([System.IO.Path]::GetTempPath()) ('firo-crosswalk-' + [guid]::NewGuid())
try {
    foreach ($directory in 'project/src','project/outputs/final/baseline','elsewhere') {
        [void](New-Item -ItemType Directory -Path (Join-Path $fixture $directory) -Force)
    }
    $source = @'
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIRECTORY = ROOT / 'outputs'
def write_csv(frame: object, filename: str) -> Path:
    path = OUTPUT_DIRECTORY / filename
    frame.to_csv(path, index=False)
    return path
write_csv(df, 'summary.csv')
html = '''header
''' + escape(name) + '''body
'''
def export():
    final = ROOT / 'outputs' / 'final'
    for case, directory in [('after', final), ('before', final / 'baseline')]:
        table.to_csv(directory / f'alternative_{int(aid):02d}_combined_curves.csv', index=False)
    missing = final / 'not_generated.csv'
    table.to_csv(missing, index=False)
# table.to_csv(ROOT / 'outputs' / 'comment.csv')
'@
    Set-Content -LiteralPath (Join-Path $fixture 'project/src/export.py') -Value $source
    foreach ($name in 'project/outputs/summary.csv','project/outputs/final/alternative_01_combined_curves.csv','project/outputs/final/baseline/alternative_01_combined_curves.csv','elsewhere/not_generated.csv','elsewhere/alternative_02_combined_curves.csv') {
        Set-Content -LiteralPath (Join-Path $fixture $name) -Value 'test'
    }
    $rows = @(& $tool -Repository $fixture -ScanOnly)
    foreach ($name in 'project/outputs/summary.csv','project/outputs/final/alternative_01_combined_curves.csv','project/outputs/final/baseline/alternative_01_combined_curves.csv') {
        $expected = $name -replace '/', [System.IO.Path]::DirectorySeparatorChar
        if (-not @($rows | Where-Object { $_.DataPath -eq $expected -and $_.Direction -eq 'Output' -and $_.Availability -eq 'Present' }).Count) {
            throw "Present output not found: $name"
        }
    }
    if (@($rows | Where-Object { $_.DataPath -match '^elsewhere' -or $_.Literal -match 'comment.csv' }).Count) { throw 'Wrong-directory or commented reference was included' }
    $missing = @($rows | Where-Object { $_.DataFile -eq 'not_generated.csv' -and $_.Availability -eq 'Output not generated' })
    if (-not $missing.Count) { throw 'Absent output was not identified' }
    Write-Output 'Crosswalk regression checks passed.'
} finally {
    if (Test-Path -LiteralPath $fixture) { Remove-Item -LiteralPath $fixture -Recurse -Force }
}
