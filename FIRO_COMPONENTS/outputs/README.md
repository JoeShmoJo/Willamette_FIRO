# FIRO outputs

- **[final/](final/README.md)** — final combined curves, one CSV per alternative. Main files are after reallocation; baseline/ contains before reallocation.
- **[diagnostics/review/index.html](diagnostics/review/index.html)** — interactive review landing page. Individual component pages remain in diagnostics/plotly_component_review/.
- **diagnostics/scenarios/** — consolidated allocation/rebuild inputs and before/after plot-support data. These feed the review.
- **diagnostics/extra/** — optional intermediate tables, extra QA and static plots; generated only when requested.

Run `python FIRO_COMPONENTS/run.py all` for final curves and the complete review without extra exports. Add `--diagnostics` to retain extras. Use `model` for numerical/final results or `review` to rebuild plots from saved inputs. A later default run removes the generated extra folder.
