# Delayed Fall Drawdown Screening

Entry point: `src/DelayedDrawdownScreening.py`.

From the repository root, with the development Python environment activated:

```sh
python DELAYED_DRAWDOWN_SCREENING/src/DelayedDrawdownScreening.py
```

Paths are resolved from the script location, so invocation does not depend on your working directory. For headless execution set `MPLBACKEND=Agg`; interactive plotting can use your local default backend.

Inputs: Shared rule curves, drawdown targets, storage ratings and reservoir parameters; external SHARED_DATA/ressim_output/2026_10_26/ALL_D.csv.gz and FALLFIRO.csv.gz.

Outputs: DelayedFallDrawdown.pptx plus screening statistics/plots. Generated files are written to this project's `outputs/` and ignored by Git. Shared utility modules remain in root `modules/`.

Status: Full execution requires the two external ResSim datasets, which are not tracked.

This reorganization preserves existing source choices. Shared data has not yet been reconciled or certified as authoritative.
