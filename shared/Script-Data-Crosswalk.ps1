param(
    [string]$Repository = (Split-Path -Parent $PSScriptRoot),
    [switch]$ScanOnly,
    [string]$ExportCsv
)
$ErrorActionPreference = 'Stop'
$Repository = (Resolve-Path -LiteralPath $Repository).Path

function Get-Crosswalk {
    param([string]$Root)
    # Exclude history, environments, third-party assets, and this tool itself.
    $excluded = '[\\/](Archive|\.git|\.venv|venv|node_modules|__pycache__|temp)[\\/]'
    $scripts = @(Get-ChildItem -LiteralPath $Root -Recurse -File |
        Where-Object { $_.FullName -notmatch $excluded -and $_.Extension -in '.py','.ps1','.R','.r','.ipynb' -and $_.Name -ne 'Script-Data-Crosswalk.ps1' })
    $files = @(Get-ChildItem -LiteralPath $Root -Recurse -File |
        Where-Object { $_.FullName -notmatch $excluded -and $_.Extension -match '^\.(csv|xlsx?|dss|pkl|pickle|parquet|json|nc|h5|hdf5|feather|yaml|yml)$' })
    $byName = @{}
    foreach ($file in $files) {
        if (-not $byName.ContainsKey($file.Name)) { $byName[$file.Name] = @() }
        $byName[$file.Name] += $file
    }
    foreach ($scriptFile in $scripts) {
        $lines = @(Get-Content -LiteralPath $scriptFile.FullName)
        $scriptText = $lines -join "`n"
        for ($i = 0; $i -lt $lines.Count; $i++) {
            $code = [string]$lines[$i]
            # Quoted literal paths only. Dynamic names are explicitly outside this scan.
            $matches = [regex]::Matches($code, '["'']([^"''\r\n]+\.(?:csv|xlsx?|dss|pkl|pickle|parquet|json|nc|h5|hdf5|feather|yaml|yml))["'']', 'IgnoreCase')
            foreach ($match in $matches) {
                $literal = $match.Groups[1].Value
                $name = ($literal -split '[\\/]')[-1]
                if ($name -match '[{}*?]') { continue }
                $candidates = @()
                if ($byName.ContainsKey($name)) { $candidates = @($byName[$name]) }
                $flow = 'Unclassified'
                if ($code -match '(?i)to_csv|to_excel|write_|dump\(|save\(|export-|OUTPUT|_OUT\b') { $flow = 'Output (inferred)' }
                elseif ($code -match '(?i)read_|load\(|INPUT|SOURCE|SETTINGS') { $flow = 'Input (inferred)' }
                elseif ($literal -match '(?i)(^|[\\/])outputs?([\\/]|$)') { $flow = 'Output (inferred)' }
                elseif ($literal -match '(?i)(^|[\\/])(data|common_data|config)([\\/]|$)') { $flow = 'Input (inferred)' }
                # Recover a multiline path assignment, then look for direct read/write use.
                $context = ($lines[[Math]::Max(0, $i - 5)..$i] -join "`n")
                $assignments = [regex]::Matches($context, '(?m)^\s*([A-Za-z_]\w*)\s*=')
                if ($assignments.Count -gt 0) {
                    $variable = [regex]::Escape($assignments[$assignments.Count - 1].Groups[1].Value)
                    if ($scriptText -match ('(?i)(read_csv|read_excel|read_pickle|require_input)\(\s*' + $variable + '\b')) {
                        $flow = 'Input (inferred)'
                    } elseif ($scriptText -match ('(?i)(to_csv|to_excel|to_pickle)\(\s*' + $variable + '\b')) {
                        $flow = 'Output (inferred)'
                    }
                }
                $state = 'Code' 
                if ($code.TrimStart() -match '^#') { $state = 'Comment only' }
                if ($candidates.Count -eq 0) { $candidates = @($null) }
                foreach ($candidate in $candidates) {
                    $relative = ''; $full = ''; $resolution = 'No existing filename match'
                    if ($null -ne $candidate) {
                        $full = $candidate.FullName
                        $relative = $full.Substring($Root.Length).TrimStart('\','/')
                        $resolution = 'Filename match; verify path'
                        if ($candidates.Count -gt 1) { $resolution = 'Multiple copies; verify path' }
                    }
                    $availability = 'Not found - direction unknown'
                    if ($null -ne $candidate) {
                        $availability = 'Found by name - verify path'
                        if ($candidates.Count -gt 1) { $availability = 'Ambiguous - multiple copies' }
                    } elseif ($flow -eq 'Input (inferred)') {
                        $availability = 'Input not found in scanned repo'
                    } elseif ($flow -eq 'Output (inferred)') {
                        $availability = 'Output not found - may not be generated'
                    }
                    if ($state -eq 'Comment only') { $availability = 'Comment only - not a requirement' }
                    [pscustomobject]@{
                        Project = ($scriptFile.FullName.Substring($Root.Length).TrimStart('\','/') -split '[\\/]')[0]
                        Script = $scriptFile.FullName.Substring($Root.Length).TrimStart('\','/')
                        Direction = $flow
                        Availability = $availability
                        DataFile = $name
                        CandidatePath = $relative
                        Resolution = $resolution
                        Reference = $state
                        Line = $i + 1
                        Literal = $literal
                        Evidence = $code.Trim()
                        ScriptPath = $scriptFile.FullName
                        FilePath = $full
                    }
                }
            }
        }
    }
}

$script:Rows = @(Get-Crosswalk -Root $Repository)
if ($ExportCsv) { $script:Rows | Export-Csv -LiteralPath $ExportCsv -NoTypeInformation -Encoding UTF8 }
if ($ScanOnly) { $script:Rows; return }

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()
$form = New-Object System.Windows.Forms.Form
$form.Text = 'Willamette: scripts, inputs and outputs'
$form.Size = New-Object System.Drawing.Size(1450,850)
$form.StartPosition = 'CenterScreen'
$panel = New-Object System.Windows.Forms.FlowLayoutPanel
$panel.Dock = 'Top'; $panel.Height = 80; $panel.WrapContents = $true
$form.Controls.Add($panel)
$label = New-Object System.Windows.Forms.Label
$label.Text = 'Search any column:'; $label.AutoSize = $true; $panel.Controls.Add($label)
$search = New-Object System.Windows.Forms.TextBox
$search.Width = 300; $panel.Controls.Add($search)
$comments = New-Object System.Windows.Forms.CheckBox
$comments.Text = 'Include commented references'; $comments.AutoSize = $true; $panel.Controls.Add($comments)
$missing = New-Object System.Windows.Forms.CheckBox
$missing.Text = 'Only files not found'; $missing.AutoSize = $true; $panel.Controls.Add($missing)
function Add-Action([string]$Text, [scriptblock]$Action) {
    $button = New-Object System.Windows.Forms.Button
    $button.Text = $Text; $button.AutoSize = $true; $button.Add_Click($Action)
    $panel.Controls.Add($button)
}
$grid = New-Object System.Windows.Forms.DataGridView
$grid.Dock = 'Fill'; $grid.ReadOnly = $true; $grid.AllowUserToAddRows = $false
$grid.SelectionMode = 'FullRowSelect'; $grid.MultiSelect = $true
$grid.AutoSizeColumnsMode = 'DisplayedCells'; $grid.RowHeadersVisible = $false
$form.Controls.Add($grid); $grid.BringToFront()
$status = New-Object System.Windows.Forms.Label
$status.Dock = 'Bottom'; $status.Height = 45
$status.Text = 'Click a column heading to sort. Select rows to open files. References are static clues, not a proven execution graph; computed paths and dynamic filenames may be missed.'
$form.Controls.Add($status)

function Update-View {
    $table = New-Object System.Data.DataTable
    foreach ($column in 'Project','Script','Direction','Availability','DataFile','CandidatePath','Resolution','Reference','Line','Literal','Evidence','ScriptPath','FilePath') {
        if ($column -eq 'Line') { [void]$table.Columns.Add($column, [int]) }
        else { [void]$table.Columns.Add($column) }
    }
    $query = $search.Text.Trim()
    foreach ($row in $script:Rows) {
        if (-not $comments.Checked -and $row.Reference -eq 'Comment only') { continue }
        if ($missing.Checked -and $row.FilePath) { continue }
        if ($query -and (($row.PSObject.Properties.Value -join ' ').IndexOf($query, [System.StringComparison]::OrdinalIgnoreCase) -lt 0)) { continue }
        $values = foreach ($column in $table.Columns) { [string]$row.($column.ColumnName) }
        [void]$table.Rows.Add([object[]]$values)
    }
    $grid.DataSource = $table
    $grid.Columns['ScriptPath'].Visible = $false; $grid.Columns['FilePath'].Visible = $false
    $grid.Columns['Evidence'].Width = 380
    $form.Text = "Willamette crosswalk - $($table.Rows.Count) references shown"
}
function Open-Selection([string]$Column, [switch]$Folder) {
    $paths = @($grid.SelectedRows | ForEach-Object { [string]$_.Cells[$Column].Value } | Where-Object { $_ } | Select-Object -Unique)
    foreach ($path in $paths) {
        if (Test-Path -LiteralPath $path) {
            if ($Folder) { Start-Process explorer.exe -ArgumentList ('/select,"' + $path + '"') }
            elseif ($Column -eq 'ScriptPath') { Start-Process notepad.exe -ArgumentList ('"' + $path + '"') }
            else { Start-Process -FilePath $path }
        }
    }
}
Add-Action 'Open data file(s)' { Open-Selection 'FilePath' }
Add-Action 'Open script(s)' { Open-Selection 'ScriptPath' }
Add-Action 'Locate data' { Open-Selection 'FilePath' -Folder }
Add-Action 'Locate script' { Open-Selection 'ScriptPath' -Folder }
Add-Action 'Refresh scan' {
    $form.UseWaitCursor = $true
    try { $script:Rows = @(Get-Crosswalk -Root $Repository); Update-View }
    finally { $form.UseWaitCursor = $false }
}
Add-Action 'Export shown CSV' {
    $dialog = New-Object System.Windows.Forms.SaveFileDialog
    $dialog.Filter = 'CSV files (*.csv)|*.csv'; $dialog.FileName = 'script-data-crosswalk.csv'
    if ($dialog.ShowDialog() -eq 'OK') {
        $visible = foreach ($row in $grid.Rows) {
            $record = [ordered]@{}
            foreach ($column in $grid.Columns) { $record[$column.Name] = $row.Cells[$column.Name].Value }
            [pscustomobject]$record
        }
        $visible | Export-Csv -LiteralPath $dialog.FileName -NoTypeInformation -Encoding UTF8
    }
}
$missing.Add_CheckedChanged({ Update-View })
$search.Add_TextChanged({ Update-View }); $comments.Add_CheckedChanged({ Update-View })
$grid.Add_CellDoubleClick({ Open-Selection 'FilePath' })
Update-View
[void]$form.ShowDialog()
