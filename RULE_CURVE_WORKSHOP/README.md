# Rule Curve Workshop Plots

Entry point: `src/RuleCurveBlankPlots.py`.

From the repository root, with the development Python environment activated:

```sh
python RULE_CURVE_WORKSHOP/src/RuleCurveBlankPlots.py
```

Paths are resolved from the script location, so invocation does not depend on your working directory. For headless execution set `MPLBACKEND=Agg`; interactive plotting can use your local default backend.

Inputs: Shared rule curves, drawdown targets, storage ratings, reservoir parameters and LP3 residuals.

Outputs: reservoir_plots.pptx plus exploratory plots. Generated files are written to this project's `outputs/` and ignored by Git. Shared utility modules remain in `shared/modules/`.

Status: The plotting script was successfully run during reorganization.

This reorganization preserves existing source choices. Shared data has not yet been reconciled or certified as authoritative.
