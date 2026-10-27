# Script, input, and output crosswalk

Double-click **Start-Script-Data-Crosswalk.cmd** in this folder on Windows.
The tool finds the repository automatically from its own location.
It does not execute analysis scripts or modify their data.

1. Search for a data filename, project, script name, or part of a path.
2. Click any column heading to sort. Sort by **DataFile** to group scripts
   mentioning the same data, or by **Script** to inspect one script's references.
3. Select rows (Ctrl-click for several) and use **Open data file(s)** to compare
   files in their default applications. **Open script(s)** uses Notepad;
   the **Line** and **Evidence** columns show where the reference was found.
4. **Locate data/script** opens Explorer with the file selected.
5. **Export shown CSV** saves the current filtered, sorted view for Excel.
   **Refresh scan** rescans after repository changes.

**Direction** is inferred from read/write calls, variable names, or literal
input/output directory names. Unclassified references need inspection.
**CandidatePath** is a filename match, not proof that the script uses that copy.
Multiple copies are shown separately. **No existing filename match** may mean
an output not generated yet, a missing input, or an external path.
Comment-only lines are hidden initially; check the box to include them.
References in docstrings, notebook text, inactive branches, or disabled blocks
may still appear as code. Computed filenames and paths assembled from variables
can be missed. This is a review aid, not a complete execution/dependency graph.

The scan includes current project scripts and data/results, including MAX and
FIRO's final/diagnostic folders. Archive, temp, Git, virtual environments, and
common dependency/cache folders are excluded. External files are not scanned.

For a scan without opening the window:

```powershell
.\shared\Script-Data-Crosswalk.ps1 -ScanOnly -ExportCsv "$env:TEMP\firo-crosswalk.csv"
```

The launcher uses Windows PowerShell in STA mode and unblocks only its own PS1.
It does not change machine execution policy. A policy imposed by your organization
may still prevent it from launching.

## Missing inputs and outputs

The **Availability** column distinguishes:

- **Input not found in scanned repo**: an inferred input with no filename match.
- **Output not found - may not be generated**: an inferred output with no filename match;
  this alone is not an error.
- **Not found - direction unknown**: inspect the source line to determine its role.
- **Found by name - verify path**: a candidate exists, but its actual use is not proven.
- **Ambiguous - multiple copies**: several candidates exist; inspect their paths.
- **Comment only - not a requirement**: a commented reference, hidden by default.

Check **Only files not found** to focus on absent candidates, or search an
Availability label to narrow further. Availability is included in CSV exports.
A match elsewhere in the repository does not prove that the expected input path
exists. Files outside the repository, or in excluded directories, are not checked.
Read/write uses of simple path variables are also considered when inferring direction.

## Combine column filters

Each visible column has a labeled filter box above the table. Leave a box blank
to leave that column unfiltered. Enter part of a value to match it, ignoring case.
All filled boxes must match the same row; they also combine with the general
search and missing-file/comment checkboxes. For example, Project = `FIRO`,
Direction = `Input`, and DataFile = `Elev` narrow the list together.

**Reset filters** clears the general search and every column filter and restores
the default checkboxes (all file statuses shown, commented references hidden).
Refresh scan keeps your filters. Export shown CSV exports only matching rows.
On smaller windows, scroll the filter area to reach additional fields.
