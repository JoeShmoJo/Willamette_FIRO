# FIRO outputs

The progressive WAT workflow writes eight WAT CSVs and all review plots to
`diagnostics/shared_rule_curves/`. From the repository root, run:

```sh
python FIRO_COMPONENTS/compare_k_scaling.py --wat-csvs
python FIRO_COMPONENTS/compare_k_scaling.py --wat-csvs --max-offset
python FIRO_COMPONENTS/plot_lookout_point.py --review
```

Open `diagnostics/shared_rule_curves/index.html` for the Lookout Point demo and
the eight component pages. Keep the HTML files and `plotly.min.js` together.

The optional system-alternative workflow (`run.py all`) regenerates combined
storage curves under `final/` and its review and working tables under
`diagnostics/`. Its before-reallocation curves go under `final/baseline/`.
The optional fixed-allocation exporter writes under
`diagnostics/legacy_fixed_allocation/`. These outputs are generated locally.
