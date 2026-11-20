"""Render two POR plot pages from the selected CSV exports and configuration."""
import argparse
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
LEVELS = dict(action_cfs='Days above action / bankfull flow',
              flood_cfs='Days above flood flow', major_flood_cfs='Days above major flood flow')


BIOP = 'ESA flow compliance / BiOp component'
COMBINED = 'ESA flow compliance / BiOp plus withdrawals'
FLOW_COMPLIANCE = {
    BIOP: ('biop_component.html', 'BiOp minimum-flow component',
           'Daily outflow screened against the fixed BiOp minimum-flow schedule.'),
    COMBINED: ('combined_minimum_flow.html', 'Combined minimum flow',
               'Daily outflow screened against each compute’s captured minimum-flow plus withdrawal schedules. '
               'Missing captured schedules leave that trial unavailable. This screen does not reproduce '
               'native timestep rule adjustments or verify that the rule was active.'),
}
HOLIDAYS = ('Memorial Day', 'Labor Day')


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


def write_compliance_pages(output, summary, render):
    links = []
    for purpose, (filename, title, explanation) in FLOW_COMPLIANCE.items():
        table = summary[summary.purpose.eq(purpose)]
        content = render(table) if not table.empty else '<p>No comparison data are available.</p>'
        (output / filename).write_text(
            f'<!doctype html><meta charset="utf-8"><title>{title}</title><h1>{title}</h1>'
            '<p><a href="index.html">All POR metrics</a></p>'
            f'<p>{explanation} Counts use a tolerance of the greater of 5 cfs or 2% of target. '
            'The Green Peter target is evaluated at Foster. System counts count a day once.</p>'
            + content, encoding='utf-8')
        links.append(f'<a href="{filename}">{title}</a>')
    return '<p>' + ' | '.join(links) + '</p>'


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
    baseline = compute.get('baseline_configuration', {})
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
    have_mappings = all('records' in model.get('saved_input_mappings', {}) for model in models.values())
    baseline, alternative = [model_settings(models[label], have_mappings) for label in ('Baseline', 'Alternative')]
    missing = object()
    changed, matching = [], []

    def cell(value):
        if value is missing:
            return 'Absent'
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
        if len(text) > 120:
            return f'<details><summary>Show value</summary><pre>{escape(text)}</pre></details>'
        return escape(text)

    for key in sorted(baseline.keys() | alternative.keys()):
        base, alt = baseline.get(key, missing), alternative.get(key, missing)
        same = base == alt
        name = escape(' / '.join(key))
        (matching if same else changed).append(
            f'<tr><th scope="row">{name}</th><td>{cell(base)}</td>'
            + ('' if same else f'<td>{cell(alt)}</td>') + '</tr>')

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
    differences = (
        '<table><thead><tr><th>Setting</th><th>Baseline</th><th>Alternative</th></tr></thead><tbody>'
        + ''.join(changed) + '</tbody></table>' if changed else
        '<p>No differences in the captured settings shown below.</p>')
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
        + ('' if have_mappings else '<p>Input mapping comparison is unavailable without both saved files.</p>')
        + f'<h2>{len(changed)} changed settings</h2>' + differences
        + f'<details><summary>{len(matching)} matching settings</summary><table><thead>'
        '<tr><th>Setting</th><th>Shared value</th></tr></thead><tbody>'
        + ''.join(matching) + '</tbody></table></details>', encoding='utf-8')


def metric_panels(summary, labels):
    options, panels = [], []
    for n, ((purpose, metric), table) in enumerate(summary.groupby(['purpose', 'metric'])):
        title = escape(f'{purpose} / {metric}')
        options.append(f'<option value="{n}">{title}</option>')
        figures = [location_plot(table, labels, kind, percentile_boxes=True) for kind in ('box', 'duration')]
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
        body = ''.join(fig.to_html(full_html=False, include_plotlyjs=(n == i == 0))
                       for i, fig in enumerate(figures))
        panels.append(f'<section id="metric-{n}"{" hidden" if n else ""}>{body}</section>')
    return (
        '<label for="pick">Metric</label> <select id="pick">' + ''.join(options) + '</select>'
        + ''.join(panels)
        + '<script>document.querySelector("#pick").onchange=e=>{document.querySelectorAll("section").forEach(s=>'
          's.hidden=s.id!=="metric-"+e.target.value);document.querySelectorAll("section:not([hidden]) .js-plotly-plot")'
          '.forEach(p=>Plotly.Plots.resize(p))}</script>'
    )


def build(prior, output, target_directory=None, fits_files=None):
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
    project_data = ROOT/'model_metadata/scripts/externalSVs/BasicProjectData.csv'
    with project_data.open(encoding='utf-8-sig') as stream:
        header = next(i for i, line in enumerate(stream) if line.startswith('Variable,'))
    projects = pd.read_csv(project_data, skiprows=header, encoding='utf-8-sig')
    crests = projects.set_index('Variable').loc['SpillwayCrestElev']
    elevation_criteria = {
        'Lookout Point': ('Days above spillway crest', float(crests['Lookout Point'])),
        'Detroit': ('Days above spillway crest', float(crests['Detroit'])),
        'Cougar': ('Days above minimum temperature tower elevation', 1571.0),
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
        daily = pd.read_csv(case['csv'])
        stamps = pd.DatetimeIndex(pd.to_datetime(daily.pop('Timestamp'), errors='raise'))
        if stamps.hasnans or stamps.has_duplicates or not stamps.equals(stamps.normalize()):
            raise ValueError(f'{label}: expected unique daily midnight timestamps')
        daily.index = stamps - pd.Timedelta(days=1)
        daily = daily.apply(pd.to_numeric, errors='coerce').where(lambda x: np.isfinite(x) & x.gt(-900))
        water_years.update(daily.index.year + (daily.index.month >= 10).astype(int))
        calendar_years.update(daily.index.year)
        routed[label] = daily[['Salem__Flow', 'Albany__Flow']]
        records[label], values = {}, {}
        metrics.append(values)
        config = compute.get('baseline_configuration') or {}
        relative = config.get('resolved', {}).get('table_paths', {}).get('firoSpaceConfigCSV')
        embedded = config.get('tables', {}).get(relative)
        if embedded:
            targets[label] = pd.read_csv(io.StringIO(embedded), comment='#').set_index(['Month', 'Day'])

        for column in daily:
            if '__' not in column:
                continue
            reservoir, parameter = column.rsplit('__', 1)
            values_series = daily[column].reindex(dates)
            if parameter in ('Elev', 'Flow-IN', 'Flow-OUT'):
                records[label]['', reservoir+'-Pool', parameter] = (
                    values_series, 'ft' if parameter == 'Elev' else 'cfs')
            elif parameter == 'Stor':
                values['Water Supply', reservoir, 'Maximum daily pool storage', 'acre-ft', 'max'] = values_series
                for holiday in HOLIDAYS:
                    values['Recreation', reservoir, f'Pool storage on {holiday}', 'acre-ft', 'max'] = values_series

        for reservoir, (metric, elevation) in elevation_criteria.items():
            pool = daily.get(f'{reservoir}__Elev')
            if pool is not None:
                pool = pool.reindex(dates)
                key = ('Reservoir elevation', reservoir, metric, 'days', 'sum')
                values[key] = pool.gt(elevation).astype(float).where(pool.notna())

        for station in thresholds.itertuples(index=False):
            flow = daily[f'{station.location}__Flow'].reindex(dates)
            values['Flood Control', station.location, 'Peak daily routed flow', 'cfs', 'max'] = flow
            for field, metric in LEVELS.items():
                values['Flood Control', station.location, metric, 'days', 'sum'] = flow.gt(
                    getattr(station, field)).astype(float).where(flow.notna())
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
        if (purpose in ('Water Supply', 'Recreation') or metric in LEVELS.values()
                or purpose in FLOW_COMPLIANCE):
            groups.setdefault((purpose, 'SYSTEM', metric, units, reducer), []).append(key)
    for key, members in groups.items():
        for case in metrics:
            daily = pd.concat([case.get(member, pd.Series(np.nan, index=dates))
                               for member in members], axis=1)
            total = daily.sum(axis=1, min_count=len(members))
            if key[2] in LEVELS.values() or key[0] in FLOW_COMPLIANCE:
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
            rows.append(dict(purpose=purpose, location=name, metric=metric, units=units, year=year,
                             period='water year' if flood else 'calendar year',
                             expected=len(window), paired=paired, baseline=baseline,
                             alternative=alternative, change=alternative-baseline,
                             status='Elevation-only screen' if units in ('ramps', 'ramp-days') else
                             'Minimum-flow schedule screen' if purpose in FLOW_COMPLIANCE else 'Daily POR CSV'))
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
    write_model_settings(output/'model_settings.html', models)

    compliance_links = write_compliance_pages(output, summary, lambda table: metric_panels(table, labels))
    regime_links = write_target_pages(output, target_directory, routed, sorted(calendar_years)) if target_directory else ''
    (output/'index.html').write_text(
        '<!doctype html><meta charset="utf-8"><title>POR comparison</title>'
        '<h1>POR box and duration plots</h1><p><a href="annual_reservoir_overlays.html">'
        'Stacked annual reservoir plots</a> | <a href="system_metrics.html">System metrics</a> | '
        '<a href="model_settings.html">Model settings</a> | <a href="annual_comparison.csv">Annual data</a></p>'
        '<p>System flood and BiOp counts count a day once across locations. Max Evac totals are '
        'reservoir-days. System storage and ramp totals require all included reservoirs.</p>'
        + regime_links + compliance_links +
        '<p>Flood metrics use water years. Other metrics use calendar years. System maximum storage is the calendar-year maximum of the sum of each day’s reservoir storage. '
        'Holiday storage and ramps use the holiday date only. Ramp counts use pool elevation.</p>'
        '<p>Elevation counts use daily pool elevation strictly above the Lookout Point and Detroit '
        'spillway crests or Cougar’s 1,571 ft minimum temperature tower elevation.</p>'
        + metric_panels(summary, labels), encoding='utf-8')

    def firo_references(reservoir, *_):
        curves = []
        for i, (label, table) in enumerate(targets.items()):
            if reservoir in table:
                dates = overlays.CALENDAR
                keys = [(day.month, 28 if (day.month, day.day) == (2, 29) else day.day) for day in dates]
                schedule = table[reservoir].reindex(keys).set_axis(dates)
                if schedule.notna().any():
                    curves.append((f'{label} configured FIRO target', schedule, overlays.CASE_COLORS[i]))
        return curves, [] if curves else ['Captured FIRO schedule unavailable']

    original = overlays.firo_overlays
    try:
        overlays.firo_overlays = firo_references
        overlay_path = output/'annual_reservoir_overlays.html'
        overlays.write_annual_overlays(overlay_path, records, ramps, Path('per-compute JSON'),
            project_data, {}, {})
        content = overlay_path.read_text(encoding='utf-8')
        overlay_path.write_text(content.replace('Rule curves come from DSS Elev-ZONE. '
            'The FIRO line is the recurring target schedule from the reference CSV. '
            'It does not establish whether FIRO was active in either run.',
            'Pool series come from the CSV exports. FIRO lines show captured configured schedules. '
            'Daily activation and rule curves are unavailable.'), encoding='utf-8')
    finally:
        overlays.firo_overlays = original
    print(output/'index.html')


if __name__ == '__main__':
    main()
