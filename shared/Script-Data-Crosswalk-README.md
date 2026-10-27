# Script, input, and output crosswalk

Double-click **Start-Script-Data-Crosswalk.cmd** on Windows. The repository is
located automatically from this folder. Python 3.9 or newer is required; the
launcher finds `py -3`, `python`, or `python3`. No extra Python packages are needed.
The tool reads source code without executing analysis scripts or modifying data.

## Browse and filter

Search across all columns or fill the labeled per-column filter boxes. Blank
boxes are unfiltered; filled boxes combine and ignore case. For example,
Project = `FIRO`, Direction = `Input`, and DataFile = `Elev` narrow the view together.
Click column headings to sort. On smaller windows, scroll the filter area.
**Reset filters** clears every search and restores all file statuses.
**Refresh scan** rescans the repository while retaining filters.

Select rows (Ctrl-click for several) and choose **Open data file(s)** to compare
files in their default applications. **Open script(s)** opens Notepad; **Line**
and **Evidence** show the relevant source location. **Locate data/script** selects
the file in Explorer. **Export shown CSV** exports the current filtered, sorted view.

## Paths identify files

**DataPath** is the path resolved from the script, displayed relative to the
repository when possible. **FileID** is the normalized absolute path: different
full paths identify different files, even when filenames or contents agree.
Repeated references to the same full path share one FileID. There is no search
for alternative copies by filename and no "multiple copies" classification.

The resolver reads Python syntax to follow module path constants, `__file__`,
`Path(...).resolve().parents[...]`, `/` joins, and supported simple local paths
and output helpers. Comments and docstrings do not become file references.
Input/output roles come from recognized read/write calls; definitions without
an identified role are marked Unclassified.

**Availability** checks the resolved full path:

- **Present**: the specific file exists.
- **Missing input**: a resolved input path has no file.
- **Output not generated**: a resolved output path has no file; this alone is not an error.
- **File absent - role unclassified**: the resolved path is absent but its role needs review.
- **Path unresolved**: the tool cannot establish a path; no file is assigned.

**Only files not found** includes unresolved expressions and resolved absent files.
Search Availability for `Missing input` to isolate known missing input paths.
Exports contain the same statuses and paths. External absolute paths are checked
on the computer running the tool; no external directories are searched for matches.

## Limits of static analysis

A resolved path is the source code's static path, not proof of a runtime read or
write. Function arguments, imported settings, caller working directories,
conditional assignments, loops, dynamic filenames, or another script rebinding
module constants can change or prevent resolution. For example, FIRO's comparison
builder overrides imported modules' output directories at runtime; their own
source definitions still describe their default paths. No execution is simulated.
Unanchored relative strings remain working-directory dependent rather than being
guessed relative to the script or repository. Missing runtime-derived relationships
still require inspection of the script.

Only Python scripts currently have path resolution. **Scan notes** lists unsupported
script types or parse failures. Archive, temp, Git, virtual environments, and common
dependency/cache directories are excluded. This is not a complete execution graph.

For a scan without the Windows window:

```powershell
.\shared\Script-Data-Crosswalk.ps1 -ScanOnly -ExportCsv "$env:TEMP\firo-crosswalk.csv"
```

The launcher uses Windows PowerShell in STA mode and unblocks only its own PS1.
It does not change machine execution policy. Organization policy may still prevent
launching. The Python helper must stay beside the PS1 when moving the tool.
