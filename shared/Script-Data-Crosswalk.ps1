param(
    [string]$Repository = (Split-Path -Parent $PSScriptRoot),
    [switch]$ScanOnly,
    [string]$ExportCsv
)
$ErrorActionPreference = 'Stop'
$Repository = (Resolve-Path -LiteralPath $Repository).Path

function Get-Crosswalk {
    param([string]$Root)
    $helper = Join-Path $PSScriptRoot 'resolve_script_paths.py'
    $python = $null; $prefix = @()
    foreach ($command in 'py','python','python3') {
        $found = Get-Command $command -ErrorAction SilentlyContinue
        if ($found) {
            $testArgs = @()
            if ($command -eq 'py') { $testArgs = @('-3') }
            & $found.Source @testArgs -c 'import sys; assert sys.version_info >= (3,9)' 2>$null
            if ($LASTEXITCODE -eq 0) { $python = $found.Source; $prefix = $testArgs; break }
        }
    }
    if (-not $python) { throw 'Python 3.9 or newer is required for safe Python path analysis. Install Python or activate your project environment, then reopen this tool.' }
    $json = & $python @prefix $helper $Root
    if ($LASTEXITCODE -ne 0) { throw 'Path analysis failed. See the Python error above.' }
    $report = ($json -join "`n") | ConvertFrom-Json
    $script:ScanWarnings = @($report.warnings)
    $report.rows
}

function Test-ColumnFilters {
    param($Row, [System.Collections.IDictionary]$Filters)
    foreach ($column in $Filters.Keys) {
        $query = ([string]$Filters[$column]).Trim()
        if ($query -and ([string]$Row.$column).IndexOf($query, [System.StringComparison]::OrdinalIgnoreCase) -lt 0) {
            return $false
        }
    }
    return $true
}

$script:Rows = @(Get-Crosswalk -Root $Repository)
if ($ExportCsv) { $script:Rows | Export-Csv -LiteralPath $ExportCsv -NoTypeInformation -Encoding UTF8 }
if ($ScanOnly) {
    foreach ($warning in $script:ScanWarnings) { Write-Warning $warning }
    $script:Rows; return
}

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()
$form = New-Object System.Windows.Forms.Form
$form.Text = 'Willamette: scripts, inputs and outputs'
$form.Size = New-Object System.Drawing.Size(1450,850)
$form.StartPosition = 'CenterScreen'
$panel = New-Object System.Windows.Forms.FlowLayoutPanel
$panel.Dock = 'Top'; $panel.Height = 250; $panel.WrapContents = $true; $panel.AutoScroll = $true
$form.Controls.Add($panel)
$label = New-Object System.Windows.Forms.Label
$label.Text = 'Search any column:'; $label.AutoSize = $true; $panel.Controls.Add($label)
$search = New-Object System.Windows.Forms.TextBox
$search.Width = 300; $panel.Controls.Add($search)
$missing = New-Object System.Windows.Forms.CheckBox
$missing.Text = 'Only files not found'; $missing.AutoSize = $true; $panel.Controls.Add($missing)
$script:ColumnFilters = [ordered]@{}
$script:ResettingFilters = $false
$filterPanel = New-Object System.Windows.Forms.FlowLayoutPanel
$filterPanel.Width = 1380; $filterPanel.Height = 160; $filterPanel.AutoScroll = $true
$panel.SetFlowBreak($missing, $true)
$panel.Controls.Add($filterPanel)
$panel.SetFlowBreak($filterPanel, $true)
foreach ($column in 'Project','Script','Direction','Availability','DataFile','DataPath','Resolution','Reference','FileID','Line','Literal','Evidence') {
    $group = New-Object System.Windows.Forms.FlowLayoutPanel
    $group.FlowDirection = 'TopDown'; $group.WrapContents = $false
    $group.Width = 215; $group.Height = 46
    $caption = New-Object System.Windows.Forms.Label
    $caption.Text = $column; $caption.AutoSize = $true; $group.Controls.Add($caption)
    $box = New-Object System.Windows.Forms.TextBox
    $box.Width = 205; $group.Controls.Add($box)
    $script:ColumnFilters[$column] = $box
    $box.Add_TextChanged({ Update-View })
    $filterPanel.Controls.Add($group)
}
$form.Add_Resize({ $filterPanel.Width = [Math]::Max(220, $form.ClientSize.Width - 35) })
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
$status.Text = 'Blank column filters show all values; filled filters combine. Click a column heading to sort. Select rows to open files. Files are identified by their full path. Unresolved expressions have no file assigned. Runtime overrides may change static paths; use Scan notes for limitations.'
$form.Controls.Add($status)

function Update-View {
    if ($script:ResettingFilters) { return }
    $table = New-Object System.Data.DataTable
    foreach ($column in 'Project','Script','Direction','Availability','DataFile','DataPath','Resolution','Reference','FileID','Line','Literal','Evidence','ScriptPath','FilePath') {
        if ($column -eq 'Line') { [void]$table.Columns.Add($column, [int]) }
        else { [void]$table.Columns.Add($column) }
    }
    $query = $search.Text.Trim()
    $filters = [ordered]@{}
    foreach ($column in $script:ColumnFilters.Keys) { $filters[$column] = $script:ColumnFilters[$column].Text }
    foreach ($row in $script:Rows) {
        if ($missing.Checked -and $row.Availability -eq 'Present') { continue }
        if ($query -and (($row.PSObject.Properties.Value -join ' ').IndexOf($query, [System.StringComparison]::OrdinalIgnoreCase) -lt 0)) { continue }
        if (-not (Test-ColumnFilters -Row $row -Filters $filters)) { continue }
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
Add-Action 'Reset filters' {
    $script:ResettingFilters = $true
    try {
        $search.Clear()
        foreach ($box in $script:ColumnFilters.Values) { $box.Clear() }
        $missing.Checked = $false
    } finally { $script:ResettingFilters = $false }
    Update-View
}
Add-Action 'Open data file(s)'  { Open-Selection 'FilePath' }
Add-Action 'Open script(s)' { Open-Selection 'ScriptPath' }
Add-Action 'Locate data' { Open-Selection 'FilePath' -Folder }
Add-Action 'Locate script' { Open-Selection 'ScriptPath' -Folder }
Add-Action 'Scan notes' {
    $notes = 'Python paths are read from syntax without executing project code. Relative paths with an unknown working directory remain unresolved. Runtime parameter overrides, dynamic filenames, and imported settings may not resolve.'
    if ($script:ScanWarnings.Count) { $notes += "`r`n`r`n" + ($script:ScanWarnings -join "`r`n") }
    [void][System.Windows.Forms.MessageBox]::Show($notes, 'Path analysis notes')
}
Add-Action 'Refresh scan'  {
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
$search.Add_TextChanged({ Update-View })
$grid.Add_CellDoubleClick({ Open-Selection 'FilePath' })
Update-View
[void]$form.ShowDialog()
