param([string]$Repository = 'C:\Projects\A_Recent_Projects\Willamette_FIRO_GIT')

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()

$ErrorActionPreference = 'Stop'
$script:Inputs = @()
$script:Preferred = @{}
$StateDirectory = Join-Path $env:LOCALAPPDATA 'Willamette Input Review'
$StateFile = Join-Path $StateDirectory 'preferred-sources.json'
if (Test-Path -LiteralPath $StateFile) {
    try {
        $state = Get-Content -LiteralPath $StateFile -Raw | ConvertFrom-Json
        foreach ($property in $state.PSObject.Properties) { $script:Preferred[$property.Name] = [string]$property.Value }
    } catch { }
}

function Get-Category([string]$Name) {
    switch -Regex ($Name) {
        '^(ElevStor|storage_elevation|04_storage_elevation_long)' { return 'Elevation-storage ratings' }
        '(rule.?curve|03_rule_curves_long|green_peter_rule_curve)' { return 'Rule curves' }
        'Drawdown_Target' { return 'Drawdown targets' }
        '^(Reservoirs|project_data|01_projects_physical)' { return 'Reservoir parameters' }
        '^(02_decision_units|08_project_allocation_caps)' { return 'Allocation units and caps' }
        '^(control_points_space|05_control_point_limits|Flood_Levels)' { return 'Control-point limits' }
        '^(project_space_summary|06_legacy_project_space_summary)' { return 'Legacy space allocations' }
        'RoutingParams' { return 'Routing parameters' }
        'RampRates' { return 'Ramp rates and flow guidelines' }
        'LocationAlias' { return 'Location names and aliases' }
        'LagConfig' { return 'Lag-time configuration' }
        'LP3|Residual' { return 'Residual frequency' }
        '^(11_system_alternatives|12_alternative_component_selections)' { return 'Alternative/component selections' }
        '^(07_project_control|1[3-8]_network|16_legacy_control)' { return 'Network relationships' }
        '^(09_source_coverage|10_data_quality|19_network_build_quality)' { return 'Input quality and coverage' }
        'Temp1Day' { return 'Testing time series' }
        default { return 'Other inputs' }
    }
}

$Hints = @{
    'Rule curves' = 'Compare dates as well as elevations. The CWMS workbook uses 2400 labels; some other files use next-day 0000. The workbook includes source correspondence. FIRO recurring curves are not identical to the common CWMS series; check Hills Creek March 1.'
    'Elevation-storage ratings' = 'storage_elevation.xlsx and ElevStor.csv contain different ratings. The FIRO long-form CSV is derived from storage_elevation.xlsx. Compare matching project/elevation rows and storage units; Green Peter conservation-storage totals differ.'
    'Reservoir parameters' = 'Compare the two SpillwayCrest columns in Reservoirs.xlsx. Several spillway values are absent from project_data.csv and the derived FIRO table. The min/max conservation elevations agree for the 11 physical projects.'
    'Control-point limits' = 'Not all these files measure the same thing: Flood_Levels.xlsx contains flows in cfs; control_points_space.csv and its FIRO derivative contain storage limits in KAF. Compare units before choosing a source.'
    'Ramp rates and flow guidelines' = 'Evacuation rates also appear in Reservoirs.xlsx, Flood_Levels.xlsx and LagConfig.xlsx. Use the Reservoir parameters or Control-point limits groups to inspect those files. Cougar/Blue River normal evacuation rates disagree between the workbooks.'
    'Lag-time configuration' = 'ResvMaxRel contains release rates and conservation storage. These overlap with Reservoirs.xlsx and project_data.csv. In particular, Green Peter storage is 249.9 KAF here versus 258.774 KAF in the FIRO input.'
    'Legacy space allocations' = 'The normalized FIRO legacy summary preserves the numerical content of project_space_summary.csv and adds project identification. Keep source lineage separate from deciding which working representation scripts should use.'
}

# Files can carry more than one kind of data. These workbook tabs are therefore
# shown in multiple relevant groups, with the tab named explicitly.
$ExtraViews = @{
    'Reservoirs.xlsx' = @(
        [PSCustomObject]@{ Category = 'Ramp rates and flow guidelines'; Detail = 'Reservoirs: NormalEvacRate / MaxEvacRate' },
        [PSCustomObject]@{ Category = 'Conservation storage'; Detail = 'Reservoirs: min/max conservation elevations' }
    )
    'Flood_Levels.xlsx' = @([PSCustomObject]@{ Category = 'Ramp rates and flow guidelines'; Detail = 'FloodLevels: evacuation rates' })
    'LagConfig.xlsx' = @(
        [PSCustomObject]@{ Category = 'Ramp rates and flow guidelines'; Detail = 'ResvMaxRel: release rates' },
        [PSCustomObject]@{ Category = 'Conservation storage'; Detail = 'ResvMaxRel: ConStorKAF' }
    )
    'project_data.csv' = @([PSCustomObject]@{ Category = 'Conservation storage'; Detail = 'ConStorageKAF' })
    '01_projects_physical.csv' = @([PSCustomObject]@{ Category = 'Conservation storage'; Detail = 'conservation_storage_kaf' })
}
$Hints['Conservation storage'] = 'Compare the same quantity, not just filenames: project_data.csv and the FIRO table use Green Peter 258.774 KAF, while LagConfig uses 249.9 KAF. Rating tables can also be used to compute max-minus-min conservation storage.'

$form = New-Object System.Windows.Forms.Form
$form.Text = 'Willamette - Compare input sources'
$form.Size = New-Object System.Drawing.Size(1450, 950)
$form.MinimumSize = New-Object System.Drawing.Size(1050, 700)
$form.StartPosition = 'CenterScreen'
$form.Font = New-Object System.Drawing.Font('Segoe UI', 10)

$top = New-Object System.Windows.Forms.Panel
$top.Dock = 'Top'; $top.Height = 108
$form.Controls.Add($top)
$repoLabel = New-Object System.Windows.Forms.Label
$repoLabel.Text = 'Repository folder:'; $repoLabel.SetBounds(12, 13, 140, 24); $top.Controls.Add($repoLabel)
$repoBox = New-Object System.Windows.Forms.TextBox
$repoBox.Text = $Repository; $repoBox.SetBounds(155, 10, 1000, 28)
$repoBox.Anchor = 'Top, Left, Right'; $top.Controls.Add($repoBox)
$browse = New-Object System.Windows.Forms.Button
$browse.Text = 'Browse...'; $browse.SetBounds(1165, 8, 100, 32); $browse.Anchor = 'Top, Right'; $top.Controls.Add($browse)
$scan = New-Object System.Windows.Forms.Button
$scan.Text = 'Scan / refresh'; $scan.SetBounds(1275, 8, 140, 32); $scan.Anchor = 'Top, Right'; $top.Controls.Add($scan)
$instructions = New-Object System.Windows.Forms.Label
$instructions.Text = '1. Choose a data type on the left.   2. Ctrl-click competing sources.   3. Open the files, then inspect the scripts below.'
$instructions.SetBounds(12, 48, 1390, 24); $instructions.Anchor = 'Top, Left, Right'; $top.Controls.Add($instructions)
$filter = New-Object System.Windows.Forms.TextBox
$filter.SetBounds(155, 76, 620, 26); $top.Controls.Add($filter)
$filterLabel = New-Object System.Windows.Forms.Label
$filterLabel.Text = 'Filter files/scripts:'; $filterLabel.SetBounds(12, 78, 140, 24); $top.Controls.Add($filterLabel)
$status = New-Object System.Windows.Forms.Label
$status.Text = 'Ready'; $status.SetBounds(790, 78, 620, 24); $status.Anchor = 'Top, Left, Right'; $top.Controls.Add($status)

$body = New-Object System.Windows.Forms.SplitContainer
$body.Size = New-Object System.Drawing.Size(1400, 750)
$body.Dock = 'Fill'; $body.SplitterDistance = 270; $body.Panel1MinSize = 150
$form.Controls.Add($body); $body.BringToFront()
$groups = New-Object System.Windows.Forms.ListBox
$groups.Dock = 'Fill'; $groups.DisplayMember = 'Label'; $body.Panel1.Controls.Add($groups)

$right = New-Object System.Windows.Forms.TableLayoutPanel
$right.Dock = 'Fill'; $right.ColumnCount = 1; $right.RowCount = 6
foreach ($height in @(78, 40, 0, 26, 0, 38)) {
    $style = New-Object System.Windows.Forms.RowStyle
    if ($height -eq 0) { $style.SizeType = 'Percent'; $style.Height = 50 }
    else { $style.SizeType = 'Absolute'; $style.Height = $height }
    [void]$right.RowStyles.Add($style)
}
$body.Panel2.Controls.Add($right)
$hint = New-Object System.Windows.Forms.Label
$hint.Dock = 'Fill'; $hint.Padding = New-Object System.Windows.Forms.Padding(8)
$hint.BackColor = [System.Drawing.Color]::FromArgb(239, 245, 251)
$right.Controls.Add($hint, 0, 0)
$buttons = New-Object System.Windows.Forms.FlowLayoutPanel
$buttons.Dock = 'Fill'; $right.Controls.Add($buttons, 0, 1)
function Add-Button([string]$Text, [int]$Width) {
    $button = New-Object System.Windows.Forms.Button
    $button.Text = $Text; $button.Width = $Width; $button.Height = 30
    $buttons.Controls.Add($button); return $button
}
$openFiles = Add-Button 'Open selected files' 160
$folderButton = Add-Button 'Show file in Explorer' 175
$preferButton = Add-Button 'Mark preferred source' 180
$clearButton = Add-Button 'Clear preference' 140

$filesView = New-Object System.Windows.Forms.ListView
$filesView.Dock = 'Fill'; $filesView.View = 'Details'; $filesView.FullRowSelect = $true
$filesView.MultiSelect = $true; $filesView.HideSelection = $false; $filesView.GridLines = $true
foreach ($column in @(@('Preferred', 85), @('Source file', 350), @('Data / workbook tab', 280), @('Role', 100), @('Scripts', 80), @('KB', 75))) {
    [void]$filesView.Columns.Add([string]$column[0], [int]$column[1])
}
$right.Controls.Add($filesView, 0, 2)
$refLabel = New-Object System.Windows.Forms.Label
$refLabel.Text = 'Scripts referencing the selected sources (double-click a row to open a script):'
$refLabel.Dock = 'Fill'; $right.Controls.Add($refLabel, 0, 3)
$refsView = New-Object System.Windows.Forms.ListView
$refsView.Dock = 'Fill'; $refsView.View = 'Details'; $refsView.FullRowSelect = $true
$refsView.MultiSelect = $true; $refsView.HideSelection = $false; $refsView.GridLines = $true
foreach ($column in @(@('Input source', 280), @('Script', 340), @('Line', 60), @('Code', 550))) {
    [void]$refsView.Columns.Add([string]$column[0], [int]$column[1])
}
$right.Controls.Add($refsView, 0, 4)
$bottom = New-Object System.Windows.Forms.FlowLayoutPanel
$bottom.Dock = 'Fill'; $right.Controls.Add($bottom, 0, 5)
$openScript = New-Object System.Windows.Forms.Button
$openScript.Text = 'View selected script'; $openScript.Width = 175; $openScript.Height = 30; $bottom.Controls.Add($openScript)
$scriptFolder = New-Object System.Windows.Forms.Button
$scriptFolder.Text = 'Show script in Explorer'; $scriptFolder.Width = 185; $scriptFolder.Height = 30; $bottom.Controls.Add($scriptFolder)
$note = New-Object System.Windows.Forms.Label
$note.Text = 'References are filename matches, not proof of execution. Dynamic paths may need following through the code.'
$note.AutoSize = $true; $note.Padding = New-Object System.Windows.Forms.Padding(5, 6, 0, 0); $bottom.Controls.Add($note)

function Show-Error([string]$Message) {
    [void][System.Windows.Forms.MessageBox]::Show($form, $Message, 'Input review', 'OK', 'Error')
}
function Show-Explorer([string]$Path) {
    Start-Process -FilePath explorer.exe -ArgumentList ('/select,"{0}"' -f $Path)
}
function Save-Preferences {
    New-Item -ItemType Directory -Path $StateDirectory -Force | Out-Null
    $script:Preferred | ConvertTo-Json | Set-Content -LiteralPath $StateFile -Encoding UTF8
}
function Update-References {
    $refsView.BeginUpdate(); $refsView.Items.Clear()
    $seen = @{}
    $items = @($filesView.SelectedItems)
    if ($items.Count -eq 0) { $items = @($filesView.Items); $refLabel.Text = 'Scripts for all sources in this group (select files above to narrow the list):' }
    else { $refLabel.Text = 'Scripts referencing selected sources (double-click a row to view the script):' }
    foreach ($item in $items) {
        foreach ($reference in $item.Tag.References) {
            $key = $item.Tag.Relative + '|' + $reference.Path + '|' + $reference.Line
            if ($seen.ContainsKey($key)) { continue }; $seen[$key] = $true
            $row = New-Object System.Windows.Forms.ListViewItem($item.Tag.Relative)
            [void]$row.SubItems.Add($reference.Relative)
            [void]$row.SubItems.Add([string]$reference.Line)
            [void]$row.SubItems.Add($reference.Code)
            $row.Tag = $reference; [void]$refsView.Items.Add($row)
        }
    }
    $refsView.EndUpdate()
}
function Update-Files {
    if ($null -eq $groups.SelectedItem) { return }
    $category = $groups.SelectedItem.Name
    if ($Hints.ContainsKey($category)) { $hint.Text = $Hints[$category] }
    else { $hint.Text = 'Select two or more source files with Ctrl-click and use Open selected files. The scripts that mention those filenames appear below. Marking a preference saves your choice outside the repository; it does not change input files or scripts.' }
    $query = $filter.Text.Trim()
    $filesView.BeginUpdate(); $filesView.Items.Clear()
    foreach ($file in $script:Inputs | Where-Object Category -eq $category | Sort-Object Relative, Detail) {
        $haystack = $file.Relative + ' ' + (($file.References | ForEach-Object Relative) -join ' ')
        if ($query -and $haystack.IndexOf($query, [StringComparison]::OrdinalIgnoreCase) -lt 0) { continue }
        $preferred = ''
        if ($script:Preferred[$category] -eq $file.Relative) { $preferred = 'Preferred' }
        $row = New-Object System.Windows.Forms.ListViewItem($preferred)
        foreach ($value in @($file.Relative, $file.Detail, $file.Role, [string](@($file.References | Select-Object -ExpandProperty Path -Unique).Count), [string]$file.KB)) {
            [void]$row.SubItems.Add($value)
        }
        $row.Tag = $file
        if ($preferred) { $row.BackColor = [System.Drawing.Color]::Honeydew }
        [void]$filesView.Items.Add($row)
    }
    $filesView.EndUpdate()
    Update-References
}

function Scan-Repository {
    try {
        $scan.Enabled = $false; $form.UseWaitCursor = $true
        $status.Text = 'Scanning active inputs and scripts...'; $form.Refresh()
        if (-not (Test-Path -LiteralPath $repoBox.Text -PathType Container)) { throw 'Choose a valid repository folder.' }
        $script:RepoRoot = (Resolve-Path -LiteralPath $repoBox.Text).Path.TrimEnd('\')
        $candidates = @()
        foreach ($relative in @('shared', 'FIRO_COMPONENTS\data', 'ROUTING_RAMP_EVACUATION\config', 'DELAYED_DRAWDOWN_SCREENING\config', 'RULE_CURVE_WORKSHOP\config')) {
            $path = Join-Path $script:RepoRoot $relative
            if (Test-Path -LiteralPath $path) {
                $candidates += Get-ChildItem -LiteralPath $path -File -Recurse | Where-Object Name -Match '\.(xlsx|xls|csv|csv\.gz|dss|pkl|pickle|json|yaml|yml)$'
            }
        }
        $candidates = @($candidates | Sort-Object FullName -Unique)
        if ($candidates.Count -eq 0) { throw 'No inputs found. Update your checkout or choose the folder containing shared and FIRO_COMPONENTS.' }
        $byName = @{}
        foreach ($file in $candidates) {
            if (-not $byName.ContainsKey($file.Name)) { $byName[$file.Name] = New-Object System.Collections.ArrayList }
        }
        $pattern = '(?i)(' + (($byName.Keys | Sort-Object Length -Descending | ForEach-Object { [regex]::Escape($_) }) -join '|') + ')'
        $regex = New-Object System.Text.RegularExpressions.Regex($pattern)
        $queue = New-Object 'System.Collections.Generic.Queue[string]'
        $queue.Enqueue($script:RepoRoot); $scriptCount = 0
        $exclude = @('.git', '.venv', 'venv', 'node_modules', '__pycache__', 'Archive', 'outputs', 'out', 'outputs_ek_trial', 'input-review')
        while ($queue.Count) {
            $directory = $queue.Dequeue()
            foreach ($item in Get-ChildItem -LiteralPath $directory -Force -ErrorAction Stop) {
                if ($item.PSIsContainer) {
                    if ($item.Name -notin $exclude -and -not ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) { $queue.Enqueue($item.FullName) }
                } elseif ($item.Extension.ToLower() -in @('.py', '.ps1', '.r', '.sh', '.bat', '.cmd')) {
                    $scriptCount++; $number = 0
                    foreach ($line in [IO.File]::ReadAllLines($item.FullName)) {
                        $number++
                        foreach ($match in $regex.Matches($line)) {
                            [void]$byName[$match.Value].Add([PSCustomObject]@{ Path = $item.FullName; Relative = $item.FullName.Substring($script:RepoRoot.Length + 1); Line = $number; Code = $line.Trim() })
                        }
                    }
                }
            }
        }
        $script:Inputs = @(
            foreach ($file in $candidates) {
                $relative = $file.FullName.Substring($script:RepoRoot.Length + 1)
                $role = 'Shared source'
                if ($relative -like 'FIRO_COMPONENTS\data\*') { $role = 'FIRO input' }
                if ($relative -match 'backup') { $role = 'Backup' }
                if ($relative -match '\\config\\') { $role = 'Configuration' }
                $views = @([PSCustomObject]@{ Category = (Get-Category $file.Name); Detail = 'Whole file' })
                if ($ExtraViews.ContainsKey($file.Name)) { $views += $ExtraViews[$file.Name] }
                foreach ($view in $views) {
                    [PSCustomObject]@{ Category = $view.Category; Detail = $view.Detail; Relative = $relative; Path = $file.FullName; Role = $role; KB = [Math]::Round($file.Length / 1KB, 1); References = @($byName[$file.Name]) }
                }
            }
        )
        $groups.Items.Clear()
        foreach ($group in $script:Inputs | Group-Object Category | Sort-Object Name) {
            [void]$groups.Items.Add([PSCustomObject]@{ Name = $group.Name; Label = ('{0} ({1})' -f $group.Name, $group.Count) })
        }
        if ($groups.Items.Count) { $groups.SelectedIndex = 0 }
        $status.Text = '{0} source files; {1} active scripts scanned' -f $candidates.Count, $scriptCount
    } catch { Show-Error $_.Exception.Message; $status.Text = 'Scan failed; see message.' }
    finally { $scan.Enabled = $true; $form.UseWaitCursor = $false }
}

$browse.Add_Click({
    $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
    $dialog.Description = 'Choose the Willamette repository folder'
    if (Test-Path -LiteralPath $repoBox.Text) { $dialog.SelectedPath = $repoBox.Text }
    if ($dialog.ShowDialog() -eq 'OK') { $repoBox.Text = $dialog.SelectedPath; Scan-Repository }
    $dialog.Dispose()
})
$scan.Add_Click({ Scan-Repository })
$groups.Add_SelectedIndexChanged({ Update-Files })
$filter.Add_TextChanged({ Update-Files })
$filesView.Add_SelectedIndexChanged({ Update-References })
$openFiles.Add_Click({
    if ($filesView.SelectedItems.Count -eq 0) { Show-Error 'Select the source files you want to open. Use Ctrl-click to select more than one.'; return }
    try { foreach ($item in $filesView.SelectedItems) { Invoke-Item -LiteralPath $item.Tag.Path } }
    catch { Show-Error $_.Exception.Message }
})
$filesView.Add_DoubleClick({
    try { foreach ($item in $filesView.SelectedItems) { Invoke-Item -LiteralPath $item.Tag.Path } }
    catch { Show-Error $_.Exception.Message }
})
$folderButton.Add_Click({ foreach ($item in $filesView.SelectedItems) { Show-Explorer $item.Tag.Path } })
$preferButton.Add_Click({
    if ($filesView.SelectedItems.Count -ne 1) { Show-Error 'Select one source file to mark as preferred.'; return }
    $script:Preferred[$groups.SelectedItem.Name] = $filesView.SelectedItems[0].Tag.Relative
    try { Save-Preferences; Update-Files } catch { Show-Error $_.Exception.Message }
})
$clearButton.Add_Click({
    if ($null -ne $groups.SelectedItem) { $script:Preferred.Remove($groups.SelectedItem.Name); Save-Preferences; Update-Files }
})
$openSelectedScript = {
    foreach ($item in $refsView.SelectedItems) {
        Start-Process -FilePath notepad.exe -ArgumentList ('"{0}"' -f $item.Tag.Path)
    }
}
$openScript.Add_Click($openSelectedScript)
$refsView.Add_DoubleClick($openSelectedScript)
$scriptFolder.Add_Click({ foreach ($item in $refsView.SelectedItems) { Show-Explorer $item.Tag.Path } })
$form.Add_Shown({ Scan-Repository })
[void]$form.ShowDialog()
$form.Dispose()
