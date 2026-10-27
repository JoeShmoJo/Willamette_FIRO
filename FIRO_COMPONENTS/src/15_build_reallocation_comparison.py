"""Rebuild both allocation cases and put a before/after selector in each review page."""
from pathlib import Path
import argparse
import hashlib
import os
from html import escape
import importlib.util
import json

import numpy as np
import pandas as pd
import plotly.io as pio
from plotly.offline import get_plotlyjs

ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = ROOT / 'outputs' / 'diagnostics'
SCENARIOS = OUTPUTS / 'scenarios'


def load_script(filename):
    spec = importlib.util.spec_from_file_location(filename.removesuffix('.py'), ROOT / 'src' / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def prepare_case(case, physical, decision):
    directory = SCENARIOS / case
    directory.mkdir(parents=True, exist_ok=True)
    physical.to_csv(directory / '25_alternative_physical_project_allocations.csv', index=False)
    decision.to_csv(directory / '24_alternative_decision_unit_allocations.csv', index=False)
    builder = load_script('02_build_component_curves.py')
    builder.OUTPUT_DIRECTORY = directory
    builder.PHYSICAL_ALLOCATIONS_FILE = directory / '25_alternative_physical_project_allocations.csv'
    builder.main()
    capper = load_script('03_cap_validate_and_plot_curves.py')
    capper.OUTPUT_DIRECTORY = directory
    capper.COMPONENT_CURVES_FILE = directory / '31_component_daily_curves.csv'
    capper.PHYSICAL_ALLOCATIONS_FILE = builder.PHYSICAL_ALLOCATIONS_FILE
    # Keep only the interactive comparison plots; retain all numerical cap outputs.
    capper.PLOT_ALTERNATIVES = set()
    capper.main()
    status = load_script('11_build_capacity_constraint_review.py')
    status.OUTPUT_DIRECTORY = directory
    status.CAPPED_DAILY_FILE = directory / '36_project_combined_daily_curves_capped.csv'
    status.RAW_DAILY_FILE = directory / '32_project_combined_daily_curves.csv'
    status.PHYSICAL_ALLOCATION_FILE = builder.PHYSICAL_ALLOCATIONS_FILE
    status.DECISION_UNIT_ALLOCATION_FILE = directory / '24_alternative_decision_unit_allocations.csv'
    status.CONTROL_POINT_RELATIONSHIP_FILE = OUTPUTS / '21_static_control_point_relationships.csv'
    status.REVIEW_DIRECTORY = directory / 'capacity_status'
    status.main()
    for name in ['27_static_allocation_quality_report.csv', '34_component_curve_quality_report.csv']:
        path = (OUTPUTS if name.startswith('27') else directory) / name
        quality = pd.read_csv(path)
        if not quality.empty and quality.severity.astype(str).str.upper().eq('ERROR').any():
            raise ValueError(f'Model errors in {path}; refusing to publish comparison plots')
    components = pd.read_csv(directory / '35_component_daily_curves_capped.csv')
    reservoirs = pd.read_csv(status.REVIEW_DIRECTORY / '01_reservoir_daily_capacity_status.csv')
    controls = pd.read_csv(status.REVIEW_DIRECTORY / '02_control_point_daily_capacity_status.csv')
    for table in [components, reservoirs, controls]:
        table['date'] = pd.to_datetime(table['date'])
    return components, reservoirs, controls


def write_comparison(before, after, path, budgets):
    """A single chart is redrawn from the selected case, including its limits/ribbons."""
    path.parent.mkdir(parents=True, exist_ok=True)
    asset = path.parent / 'plotly.min.js'
    if not asset.exists():
        asset.write_text(get_plotlyjs(), encoding='utf-8')
    # Fix axes to the union of the two computed numeric ranges where both are explicit.
    for key in before.layout:
        if key.startswith('yaxis'):
            a, b = before.layout[key].range, after.layout[key].range
            if a is not None and b is not None:
                lo, hi = min(a[0], b[0]), max(a[1], b[1])
                before.layout[key].range = after.layout[key].range = [lo, hi]
    for figure in [before, after]:
        figure.update_layout(uirevision='allocation-comparison')
    figures = '{"before":' + pio.to_json(before) + ',"after":' + pio.to_json(after) + '}'
    figures = figures.replace('<', '\\u003c')
    before_budget, after_budget = budgets
    note = (f'Allocation: {before_budget:.3f} KAF before; {after_budget:.3f} KAF after '
            f'(change {after_budget-before_budget:+.3f} KAF).')
    path.write_text('''<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>FIRO allocation comparison</title><script src="plotly.min.js"></script>
<style>body{font-family:Arial,sans-serif;margin:18px}.controls{padding:12px;background:#eef3f7}
select{font-size:16px;padding:6px}#chart{width:100%}.note{max-width:1100px}</style></head><body>
<div class="controls"><label for="allocation-case">Allocation case: </label>
<select id="allocation-case"><option value="before">Before reallocation</option>
<option value="after" selected>After reallocation</option></select>
<p>''' + escape(note) + '''</p></div>
<p class="note">Curves are recalculated separately for each case using the same component rules.
Limits, dates, envelope controllers and utilization ribbons follow the selected case.
This is an unrouted storage-space screen, not a release simulation.</p>
<div id="chart"></div><script id="firo-scenarios" type="application/json">''' + figures + '''</script>
<script>
const cases=JSON.parse(document.getElementById('firo-scenarios').textContent);
const chooser=document.getElementById('allocation-case');
try{const saved=localStorage.getItem('firo-allocation-case');if(cases[saved])chooser.value=saved;}catch(e){}
function draw(){const key=chooser.value, figure=cases[key];
  Plotly.react('chart',figure.data,figure.layout,{responsive:true});
  try{localStorage.setItem('firo-allocation-case',key);}catch(e){}
}
chooser.addEventListener('change',draw);draw();
</script></body></html>''', encoding='utf-8')


def export_final_curves():
    """Publish capped project envelopes, with explicit allocation-case provenance."""
    final = ROOT / 'outputs' / 'final'
    for case, directory in [('after', final), ('before', final / 'baseline')]:
        source = SCENARIOS / case / '36_project_combined_daily_curves_capped.csv'
        curves = pd.read_csv(source)
        if curves.duplicated(['alternative_id', 'project_id', 'date']).any():
            raise ValueError(f'Duplicate final curve rows in {source}')
        directory.mkdir(parents=True, exist_ok=True)
        for aid, table in curves.groupby('alternative_id', sort=True):
            table = table.sort_values(['project_id', 'date']).copy()
            table.insert(0, 'allocation_case', case)
            table.to_csv(directory / f'alternative_{int(aid):02d}_combined_curves.csv', index=False)
    (final / 'README.md').write_text('''# Final combined FIRO curves

Use `alternative_XX_combined_curves.csv` in this folder for the **after-reallocation** result.
Each file contains all modeled reservoirs for one alternative, one row per reservoir per day.
`baseline/` holds the corresponding **before-reallocation** curves for comparison.
Alternative 5 has no selected components and therefore has no curve file.

These are the final capped combined envelopes, not the individual component curves.
- `combined_storage_kaf`: total storage coordinate of the combined envelope.
- `combined_offset_kaf`: FIRO-space offset from the rule-curve storage; use this for FIRO space.
- `rule_storage_kaf`: reference rule-curve storage.
- `rule_elevation_ft`: reference rule-curve elevation, in feet.
- `allocated_project_firo_space_kaf`: allocation limit used for that reservoir and alternative.
- `controlling_component`: component controlling the envelope on that date.
- `allocation_case`: `after` or `before`; IDs and names identify the alternative and reservoir.

KAF means thousand acre-feet. Dates cover the existing August 2018–July 2019 model year;
these are planning curves, not historical observations or a routed operating simulation.
Do not treat `combined_storage_kaf` as FIRO space or infer elevation from storage without a rating table.

Rebuild with `python FIRO_COMPONENTS/run.py model` (or `all`). Source inputs, physical assumptions,
and supplied control-point limits retain the limitations documented in the project README.
Supporting numerical tables, QA reports, plots, and scenario provenance live in `../diagnostics/`.
''', encoding='utf-8')


def main(curves_only=False):
    physical = pd.read_csv(OUTPUTS / '25_alternative_physical_project_allocations.csv')
    decision = pd.read_csv(OUTPUTS / '24_alternative_decision_unit_allocations.csv')
    reallocated = pd.read_csv(OUTPUTS / '43_redistributed_physical_project_allocations.csv')
    redistributed_units = pd.read_csv(OUTPUTS / '41_redistributed_decision_unit_allocations.csv')
    keys = ['alternative_id', 'project_id']
    changes = physical[keys + ['project_firo_space_kaf']].merge(
        reallocated[keys + ['redistributed_project_firo_space_kaf']], on=keys,
        how='outer', validate='one_to_one', indicator=True)
    if not changes['_merge'].eq('both').all():
        raise ValueError('Baseline and redistributed project membership differ')
    if changes[['project_firo_space_kaf','redistributed_project_firo_space_kaf']].isna().any().any():
        raise ValueError('Allocation values are missing')
    baseline_check = physical[keys + ['project_firo_space_kaf']].merge(
        reallocated[keys + ['baseline_project_firo_space_kaf']], on=keys, validate='one_to_one')
    if not np.allclose(baseline_check.project_firo_space_kaf,
                       baseline_check.baseline_project_firo_space_kaf, atol=1e-6, rtol=0):
        raise ValueError('Redistribution is stale; rerun the model stage first')
    if (changes.redistributed_project_firo_space_kaf < changes.project_firo_space_kaf - 1e-6).any():
        raise ValueError('Redistribution reduced a baseline allocation')
    after_physical = physical.merge(reallocated[keys + ['redistributed_project_firo_space_kaf',
                                                        'redistributed_firo_space_kaf']],
                                    on=keys, validate='one_to_one')
    after_physical['project_firo_space_kaf'] = after_physical.pop('redistributed_project_firo_space_kaf')
    after_physical['decision_unit_final_firo_space_kaf'] = after_physical.pop('redistributed_firo_space_kaf')
    if (after_physical.project_firo_space_kaf > after_physical.project_physical_cap_kaf + 1e-6).any():
        raise ValueError('Reallocated physical project exceeds its cap')
    unit_keys = ['alternative_id', 'decision_unit_id']
    unit_check = decision[unit_keys + ['final_firo_space_kaf']].merge(
        redistributed_units[unit_keys + ['baseline_firo_space_kaf']],
        on=unit_keys, how='outer', validate='one_to_one', indicator=True)
    if not unit_check['_merge'].eq('both').all() or not np.allclose(
            unit_check.final_firo_space_kaf, unit_check.baseline_firo_space_kaf, atol=1e-6, rtol=0):
        raise ValueError('Redistributed allocation-unit results do not match the current baseline')
    after_decision = decision.merge(redistributed_units[unit_keys + ['redistributed_firo_space_kaf',
                                              'redistributed_limiting_control_points']],
                                    on=unit_keys, validate='one_to_one')
    after_decision['final_firo_space_kaf'] = after_decision.pop('redistributed_firo_space_kaf')
    after_decision['limiting_control_points'] = after_decision.pop('redistributed_limiting_control_points')
    after_decision['limiting_factor'] = 'OPTIMIZED_STATIC_ALLOCATION'
    after_physical = after_physical.drop(columns=['decision_unit_limiting_control_points']).merge(
        after_decision[unit_keys + ['limiting_control_points']], on=unit_keys, validate='many_to_one')
    after_physical = after_physical.rename(columns={'limiting_control_points':'decision_unit_limiting_control_points'})
    after_physical['decision_unit_limiting_factor'] = 'OPTIMIZED_STATIC_ALLOCATION'
    cases = {'before': prepare_case('before', physical, decision),
             'after': prepare_case('after', after_physical, after_decision)}
    export_final_curves()
    if curves_only:
        return
    before_components, before_reservoirs, before_controls = cases['before']
    after_components, after_reservoirs, after_controls = cases['after']
    renderers = [load_script('14_build_utilization_ribbon_overview.py'),
                 load_script('13_build_constraint_controller_overview.py')]
    entries = [[], []]
    for alternative_id, reservoirs in before_reservoirs.groupby('alternative_id', sort=True):
        name = str(reservoirs.alternative_name.iloc[0])
        other = after_reservoirs.loc[after_reservoirs.alternative_id == alternative_id]
        cp_before = before_controls.loc[before_controls.alternative_id == alternative_id]
        cp_after = after_controls.loc[after_controls.alternative_id == alternative_id]
        budgets = (physical.loc[physical.alternative_id == alternative_id, 'project_firo_space_kaf'].sum(),
                   after_physical.loc[after_physical.alternative_id == alternative_id, 'project_firo_space_kaf'].sum())
        for i, renderer in enumerate(renderers):
            filename = f'alternative_{int(alternative_id):02d}_' + ('utilization_ribbon_overview.html' if i == 0 else 'constraint_controller_overview.html')
            write_comparison(renderer.build_overview(int(alternative_id), name, reservoirs, cp_before),
                             renderer.build_overview(int(alternative_id), name, other, cp_after),
                             renderer.OUTPUT_DIRECTORY / filename, budgets)
            entries[i].append(dict(alternative_id=int(alternative_id), alternative_name=name, filename=filename))
    for renderer, entry in zip(renderers, entries):
        renderer.write_index(entry)
    detail = load_script('04_build_plotly_component_review.py')
    detail_entries = []
    for (aid, pid, name), data in before_components.groupby(['alternative_id','project_id','project_name'], sort=True):
        other = after_components.loc[(after_components.alternative_id == aid) & (after_components.project_id == pid)]
        row = changes.loc[(changes.alternative_id == aid) & (changes.project_id == pid)].iloc[0]
        filename = f'alternative_{int(aid):02d}_{pid}_component_review.html'
        write_comparison(detail.build_review_figure(data, int(aid), name),
                         detail.build_review_figure(other, int(aid), name),
                         detail.REVIEW_DIRECTORY / filename,
                         (row.project_firo_space_kaf, row.redistributed_project_firo_space_kaf))
        detail_entries.append((filename, f'Alternative {int(aid)} - {name}', int(aid), str(name)))
    detail.write_index(detail_entries)
    load_script('07_add_plotly_review_navigation.py').main()
    sources = [*ROOT.joinpath('data').glob('*.csv'),
               ROOT.parent / 'shared/common_data/ElevStor.csv',
               ROOT.parent / 'shared/control_points_space.csv',
               *[OUTPUTS / n for n in ['24_alternative_decision_unit_allocations.csv',
                  '25_alternative_physical_project_allocations.csv','41_redistributed_decision_unit_allocations.csv',
                  '43_redistributed_physical_project_allocations.csv']],
               *[ROOT / 'src' / n for n in ['02_build_component_curves.py',
                    '03_cap_validate_and_plot_curves.py','11_build_capacity_constraint_review.py',
                    '04_build_plotly_component_review.py','13_build_constraint_controller_overview.py',
                    '14_build_utilization_ribbon_overview.py','15_build_reallocation_comparison.py']]]
    manifest = {'cases':['before','after'], 'inputs_and_calculations':
                {os.path.relpath(p, ROOT):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
                'overview_pages':sum(map(len,entries)), 'component_pages':len(detail_entries)}
    (SCENARIOS / 'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(f'Built {manifest["overview_pages"]} comparison overviews and {len(detail_entries)} component pages.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--curves-only', action='store_true', help='Publish final curves without rendering plots')
    main(curves_only=parser.parse_args().curves_only)
