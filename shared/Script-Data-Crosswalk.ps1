param(
    [string]$Repository = (Split-Path -Parent $PSScriptRoot),
    [switch]$ScanOnly,
    [string]$ExportCsv
)
$ErrorActionPreference = 'Stop'
$Repository = (Resolve-Path -LiteralPath $Repository).Path

function Resolve-SourcePath {
    param([string]$Expression, [hashtable]$Variables, [string]$ScriptFile)
    $expressionText = $Expression.Trim()
    # A deliberately small path-expression parser. Never evaluates source as code.
    $expressionText = $expressionText -replace '(?m)\s+#.*$', ''
    $expressionText = $expressionText.Trim()
    while ($expressionText.StartsWith('(') -and $expressionText.EndsWith(')')) {
        $expressionText = $expressionText.Substring(1, $expressionText.Length - 2).Trim()
    }
    $base = $null; $tail = ''
    if ($expressionText -match '^Path\(__file__\)(?:\.resolve\(\))?') {
        $base = [System.IO.Path]::GetFullPath($ScriptFile)
        $tail = $expressionText.Substring($Matches[0].Length)
    } elseif ($expressionText -match '^([A-Za-z_]\w*)') {
        $variable = $Matches[1]
        if ($Variables.ContainsKey($variable)) { $base = $Variables[$variable] }
        if ($null -eq $base) { return $null }
        $tail = $expressionText.Substring($variable.Length)
    } elseif ($expressionText -match '^[rR]?["'']([^"'']+)["'']$') {
        # Bare relative strings depend on the runtime working directory.
        if ([System.IO.Path]::IsPathRooted($Matches[1])) { return [System.IO.Path]::GetFullPath($Matches[1]) }
        return $null
    } else { return $null }
    while ($tail.Trim()) {
        $tail = $tail.Trim()
        if ($tail -match '^\.parent\b') {
            $base = Split-Path -Parent $base; $tail = $tail.Substring($Matches[0].Length)
        } elseif ($tail -match '^\.parents\[(\d+)\]') {
            $count = [int]$Matches[1] + 1; $length = $Matches[0].Length
            for ($n = 0; $n -lt $count; $n++) { $base = Split-Path -Parent $base }
            $tail = $tail.Substring($length)
        } elseif ($tail -match '^\s*/\s*[rR]?["'']([^"'']+)["'']') {
            $part = $Matches[1]; $length = $Matches[0].Length
            if ($part -match '[{}*?]') { return $null }
            $base = Join-Path $base ($part -replace '[\\/]', [System.IO.Path]::DirectorySeparatorChar)
            $tail = $tail.Substring($length)
        } else { return $null }
    }
    if ($base) { return [System.IO.Path]::GetFullPath($base) }
    return $null
}

function Get-Crosswalk {
    param([string]$Root)
    $script:ScanWarnings = @()
    $excluded = '[\\/](Archive|\.git|\.venv|venv|node_modules|__pycache__|temp)[\\/]'
    $scripts = @(Get-ChildItem -LiteralPath $Root -Recurse -File |
        Where-Object { $_.FullName -notmatch $excluded -and $_.Extension -in '.py','.ps1','.r','.R','.ipynb' -and $_.Name -ne 'Script-Data-Crosswalk.ps1' })
    foreach ($source in $scripts) {
        if ($source.Extension -ne '.py') {
            $script:ScanWarnings += "$($source.FullName): path analysis currently supports Python source only"
            continue
        }
        $lines = @(Get-Content -LiteralPath $source.FullName)
        $clean = New-Object System.Collections.Generic.List[string]
        $docQuote = ''
        foreach ($line in $lines) {
            # Ignore whole comments and triple-quoted text, preserving line numbers.
            if ($docQuote) {
                if ($line.Contains($docQuote)) { $docQuote = '' }
                $clean.Add(''); continue
            }
            if ($line -match '("""|'''''')') {
                $quote = $Matches[1]
                if ([regex]::Matches($line, [regex]::Escape($quote)).Count -eq 1) { $docQuote = $quote }
                $clean.Add(''); continue
            }
            if ($line.TrimStart().StartsWith('#')) { $clean.Add('') } else { $clean.Add($line) }
        }
        $text = $clean -join "`n"
        $variables = @{}; $definitions = New-Object System.Collections.Generic.List[object]
        for ($i = 0; $i -lt $clean.Count; $i++) {
            # Only module-level constants: do not mistake local variables for globals.
            if ($clean[$i] -notmatch '^([A-Za-z_]\w*)\s*=\s*(.*)$') { continue }
            $variable = $Matches[1]; $expressionText = $Matches[2]; $lineNumber = $i + 1
            if ($expressionText.Trim() -eq '(') {
                while ($i + 1 -lt $clean.Count) {
                    $i++; $expressionText += ' ' + $clean[$i].Trim()
                    if ($clean[$i].Trim() -eq ')') { break }
                }
            }
            $full = Resolve-SourcePath $expressionText $variables $source.FullName
            $variables[$variable] = $full
            $definitions.Add([pscustomobject]@{ Variable=$variable; Expression=$expressionText; Full=$full; Line=$lineNumber })
        }
        # A function parameter or local assignment can shadow a module constant.
        # Block those names rather than resolving them to the wrong global path.
        $functionScopes = @{}
        for ($start = 0; $start -lt $clean.Count; $start++) {
            if ($clean[$start] -notmatch '^def\s+\w+\(([^)]*)\)') { continue }
            $parameters = $Matches[1]; $blocked = @{}
            foreach ($parameter in ($parameters -split ',')) {
                if ($parameter.Trim() -match '^([A-Za-z_]\w*)') { $blocked[$Matches[1]] = $true }
            }
            $end = $start + 1
            while ($end -lt $clean.Count -and ($clean[$end] -match '^\s' -or -not $clean[$end].Trim())) {
                if ($clean[$end] -match '^\s+([A-Za-z_]\w*)\s*=') { $blocked[$Matches[1]] = $true }
                if ($clean[$end] -match '^\s+for\s+([A-Za-z_]\w*)\s+in') { $blocked[$Matches[1]] = $true }
                $end++
            }
            for ($lineIndex = $start + 1; $lineIndex -lt $end; $lineIndex++) { $functionScopes[$lineIndex] = $blocked }
        }
        $references = New-Object System.Collections.Generic.List[object]
        foreach ($definition in $definitions) {
            if ($definition.Expression -notmatch '\.(csv|xlsx?|dss|pkl|pickle|parquet|json|nc|h5|hdf5|feather|yaml|yml)["'']') { continue }
            $escaped = [regex]::Escape($definition.Variable)
            $roles = @()
            if ($text -match ('(?is)(read_csv|read_excel|read_pickle|read_parquet|read_json|require_input|open)\(\s*' + $escaped + '\b')) { $roles += 'Input' }
            if ($text -match ('(?is)(to_csv|to_excel|to_pickle|to_parquet|to_json)\(\s*' + $escaped + '\b')) { $roles += 'Output' }
            if (-not $roles.Count) { $roles = @('Unclassified') }
            foreach ($role in $roles) {
                $references.Add([pscustomobject]@{ Full=$definition.Full; Expression=$definition.Expression; Line=$definition.Line; Direction=$role })
            }
        }
        # Recognize direct I/O calls and explicitly anchored expressions. Unknown locals
        # and relative string literals stay unresolved; no filename search is performed.
        for ($i = 0; $i -lt $clean.Count; $i++) {
            $callMatches = [regex]::Matches($clean[$i], '\b(read_csv|read_excel|read_pickle|read_parquet|read_json|require_input|open|to_csv|to_excel|to_pickle|to_parquet|to_json)\(\s*(.*)')
            foreach ($call in $callMatches) {
                $operation = $call.Groups[1].Value
                $argument = $call.Groups[2].Value
                if ($argument -match '^([A-Za-z_]\w*)\s*[,)]') { $argument = $Matches[1] }
                elseif ($argument -match '^([rR]?["''][^"'']+["''])\s*[,)]') { $argument = $Matches[1] }
                else { $argument = $argument -replace ',\s*(index|encoding|sheet_name|header|parse_dates)\s*=.*$', ''; $argument = $argument -replace '\)\s*$', '' }
                $callVariables = $variables
                if ($functionScopes.ContainsKey($i)) {
                    $callVariables = $variables.Clone()
                    foreach ($blockedName in $functionScopes[$i].Keys) { $callVariables.Remove($blockedName) }
                }
                $full = Resolve-SourcePath $argument $callVariables $source.FullName
                if (-not $full -and $argument -notmatch '\.(csv|xlsx?|dss|pkl|pickle|parquet|json|nc|h5|hdf5|feather|yaml|yml)["'']') { continue }
                if ($full -and $full -notmatch '\.(csv|xlsx?|dss|pkl|pickle|parquet|json|nc|h5|hdf5|feather|yaml|yml)$') { continue }
                $direction = 'Input'
                if ($operation -match '^to_') { $direction = 'Output' }
                if ($operation -eq 'open' -and $call.Value -match ',\s*["''][wax][^"'']*["'']') { $direction = 'Output' }
                $references.Add([pscustomobject]@{ Full=$full; Expression=$argument; Line=$i+1; Direction=$direction })
            }
        }
        # Resolve the common write_csv(frame, 'name.csv') wrapper only when its
        # body explicitly joins a known global directory to its filename argument.
        $helperMatch = [regex]::Match($text, '(?ms)^def write_csv\(\s*\w+\s*,\s*(\w+)\s*\):\s*\n(.*?)(?=^\S|\z)')
        if ($helperMatch.Success) {
            $filenameArgument = [regex]::Escape($helperMatch.Groups[1].Value)
            $body = $helperMatch.Groups[2].Value
            $join = [regex]::Match($body, ('(?m)^\s*(\w+)\s*=\s*(\w+)\s*/\s*' + $filenameArgument + '\b'))
            if ($join.Success -and $variables.ContainsKey($join.Groups[2].Value) -and $variables[$join.Groups[2].Value]) {
                $pathVariable = [regex]::Escape($join.Groups[1].Value)
                if ($body -match ('(?s)\.to_csv\(\s*' + $pathVariable + '\b')) {
                    foreach ($call in [regex]::Matches($text, '\bwrite_csv\(\s*\w+\s*,\s*["'']([^"'']+\.csv)["'']\s*[,)]')) {
                        $filename = $call.Groups[1].Value
                        if ($filename -match '[{}*?]') { continue }
                        $full = [System.IO.Path]::GetFullPath((Join-Path $variables[$join.Groups[2].Value] $filename))
                        $lineNumber = [regex]::Matches($text.Substring(0, $call.Index), "`n").Count + 1
                        $references.Add([pscustomobject]@{ Full=$full; Expression=$call.Value; Line=$lineNumber; Direction='Output' })
                    }
                }
            }
        }
        foreach ($reference in $references) {
            $full = [string]$reference.Full
            $display = ''; $name = ''; $resolution = 'Path unresolved - no file assigned'; $availability = 'Path unresolved'
            if ($full) {
                $display = $full
                if ($full.StartsWith($Root + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) { $display = $full.Substring($Root.Length + 1) }
                $name = [System.IO.Path]::GetFileName($full)
                $resolution = 'Resolved static path'
                if (Test-Path -LiteralPath $full -PathType Leaf) { $availability = 'Present' }
                elseif ($reference.Direction -eq 'Input') { $availability = 'Missing input' }
                elseif ($reference.Direction -eq 'Output') { $availability = 'Output not generated' }
                else { $availability = 'File absent - role unclassified' }
            } elseif ($reference.Expression -match '["'']([^"'']+\.(csv|xlsx?|dss|pkl|pickle|parquet|json|nc|h5|hdf5|feather|yaml|yml))["'']') {
                $name = ($Matches[1] -split '[\\/]')[-1]
            }
            $relativeScript = $source.FullName.Substring($Root.Length).TrimStart('\','/')
            $fileID = $full
            if ([System.IO.Path]::DirectorySeparatorChar -eq '\') { $fileID = $fileID.ToLowerInvariant() }
            [pscustomobject]@{
                Project=($relativeScript -split '[\\/]')[0]; Script=$relativeScript
                Direction=$reference.Direction; Availability=$availability; DataFile=$name
                DataPath=$display; Resolution=$resolution; Reference='Code'; FileID=$fileID
                Line=$reference.Line; Literal=$reference.Expression; Evidence=$lines[$reference.Line-1].Trim()
                ScriptPath=$source.FullName; FilePath=$full
            }
        }
    }
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
    $notes = 'PowerShell reads supported Python path expressions without executing project code. Relative paths with an unknown working directory remain unresolved. Runtime parameter overrides, dynamic filenames, and imported settings may not resolve.'
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
