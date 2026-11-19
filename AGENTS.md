# Working with this repository

Start with [POR workflow handoff](POR_WORKFLOW_HANDOFF.md) for the current
entry points, validation, and remaining limits.

- Give complete, paste-ready PowerShell blocks. Include `Set-Location -LiteralPath`
  for the verified Windows checkout and initialize every variable inside the block.
  Use the stated Conda interpreter by absolute path. Check native exit codes before
  continuing. Supply the command with each change that needs Windows sync or execution.
- Scope sync to the exact requested or changed files. Use a Git ref with a verified
  path list or the existing targeted installer. Preserve local edits and unrelated
  simulation data. Avoid broad pulls, downloaded patches, opaque inline payloads,
  and interactive file selection when the actual target is already known.
- Use `git --no-pager diff --stat` or a similarly bounded summary for review.
  Log and output inspection blocks must print and copy their concise result with
  `Set-Clipboard` so it is ready to paste back.
- Check the repository, ref, and file paths before publishing. Publish reviewed
  source and documentation changes only. Keep generated results, run folders,
  local configuration libraries, backups, and machine-specific environment files
  out of commits. Use a clean staging area when the checkout contains other edits.
- Keep ResSim runtime scripts compatible with Jython and the external editor and
  plotting scripts in CPython. Test the ordinary entry point and state which
  checks still require the user's Windows ResSim installation.
- Use the existing CSV-based plot layout and metrics for POR comparisons. Keep
  POR plotting independent of DSS unless the user explicitly requests DSS work.
  Match the saved output to its own compute report before interpreting differences.
