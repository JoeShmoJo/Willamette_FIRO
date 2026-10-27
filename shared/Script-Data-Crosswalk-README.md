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
