# FIRO Components

Build baseline FIRO-space allocations and daily component/envelope curves,
calculate a separate redistribution case, and review the resulting geometry.

## Start here

Open `outputs/review/index.html`. It links to:

- **Utilization overview:** the default reservoir/control-point daily overview.
- **Controller diagnostics:** constraint status and the component controlling each envelope.
- **Component detail:** individual component storage/offset plots with navigation.
- **Allocation and QA tables:** baseline versus redistributed allocation summaries.

The daily charts use **baseline allocations**. Redistribution is a separate
allocation calculation; the current daily curves are not rebuilt from that case.
All daily control-point loading is an unrouted storage-space screen, without
travel time, attenuation, local inflows or operational release simulation.

## Run

From the repository root, using an activated Python environment:

```sh
python -m pip install -r FIRO_COMPONENTS/requirements.txt
python FIRO_COMPONENTS/run.py model
python FIRO_COMPONENTS/run.py review
```

`all` runs both stages. Commands stop on the first failing script. Running a stage
overwrites its generated outputs. Headless machines should set `MPLBACKEND=Agg`.
Keep the complete review folders together: HTML pages use local Plotly assets.

## What is retained

| Scripts | Purpose | Outputs |
| --- | --- | --- |
| 01 | Baseline allocation | 20–27 |
| 02 | Component geometry and daily envelopes | 30–34 |
| 03 | Cap and validate curves; static diagnostic plots | 35–39 and plots/ |
| 05 | Separate redistribution optimization | 40–47 |
| 11 | Numerical capacity/status/contribution preparation | review/capacity_constraint_review/*.csv |
| 14, 13 | Default overview and controller diagnostics | review/utilization_ribbon_overview, review/constraint_controller_overview |
| 04, 07 | Component detail and navigation | plotly_component_review/ |
| 06 | Allocation/QA summary and review landing page | review/index.html and summary tables |

`00_patch_green_peter_rule_curve.py` is an explicit input-patching operation,
not a routine run step. Its anchors, audits and backups remain in `data/`.
The existing 24 data/provenance files are retained pending source reconciliation.
Some reference/staging tables are not direct model inputs. The initial canonical
input/network generation is not fully captured here; do not assume this project
can regenerate those inputs from the shared originals.

## Cleanup

Removed redundant backup scripts, the duplicate E/K trial builder and obsolete
source-editing tools. Removed earlier no-routing utilization/alternative overview
and combined-constraint visualization families. The standalone capacity pages
were removed while retaining their numerical preparation for scripts 13/14.

Core model scripts 01/02/03/05, all input data, and existing root allocation/curve
CSV outputs were preserved byte-for-byte during cleanup. Component-detail HTML
was regenerated with a shared offline Plotly asset and matching filename case.
The capacity-table preparation was checked against its original implementation:
all three resulting tables matched exactly. These checks do not independently
validate the hydrologic assumptions or certify the stored results as current.

Alternative 5 is cataloged but has no component-selection rows and no daily
outputs. F/G components remain deferred. A zero-exception output-stage QA summary
does not resolve every source-data/provisional-model warning; consult the input
quality and topology reports as well.
