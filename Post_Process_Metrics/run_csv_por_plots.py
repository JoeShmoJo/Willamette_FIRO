"""Render two POR plot pages from the selected CSV exports and configuration."""
import argparse
from datetime import datetime
from html import escape
import io
import json
import ntpath
import re
from pathlib import Path

import numpy as np
import pandas as pd

import annual_overlays as overlays
from purpose_plots import location_plot

ROOT = Path(__file__).resolve().parent
BANKFULL_METRIC = 'Days above bankfull flow'


BIOP = 'ESA flow compliance / BiOp component'
COMBINED = 'ESA flow compliance / BiOp plus withdrawals'
FLOW_COMPLIANCE = {
    BIOP: ('BiOp minimum-flow component',
           'Daily outflow screened against the fixed BiOp minimum-flow schedule.'),
    COMBINED: ('Combined minimum flow',
               'Daily outflow screened against each compute’s captured minimum-flow plus withdrawal schedules. '
               'Missing captured schedules leave that trial unavailable. This screen does not reproduce '
               'native timestep rule adjustments or verify that the rule was active.'),
}
HOLIDAYS = ('Memorial Day', 'Labor Day')


def bankfull_thresholds(model, thresholds, target_directory):
    captured = model.get('bankfull_cfs') or {}
    options = {}
    for operation in model.get('operations', []):
        definitions = operation.get('rule_inventory', {}).get('definitions', {})
        for rule in definitions.values():
            name = rule.get('name') or ''
            release = rule.get('release_definition') or {}
            units = release.get('units') or release.get('y_units') or ''
            if units.casefold() != 'cfs':
                continue
            kind = release.get('kind')
            if kind == 'constant':
                values = [release.get('value')]
            elif kind == 'seasonal_record':
                values = release.get('values', [])
            elif kind == 'paired_values':
                values = [value for point in release.get('points', []) for value in point.get('y', [])]
            else:
                continue
            if not values or not all(isinstance(value, (int, float)) and np.isfinite(value) and value > 0
                                     for value in values) or len(set(values)) != 1:
                continue
            for site in thresholds.location:
                if re.search(rf'\b{re.escape(site)}\s+bank\s*full(?:\s+max)?$', name, re.I):
                    options.setdefault(site, set()).add(values[0])
    script = ''
    if target_directory is not None:
        path = target_directory.parent/'Plots_Jython/Willamett_FRM plots_ McKenzieAndBelowAndFlows.py'
        if path.is_file():
            script = path.read_text(encoding='utf-8-sig', errors='replace')
    identifiers = {'Harrisburg': 'HARO', 'Jefferson': 'JFFO', 'Salem': 'SALO', 'Albany': 'ALBO'}
    result = {}
    for station in thresholds.itertuples(index=False):
        site = station.location
        value = captured.get(site)
        if isinstance(value, (int, float)) and np.isfinite(value) and value > 0:
            result[site] = (value, 'compute JSON bankfull_cfs')
            continue
        candidates = options.get(site, set())
        if len(candidates) == 1:
            value = next(iter(candidates))
            if np.isfinite(value) and value > 0:
                result[site] = (value, 'compute JSON bankfull rule')
                continue
        identifier = identifiers.get(site)
        match = re.search(rf'^\s*{identifier}BF\.value\s*=\s*["\'](\d+(?:\.\d+)?)["\']', script, re.M) if identifier else None
        if match:
            result[site] = (float(match[1]), 'watershed FRM plotting script')
        else:
            result[site] = (station.action_cfs, 'report action/bankfull CSV')
    return result


def conservation_storage_ratings(model, rule_curve):
    if rule_curve is None:
        return {}
    values = {}
    for operation in model.get('operations', []):
        name = operation['reservoir']
        key = name.casefold()
        if key not in rule_curve or rule_curve[key].dropna().empty:
            continue
        rating = operation.get('rating_tables', {}).get('elevation_storage') or {}
        if rating.get('columns') != ['elevation_ft', 'storage_acre_ft']:
            continue
        rows = np.asarray(rating.get('rows', []), dtype=float)
        if rows.ndim != 2 or rows.shape[1] != 2 or len(rows) < 2 or not np.isfinite(rows).all():
            continue
        elevations, storage = rows.T
        minimum = rule_curve[key].min()
        if (np.diff(elevations) <= 0).any() or (np.diff(storage) < 0).any() or not elevations[0] <= minimum <= elevations[-1]:
            continue
        values[name] = (elevations, storage, np.interp(minimum, elevations, storage))
    return values


def metric_window(purpose, metric, year):
    if metric.endswith(HOLIDAYS[0]):
        return pd.date_range(end=f'{year}-05-31', periods=1, freq='W-MON')
    if metric.endswith(HOLIDAYS[1]):
        return pd.date_range(start=f'{year}-09-01', periods=1, freq='W-MON')
    if purpose == 'Flood Control':
        return pd.date_range(f'{year-1}-10-01', f'{year}-09-30')
    return pd.date_range(f'{year}-01-01', f'{year}-12-31')


def captured_combined_schedule(config):
    paths = config.get('resolved', {}).get('table_paths', {})
    tables = config.get('tables', {})
    texts = [tables.get(paths.get(name)) for name in ('minFlowConfigCSV', 'withdrawalConfigCSV')]
    if not all(texts):
        return None
    calendar = pd.date_range('2001-01-01', '2001-12-31')
    expected = set(zip(calendar.month, calendar.day))
    schedules = []
    for text in texts:
        table = pd.read_csv(io.StringIO(text.lstrip('\ufeff')), comment='#').set_index(['Month', 'Day'])
        if not table.index.is_unique or set(table.index) != expected:
            return None
        schedules.append(table.select_dtypes(include='number'))
    return schedules[0].add(schedules[1], fill_value=0)


def compliance_series(schedule, daily, dates):
    targets = schedule.reindex([
        (day.month, 28 if (day.month, day.day) == (2, 29) else day.day) for day in dates
    ]).set_axis(dates)
    for reservoir, target in targets.items():
        outlet = 'Foster' if reservoir == 'Green Peter' else reservoir
        column = f'{outlet}__Flow-OUT'
        if column not in daily and not target.gt(0).any():
            continue
        flow = daily[column].reindex(dates)
        yield reservoir, (target.gt(0) & flow.lt(target - target.mul(.02).clip(lower=5))
                          ).astype(float).where(flow.notna() | ~target.gt(0))


def metric_groups(summary):
    groups = dict(tuple(summary.groupby(['purpose', 'metric', 'period'])))
    if summary.purpose.isin(FLOW_COMPLIANCE).any():
        for purpose in FLOW_COMPLIANCE:
            groups.setdefault((purpose, 'Days below minimum-flow target', 'calendar year'),
                              summary.iloc[:0])
    return sorted(groups.items())


def metric_heading(purpose, metric, period):
    if purpose in FLOW_COMPLIANCE:
        name, explanation = FLOW_COMPLIANCE[purpose]
        title = f'{name} ({period})'
        context = f'{metric} · {period.capitalize()}'
        details = (f'<p>{explanation} Counts use a tolerance of the greater of 5 cfs or 2% of target. '
                   'The Green Peter target is evaluated at Foster. System counts count a day once.</p>')
    else:
        name = metric
        title = f'{purpose} / {metric} ({period})'
        context = f'{purpose} · {period.capitalize()}'
        details = ''
    heading = (f'<h2 style="font-size:1.8rem;margin-bottom:.25em">{escape(name)}</h2>'
               f'<p style="margin-top:0">{escape(context)}</p>{details}')
    return escape(title), heading


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('prior', type=Path, help='Existing CSV comparison folder')
    parser.add_argument('output', type=Path)
    parser.add_argument('--target-directory', type=Path, help='Watershed scripts/externalSVs folder')
    parser.add_argument('--settings-only', action='store_true', help='Refresh Model Settings in an existing output folder')
    parser.add_argument('--baseline-fits', type=Path, help='Explicit saved Baseline input mapping file')
    parser.add_argument('--alternative-fits', type=Path, help='Explicit saved Alternative input mapping file')
    args = parser.parse_args()
    fits_files = {'Baseline': args.baseline_fits, 'Alternative': args.alternative_fits}
    if args.settings_only:
        source = json.loads((args.output/'csv_provenance.json').read_text(encoding='utf-8-sig'))
        models = {label: read_compute_report(source[label.lower()], label, fits_files[label])
                  for label in ('Baseline', 'Alternative')}
        page = args.output/'model_settings.html'
        pending = page.with_suffix('.tmp')
        write_model_settings(pending, models)
        pending.replace(page)
        print(page)
        for label, model in models.items():
            compute = model['compute']
            baseline = compute.get('baseline_configuration') or {}
            pointer = baseline.get('pointer') or {}
            name = (baseline.get('resolved') or {}).get('name') or pointer.get('name')
            mapping = model['saved_input_mappings']
            print(f'{label} | {compute["output_fpart"]} | captured configuration: {name or "None recorded"} '
                  f'| snapshot: {pointer.get("id") or "-"} | {mapping["status"]}')
    else:
        build(args.prior, args.output, args.target_directory, fits_files)


def read_compute_report(case, label, fits_file=None):
    model = json.loads(Path(case['report']).read_text(encoding='utf-8-sig'))
    compute = model['compute']
    if (compute['compute_id'], compute['output_fpart']) != (case['compute_id'], case['f_part']):
        raise ValueError(f'{label}: report identity differs from CSV provenance')
    model['saved_input_mappings'] = read_saved_mappings(case, fits_file)
    return model


def linked_input_mapping(run, fpart):
    """Follow the saved RssRun alternative to its declared input mapping."""
    run_file = run/'rss'/f'{fpart}.rssrun'
    if not run_file.is_file():
        return None

    def resolve_saved_path(value):
        path = Path(value.strip().replace('\\', '/'))
        return run/path

    match = re.search(r'^\s*FLD=_altPath[ \t]*\r?\n[ \t]*STR=([^\r\n]+)',
                      run_file.read_text(encoding='utf-8-sig', errors='replace'), re.MULTILINE)
    if not match:
        return None
    alternative = resolve_saved_path(match[1])
    if not alternative.is_file():
        return None
    match = re.search(r'^InputTSData Path=([^\r\n]+)',
                      alternative.read_text(encoding='utf-8-sig', errors='replace'), re.MULTILINE)
    if match:
        return resolve_saved_path(match[1])
    return None


def read_saved_mappings(case, explicit=None):
    basis = 'explicit selection'
    if explicit is None:
        run = Path(case['report']).parent.parent
        linked = linked_input_mapping(run, case['f_part'])
        if linked is not None:
            if not linked.is_file():
                return {'source': str(linked), 'status': 'Linked input mapping file is missing'}
            explicit = linked
            basis = 'linked by saved run and alternative'
    if explicit is None:
        folder = run/'rss'
        prefix = case['f_part'] + '_'
        candidates = [path for path in folder.glob(prefix + '*.fits')
                      if path.name.startswith(prefix) and not path.stem.casefold().endswith('obs')]
        # WAT copies are a different input selection. Prefer the regular trial file.
        regular = [path for path in candidates if not path.stem.casefold().endswith('wat-default')]
        candidates = regular or candidates
        if len(candidates) != 1:
            return {'source': None, 'status': 'Could not resolve a saved mapping file for this trial' if not candidates
                    else 'Multiple trial mapping files. Select one explicitly.'}
        explicit = candidates[0]
        basis = 'matched trial filename'
    records = {}
    row = None
    lines = explicit.read_bytes()
    try:
        text = lines.decode('utf-8-sig')
    except UnicodeDecodeError:
        text = lines.decode('cp1252')
    for line in text.splitlines():
        key, sep, value = line.partition('=')
        if not sep:
            continue
        if key == 'TSRecord':
            if row is not None:
                raise ValueError(f'{explicit}: unterminated TSRecord')
            row = {}
        elif row is not None and key == 'TSRecord End':
            name, variable = row.pop('Name', ''), row.pop('VariableId', '')
            identity = f'{name} (variable {variable})'
            if not name or identity in records:
                raise ValueError(f'{explicit}: missing or duplicate input mapping: {identity}')
            if 'DssFilename' in row and row['DssFilename']:
                row['DssFilename'] = ntpath.normcase(ntpath.normpath(row['DssFilename']))
            if 'DssPathname' in row:
                row['DssPathname'] = row['DssPathname'].upper()
            records[identity] = row
            row = None
        elif row is not None and key.startswith('TSRecord '):
            row[key.removeprefix('TSRecord ')] = value.strip()
    if row is not None or not records:
        raise ValueError(f'{explicit}: expected a complete ResSim input time-series dataset')
    return {'source': str(explicit), 'status': f'{len(records)} saved mappings ({basis})', 'records': records}


def write_target_pages(output, directory, routed, years):
    links = []
    labels = ('Baseline', 'Alternative')
    for regime, regime_name in (('2008BiOp', '2008 BiOp'), ('HD531', 'House Document 531')):
        panels = []
        for site in ('Salem', 'Albany'):
            path = directory/f'MinFlow{site}_{regime}.csv'
            schedule = pd.read_csv(path, comment='#', encoding='utf-8-sig')
            breakpoints = pd.to_datetime([column+'2000' for column in schedule.columns[1:]],
                                         format='%d%b%Y').dayofyear.to_numpy()
            for _, group in schedule.groupby(list(schedule.columns[1:]), sort=False):
                values = group.iloc[0, 1:].to_numpy(dtype=float)
                classification = ', '.join(f'{value:g}' for value in group['WY_type'])
                rows = []
                for year in years:
                    dates = metric_window(BIOP, '', year)
                    calendar = np.array([pd.Timestamp(2000, day.month, day.day).dayofyear for day in dates])
                    target = pd.Series(values[np.searchsorted(breakpoints, calendar, side='right')-1], index=dates)
                    eligible = target[target.gt(0)]
                    flows = [routed[label][f'{site}__Flow'].reindex(eligible.index) for label in labels]
                    complete = len(eligible) > 0 and all(flow.notna().all() for flow in flows)
                    b, a = [int(flow.lt(eligible).sum()) if complete else np.nan for flow in flows]
                    rows.append(dict(purpose='ESA flow compliance', location=site, year=year, units='days',
                                     baseline=b, alternative=a))
                table = pd.DataFrame(rows)
                panels.append(f'<h2>{site} | Water-year-type table rows {escape(classification)}</h2>')
                for kind in ('box', 'duration'):
                    fig = location_plot(table, labels, kind, percentile_boxes=True)
                    peak = table[['baseline', 'alternative']].max().max()
                    fig.update_yaxes(range=[0, max(1, 1.05*peak)] if pd.notna(peak) else [0, 1],
                                     dtick=1 if pd.isna(peak) or peak <= 10 else None)
                    panels.append(fig.to_html(full_html=False, include_plotlyjs=len(panels) == 1))
        filename = f'mainstem_{regime.lower()}.html'
        (output/filename).write_text(
            f'<!doctype html><meta charset="utf-8"><title>{regime_name}</title>'
            f'<h1>Salem and Albany | {regime_name}</h1><a href="index.html">POR plots</a>'
            '<p>Days with routed flow strictly below a positive configured target. Each distinct schedule '
            'is applied to both cases across each calendar year. These are fixed-schedule comparisons.</p>'
            + ''.join(panels), encoding='utf-8')
        links.append(f'<a href="{filename}">{regime_name}</a>')
    return '<p>Salem and Albany target comparisons | ' + ' | '.join(links) + '</p>'


def model_settings(model, include_mappings=True):
    compute = model['compute']
    baseline = compute.get('baseline_configuration') or {}
    resolved = baseline.get('resolved') or {}
    effective = compute.get('effective_alternative_configuration')
    snapshot = (baseline.get('pointer') or {}).get('directory')
    checksums = resolved.get('table_sha256') or {}
    if isinstance(effective, dict) and snapshot:
        effective = effective.copy()
        for key, relative in (resolved.get('table_paths') or {}).items():
            value = effective.get(key)
            if not isinstance(value, str) or not checksums.get(relative):
                continue
            suffix = (snapshot.rstrip('/\\') + '/' + relative).replace('\\', '/').casefold()
            path = value.replace('\\', '/').casefold()
            if path == suffix or path.endswith('/' + suffix):
                # The checksum below captures content changes across snapshots.
                effective[key] = 'Captured baseline table: ' + relative.replace('\\', '/')
    report = {
        'Effective alternative settings': effective,
        'Baseline application status': baseline.get('status'),
        'Baseline rule settings': resolved.get('rules'),
        'Baseline augmentation': resolved.get('baseline_augmentation'),
        'Baseline table checksums': resolved.get('table_sha256'),
        'Reservoir operation sets': {
            op['reservoir']: {
                'operation_set': op.get('operation_set'),
                'zone_order': [zone['zone_name'] for zone in op.get('zones', [])],
                'zone_rules': {zone['zone_name']: zone['rules'] for zone in op.get('zones', [])},
                'rating_tables': op.get('rating_tables'),
                'evacuation_limits': {zone['zone_name']: zone['evacuation_limits']
                                      for zone in op.get('zones', []) if 'evacuation_limits' in zone},
            } for op in model.get('operations', [])
        },
    }
    if include_mappings and 'records' in model.get('saved_input_mappings', {}):
        report['Alternative input time-series mappings'] = model['saved_input_mappings']['records']
    flattened = {}

    def visit(path, value):
        if isinstance(value, dict) and value:
            for key, item in value.items():
                visit(path + (key,), item)
        else:
            flattened[path] = value

    visit((), report)
    return flattened


def write_model_settings(path, models):
    missing = object()

    def cell(value):
        if value is missing:
            return 'Absent'
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
        if len(text) > 120:
            return f'<details><summary>Show value</summary><pre>{escape(text)}</pre></details>'
        return escape(text)

    sections, navigation = [], []
    for label, model in models.items():
        if label == 'Baseline':
            continue
        have_mappings = all('records' in case.get('saved_input_mappings', {})
                            for case in (models['Baseline'], model))
        baseline = model_settings(models['Baseline'], have_mappings)
        trial = model_settings(model, have_mappings)
        changed, matching = [], []
        standalone_pair = label == 'Alternative' and len(models) == 2
        for key in sorted(baseline.keys() | trial.keys()):
            base, alt = baseline.get(key, missing), trial.get(key, missing)
            name = escape(' / '.join(key))
            if base != alt:
                changed.append(f'<tr><th scope="row">{name}</th><td>{cell(base)}</td><td>{cell(alt)}</td></tr>')
            elif standalone_pair:
                matching.append(f'<tr><th scope="row">{name}</th><td>{cell(base)}</td></tr>')
        title = escape(label)
        anchor = escape(label.lower().replace(' ', '-'), quote=True)
        navigation.append(f'<li><a href="#{anchor}">{title} versus Baseline</a></li>')
        differences = (
            f'<table><thead><tr><th>Setting</th><th>Baseline</th><th>{title}</th></tr></thead><tbody>'
            + ''.join(changed) + '</tbody></table>' if changed else
            '<p>No differences in the captured settings shown.</p>')
        shared = (f'<details><summary>{len(matching)} matching settings</summary><table><thead>'
                  '<tr><th>Setting</th><th>Shared value</th></tr></thead><tbody>'
                  + ''.join(matching) + '</tbody></table></details>') if standalone_pair else ''
        mapping_note = ('' if have_mappings else
                        '<p>Input mapping comparison is unavailable without both saved files.</p>')
        sections.append(f'<section id="{anchor}"><h2>{title} versus Baseline</h2>'
                        f'<p>{len(changed)} changed settings</p>{mapping_note}{differences}{shared}</section>')

    identities = []
    for label, model in models.items():
        compute = model['compute']
        baseline = compute.get('baseline_configuration') or {}
        pointer = baseline.get('pointer') or {}
        configuration_name = ((baseline.get('resolved') or {}).get('name') or pointer.get('name')
                              or ('Name unavailable' if pointer.get('id') else 'None recorded'))
        identities.append(f'<li><strong>{escape(label)}</strong> | Applied configuration '
                          f'<strong>{escape(configuration_name)}</strong>'
                          '<details><summary>Run details</summary>'
                          f'F-part {cell(compute.get("output_fpart"))} | compute {cell(compute.get("compute_id"))} | '
                          f'snapshot ID {cell(pointer.get("id"))}</details></li>')
    mapping_sources = []
    for label, model in models.items():
        mapping = model.get('saved_input_mappings', {})
        source = mapping.get('source')
        mapping_sources.append(f'<li>{escape(label)} | {escape(mapping.get("status", "Unavailable"))}'
                               + (f' | {escape(source)}' if source else '') + '</li>')
    path.write_text(
        '<!doctype html><meta charset="utf-8"><title>Model settings</title>'
        '<style>body{font:16px system-ui;margin:2rem}table{border-collapse:collapse}'
        'td,th{border:1px solid #cbd5e1;text-align:left;padding:.35rem;vertical-align:top}'
        'pre{white-space:pre-wrap;overflow-wrap:anywhere}</style>'
        '<h1>Model settings</h1><p><a href="index.html">All POR plots</a></p>'
        '<ul>' + ''.join(identities) + '</ul>'
        '<p>Configuration names and settings come from each selected compute report. '
        'Different snapshot IDs can have identical settings. '
        'Snapshot folder IDs are ignored for matched captured tables. Uncaptured external inputs and '
        'runtime rule behavior are outside this comparison.</p>'
        '<details><summary>Input mapping sources</summary>'
        '<p>Reads the currently saved ResSim trial mapping files. They may have been edited since compute. '
        'This compares the mapping references and does not open any referenced DSS data files.</p><ul>'
        + ''.join(mapping_sources) + '</ul></details>'
        + '<nav aria-label="Trial comparisons"><ul>' + ''.join(navigation) + '</ul></nav>'
        + ''.join(sections), encoding='utf-8')


def metric_panels(summary, labels, bankfull=None):
    options, panels = [], []
    plotly_included = False
    for n, ((purpose, metric, period), table) in enumerate(metric_groups(summary)):
        title, heading = metric_heading(purpose, metric, period)
        options.append(f'<option value="{n}">{title}</option>')
        start = f'<section id="metric-{n}"{" hidden" if n else ""}>{heading}'
        if table.empty:
            panels.append(start + '<p>No comparison data are available.</p></section>')
            continue
        limits = bankfull if metric == 'Peak daily routed flow' else None
        figures = [location_plot(table, labels, kind, percentile_boxes=True, bankfull=limits)
                   for kind in ('box', 'duration')]
        # Set an explicit range even for all-zero traces.
        if purpose == 'Flood Control' and table.units.isin(['days', 'reservoir-days']).all():
            locations = sorted(table.location.unique(), key=lambda location: (location == 'SYSTEM', location))
            columns = min(3, len(locations))
            for i, location in enumerate(locations):
                peak = table.loc[table.location.eq(location), ['baseline', 'alternative']].max().max()
                for fig in figures:
                    fig.update_yaxes(range=[0, max(1, 1.05*peak)] if pd.notna(peak) else [0, 1],
                                     dtick=1 if pd.isna(peak) or peak <= 10 else None,
                                     row=i//columns+1, col=i%columns+1)
        body = ''.join(fig.to_html(full_html=False, include_plotlyjs=(not plotly_included and i == 0))
                       for i, fig in enumerate(figures))
        panels.append(start + body + '</section>')
        plotly_included = True
    return (
        '<label for="pick">Metric</label> <select id="pick">' + ''.join(options) + '</select>'
        + ''.join(panels)
        + '<script>document.querySelector("#pick").onchange=e=>{document.querySelectorAll("section").forEach(s=>'
          's.hidden=s.id!=="metric-"+e.target.value);document.querySelectorAll("section:not([hidden]) .js-plotly-plot")'
          '.forEach(p=>Plotly.Plots.resize(p))}</script>'
    )


def build(prior, output, target_directory=None, fits_files=None, *, stacked_url=None, settings_url=None):
    source = json.loads((prior/'csv_provenance.json').read_text(encoding='utf-8-sig'))
    annual = pd.read_csv(prior/'annual_csv_comparison.csv').rename(columns={
        'reservoir':'location', 'water_year':'year', 'expected_days':'expected', 'paired_days':'paired'})
    if 'period' not in annual:
        annual['period'] = 'water year'
    annual['purpose'] = annual.metric.str.startswith('Estimated powerhouse').map(
        {True:'Hydropower', False:'Flood Control'})
    annual.loc[annual.purpose.eq('Flood Control'), 'metric'] = 'Days above Max Evac'
    annual['status'] = annual.purpose.map({'Hydropower':'Powerhouse-first capacity estimate',
                                         'Flood Control':'Outflow strictly above the exported curve'})
    labels = ('Baseline', 'Alternative')
    ramps = pd.read_csv(ROOT/'data/boat_ramp_elevations.csv')
    thresholds = pd.read_csv(ROOT/'data/flood_flow_thresholds.csv').query("location != 'Eugene'")
    biop_schedule = pd.read_csv(ROOT/'model_metadata/scripts/externalRules/MinFlowConfig.csv',
                                comment='#').set_index(['Month', 'Day'])
    records, targets, metrics, routed, models = {}, {}, [], {}, {}
    control_point_flows, bankfull = {}, {}
    _, rule_curve = conservation_rule_curve(target_directory)
    project_data = ROOT/'model_metadata/scripts/externalSVs/BasicProjectData.csv'
    with project_data.open(encoding='utf-8-sig') as stream:
        header = next(i for i, line in enumerate(stream) if line.startswith('Variable,'))
    projects = pd.read_csv(project_data, skiprows=header, encoding='utf-8-sig')
    crests = projects.set_index('Variable').loc['SpillwayCrestElev']
    elevation_criteria = {
        'Lookout Point': ('Spillway crest', float(crests['Lookout Point'])),
        'Detroit': ('Spillway crest', float(crests['Detroit'])),
        'Cougar': ('Minimum temperature tower elevation', 1571.0),
    }
    water_years = set()
    calendar_years = set()
    first = int(annual.year.min())
    last = int(annual.year.max())
    dates = pd.date_range(f'{first-1}-01-01', f'{last+1}-12-31')

    for label in labels:
        case = source[label.lower()]
        models[label] = model = read_compute_report(case, label, (fits_files or {}).get(label))
        compute = model['compute']
        bankfull[label] = bankfull_thresholds(model, thresholds, target_directory)
        min_con = {name: rating[2] for name, rating in conservation_storage_ratings(model, rule_curve).items()}
        daily = pd.read_csv(case['csv'])
        stamps = pd.DatetimeIndex(pd.to_datetime(daily.pop('Timestamp'), errors='raise'))
        if stamps.hasnans or stamps.has_duplicates or not stamps.equals(stamps.normalize()):
            raise ValueError(f'{label}: expected unique daily midnight timestamps')
        daily.index = stamps - pd.Timedelta(days=1)
        daily = daily.apply(pd.to_numeric, errors='coerce').where(lambda x: np.isfinite(x) & x.gt(-900))
        water_years.update(daily.index.year + (daily.index.month >= 10).astype(int))
        calendar_years.update(daily.index.year)
        routed[label] = daily[['Salem__Flow', 'Albany__Flow']]
        columns = {f'{site}__Flow': site for site in thresholds.location}
        control_point_flows[label] = daily[list(columns)].rename(columns=columns)
        records[label], values = {}, {}
        metrics.append(values)
        config = compute.get('baseline_configuration') or {}
        targets[label] = captured_firo_target(compute)

        for column in daily:
            if '__' not in column:
                continue
            reservoir, parameter = column.rsplit('__', 1)
            values_series = daily[column].reindex(dates)
            if parameter in ('Elev', 'Flow-IN', 'Flow-OUT'):
                records[label]['', reservoir+'-Pool', parameter] = (
                    values_series, 'ft' if parameter == 'Elev' else 'cfs')
            elif parameter == 'Stor':
                above = (values_series - min_con.get(reservoir, np.nan)).clip(lower=0)
                values['Water Supply', reservoir, 'Maximum daily storage above Min Con', 'acre-ft', 'max'] = above
                for holiday in HOLIDAYS:
                    values['Recreation', reservoir, f'Storage above Min Con on {holiday}', 'acre-ft', 'max'] = above

        for reservoir, (_, elevation) in elevation_criteria.items():
            pool = daily.get(f'{reservoir}__Elev')
            if pool is not None:
                pool = pool.reindex(dates)
                key = ('Reservoir elevation', reservoir, 'Days above', 'days', 'sum')
                values[key] = pool.gt(elevation).astype(float).where(pool.notna())

        for station in thresholds.itertuples(index=False):
            flow = control_point_flows[label][station.location].reindex(dates)
            values['Flood Control', station.location, 'Peak daily routed flow', 'cfs', 'max'] = flow
            threshold, _ = bankfull[label][station.location]
            values['Flood Control', station.location, BANKFULL_METRIC, 'days', 'sum'] = (
                flow.gt(threshold).astype(float).where(flow.notna()))
        for site in ('Albany', 'Salem'):
            values['Water Quality', site, '10th percentile daily routed flow', 'cfs', 'p10'] = daily[
                f'{site}__Flow'].reindex(dates)
        for reservoir, group in ramps.groupby('reservoir'):
            pool = daily[f'{reservoir}__Elev'].reindex(dates)
            count = sum(pool.gt(level).astype(float) for level in group.elevation_ft)
            values['Recreation', reservoir, 'Pool elevation above ramp', 'ramp-days', 'sum'] = count.where(pool.notna())
            for holiday in HOLIDAYS:
                values['Recreation', reservoir, f'Ramps below pool on {holiday}', 'ramps', 'max'] = count.where(pool.notna())
        schedules = {BIOP: biop_schedule, COMBINED: captured_combined_schedule(config)}
        for purpose, schedule in schedules.items():
            if schedule is not None:
                for reservoir, count in compliance_series(schedule, daily, dates):
                    values[purpose, reservoir, 'Days below minimum-flow target', 'days', 'sum'] = count

    # Sum matched reservoirs each day. Count coincident flood or BiOp threshold
    # events once; a missing member leaves the system value unknown.
    groups = {}
    for key in sorted(metrics[0].keys() | metrics[1].keys()):
        purpose, _, metric, units, reducer = key
        if (purpose in ('Water Supply', 'Recreation') or metric == BANKFULL_METRIC
                or purpose in FLOW_COMPLIANCE):
            groups.setdefault((purpose, 'SYSTEM', metric, units, reducer), []).append(key)
    for key, members in groups.items():
        for case in metrics:
            daily = pd.concat([case.get(member, pd.Series(np.nan, index=dates))
                               for member in members], axis=1)
            total = daily.sum(axis=1, min_count=len(members))
            if key[2] == BANKFULL_METRIC or key[0] in FLOW_COMPLIANCE:
                total = total.gt(0).astype(float).where(total.notna())
            case[key] = total

    # These two metrics were already reduced to annual totals. A system sum
    # is valid only when every member has a complete total in both cases.
    aggregate_rows = []
    for (purpose, metric), records_by_year in annual.groupby(['purpose', 'metric']):
        members = set(records_by_year.location)
        for year, group in records_by_year.groupby('year'):
            if group.location.duplicated().any() or group.expected.nunique() != 1:
                raise ValueError(f'Inconsistent annual coverage for {metric} in {year}')
            row = group.iloc[0].to_dict()
            complete = (set(group.location) == members and group.paired.eq(group.expected).all()
                        and group[['baseline', 'alternative']].notna().all().all())
            row.update(location='SYSTEM', units='reservoir-days' if purpose == 'Flood Control' else row['units'],
                       paired=row['expected'] if complete else 0,
                       baseline=group.baseline.sum() if complete else np.nan,
                       alternative=group.alternative.sum() if complete else np.nan,
                       change=group.change.sum() if complete else np.nan)
            aggregate_rows.append(row)
    annual = pd.concat([annual, pd.DataFrame(aggregate_rows)], ignore_index=True)

    rows = []
    missing = pd.Series(np.nan, index=dates)
    for key in sorted(metrics[0].keys() | metrics[1].keys()):
        purpose, name, metric, units, reducer = key
        flood = purpose == 'Flood Control'
        for year in sorted(water_years if flood else calendar_years):
            window = metric_window(purpose, metric, year)
            pair = pd.concat([case.get(key, missing).reindex(window) for case in metrics], axis=1)
            paired = len(pair.dropna())
            totals = [np.nan, np.nan]
            if paired == len(window):
                totals = pair.quantile(.1).tolist() if reducer == 'p10' else pair.agg(reducer).tolist()
            baseline, alternative = totals
            if purpose == 'Reservoir elevation':
                criterion, elevation = elevation_criteria[name]
                status = f'{criterion} ({elevation:,.1f} ft)'
            elif metric == BANKFULL_METRIC and name != 'SYSTEM':
                status = '; '.join(f'{label}: {bankfull[label][name][0]:,.0f} cfs ({bankfull[label][name][1]})'
                                   for label in labels)
            elif 'above Min Con' in metric:
                status = 'Storage above the lowest rule curve elevation, floored at zero. Requires a captured elevation-storage rating.'
            elif units in ('ramps', 'ramp-days'):
                status = 'Elevation-only screen'
            elif purpose in FLOW_COMPLIANCE:
                status = 'Minimum-flow schedule screen'
            else:
                status = 'Daily POR CSV'
            rows.append(dict(purpose=purpose, location=name, metric=metric, units=units, year=year,
                             period='water year' if flood else 'calendar year',
                             expected=len(window), paired=paired, baseline=baseline,
                             alternative=alternative, change=alternative-baseline,
                             status=status))
    summary = pd.concat([annual, pd.DataFrame(rows)], ignore_index=True)
    output.mkdir(parents=True, exist_ok=False)
    summary.to_csv(output/'annual_comparison.csv', index=False)
    (output/'csv_provenance.json').write_text(json.dumps(source, indent=2), encoding='utf-8')

    system = summary[summary.location.eq('SYSTEM')]
    (output/'system_metrics.html').write_text(
        '<!doctype html><meta charset="utf-8"><title>System metrics</title>'
        '<h1>System metrics</h1><p><a href="index.html">All POR plots</a></p>'
        + (metric_panels(system, labels) if not system.empty else '<p>No system metrics are available.</p>'),
        encoding='utf-8')
    if settings_url is None:
        write_model_settings(output/'model_settings.html', models)
    settings_href = escape(settings_url or 'model_settings.html', quote=True)

    regime_links = write_target_pages(output, target_directory, routed, sorted(calendar_years)) if target_directory else ''
    stacked_href = escape(stacked_url or 'annual_reservoir_overlays.html', quote=True)
    (output/'index.html').write_text(
        '<!doctype html><meta charset="utf-8"><title>POR comparison</title>'
        f'<h1>POR box and duration plots</h1><p><a href="{stacked_href}">'
        'Stacked annual reservoir plots</a> | <a href="system_metrics.html">System metrics</a> | '
        f'<a href="{settings_href}">Configuration comparison</a> | <a href="annual_comparison.csv">Annual data</a></p>'
        '<p>System flood and BiOp counts count a day once across locations. Max Evac totals are '
        'reservoir-days. System storage and ramp totals require all included reservoirs.</p>'
        + regime_links +
        '<p>Flood metrics use water years. Other metrics use calendar years. System maximum storage is the calendar-year maximum of the same-day sum of reservoir storage above Min Con. '
        'Holiday storage and ramps use the holiday date only. Ramp counts use pool elevation.</p>'
        '<p>Elevation counts use daily pool elevation strictly above the Lookout Point and Detroit '
        'spillway crests or Cougar’s 1,571 ft minimum temperature tower elevation.</p>'
        + metric_panels(summary, labels, bankfull), encoding='utf-8')

    if stacked_url is None:
        write_csv_overlays(output/'annual_reservoir_overlays.html', records, targets, models['Baseline'], target_directory)
    print(output/'index.html')
    return records, targets, models, control_point_flows, bankfull


def captured_firo_target(compute):
    config = compute.get('baseline_configuration') or {}
    resolved = config.get('resolved') or {}
    effective = compute.get('effective_alternative_configuration') or {}
    active = effective.get('firoActive')
    if not isinstance(active, bool):
        active = (resolved.get('rules') or {}).get('firo_space', {}).get('settings', {}).get('active')
    relative = (resolved.get('table_paths') or {}).get('firoSpaceConfigCSV')
    embedded = (config.get('tables') or {}).get(relative)
    if active is False:
        return 'FIRO off', None
    if active is not True:
        return 'FIRO activation unavailable', None
    if not embedded:
        return 'FIRO schedule unavailable', None
    table = pd.read_csv(io.StringIO(embedded.lstrip('\ufeff')), comment='#').set_index(['Month', 'Day'])
    return 'FIRO enabled', table


def conservation_rule_curve(target_directory):
    if target_directory is None:
        return None, None
    scripts = target_directory.parent
    sources = (scripts/'RTSPython/CON_SEASON_RULE_CURVES.csv',
               scripts/'rts-setup-package/ExternalPython/CON_SEASON_RULE_CURVES.csv')
    for path in sources:
        if path.is_file():
            table = pd.read_csv(path, encoding='utf-8-sig')
            # The reference uses model years 3000/3001, outside older pandas ranges.
            dates = [datetime.strptime(value, '%d%b%Y') for value in table.pop('date')]
            table.index = pd.MultiIndex.from_tuples([(date.month, date.day) for date in dates])
            table.columns = table.columns.str.strip().str.casefold()
            if table.groupby(level=[0, 1]).nunique().gt(1).any().any():
                raise ValueError(f'Conflicting daily rule curve values in {path}')
            annual = table.groupby(level=[0, 1]).first()
            if (2, 29) not in annual.index and (2, 28) in annual.index and (3, 1) in annual.index:
                annual.loc[(2, 29), :] = (annual.loc[(2, 28)] + annual.loc[(3, 1)]) / 2
            return path, annual
    return None, None


def write_csv_overlays(output, records, targets, baseline, target_directory=None, *, trial_controls=False):
    project_data = ROOT/'model_metadata/scripts/externalSVs/BasicProjectData.csv'
    ramps = pd.read_csv(ROOT/'data/boat_ramp_elevations.csv')
    rule_path, rule_curve = conservation_rule_curve(target_directory)
    storage_axes = {name.casefold(): rating for name, rating in conservation_storage_ratings(baseline, rule_curve).items()}

    def references(reservoir, *_):
        curves, notes = [], []
        dates = overlays.CSV_CALENDAR
        if rule_curve is not None and reservoir.casefold() in rule_curve:
            schedule = rule_curve[reservoir.casefold()].reindex([(day.month, day.day) for day in dates])
            curves.append(('Conservation rule curve (CSV reference)', schedule, '#394556'))
        else:
            notes.append('Conservation rule curve CSV reference unavailable')
        for i, label in enumerate(records):
            status, table = targets[label]
            if table is None:
                notes.append(f'{label}: {status}')
            elif reservoir in table:
                keys = [(day.month, 28 if (day.month, day.day) == (2, 29) else day.day) for day in dates]
                schedule = table[reservoir].reindex(keys).set_axis(dates)
                if schedule.notna().any():
                    color = overlays.CASE_COLORS[i % len(overlays.CASE_COLORS)]
                    curves.append((f'{label} configured FIRO target', schedule, color))
        return curves, notes

    rule_note = (f'Conservation rule curve reference: {rule_path}. February 29 is interpolated '
                 'when absent from the reference.' if rule_path else None)
    overlays.write_annual_overlays(
        output, records, ramps, Path('per-compute JSON'), project_data, {}, {},
        reference_curves=references, trial_controls=trial_controls, rule_note=rule_note, storage_axes=storage_axes)


if __name__ == '__main__':
    main()
