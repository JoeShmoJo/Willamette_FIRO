# Routing, Ramp and Evacuation Analysis

Entry point: `src/LagTimes.py`.

From the repository root, with the development Python environment activated:

```sh
python ROUTING_RAMP_EVACUATION/src/LagTimes.py
```

Paths are resolved from the script location, so invocation does not depend on your working directory. For headless execution set `MPLBACKEND=Agg`; interactive plotting can use your local default backend.

Inputs: config/LagConfig.xlsx; shared common_data/RoutingParams.xlsx, RampRates.xlsx and LocationAlias.xlsx; external shared/HourlyObservedInputs.dss and MeldedHourlyDaily_WY1982-2019.dss.

Outputs: ResvLagTimes_Median.csv, ResvEvacTimes_75thPctInflow.csv, plots and local pickle caches. Generated files are written to this project's `outputs/` and ignored by Git. Shared utility modules remain in `shared/modules/`.

Status: Full execution requires external DSS inputs, which are not tracked. Spreadsheet paths now point to their existing shared common_data locations.

This reorganization preserves existing source choices. Shared data has not yet been reconciled or certified as authoritative.
