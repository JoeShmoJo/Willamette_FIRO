# Willamette FIRO

Analysis projects share source data and utility modules at repository level:

```text
FIRO_COMPONANTS/                 Component allocation, curves and review packages
DELAYED_DRAWDOWN_SCREENING/       Component J screening with ResSim output
ROUTING_RAMP_EVACUATION/          Travel times, release ramps and evacuation times
RULE_CURVE_WORKSHOP/             Workshop diagrams and exploratory plots
SHARED_DATA/                    Existing source datasets, pending reconciliation
modules/                        Shared Python utilities
config/                         Legacy configuration not assigned to a workflow
```

See each project README for inputs, execution and outputs. The three newly separated workflows each use `src/`, `config/` and `outputs/`. FIRO_COMPONANTS retains its existing layout and derived model inputs in its own `data/`.

## Shared data transition

The former root `data/` folder is now `SHARED_DATA/`, with its contents and subfolders preserved. No dataset values were changed, merged or removed. In particular, `SHARED_DATA/common_data/` and the legacy files immediately inside `SHARED_DATA/` remain separate pending a source review. Their storage ratings and rule-curve representations must not be assumed equivalent.

Workflow scripts resolve paths from their own locations; shared utility modules remain in `modules/`. Generated results for the three separated workflows go into their own ignored `outputs/` folders. Existing root `out/` results are left in place as legacy outputs. `config/PostProcessConfig.xlsx` remains unassigned rather than being attributed to a workflow without evidence.

See [the structure guide](REPO_STRUCTURE.txt) and [the relocation manifest](docs/reorganization-manifest.csv) for details. The original source-folder notes are preserved in `docs/legacy_src_README.txt`.
