"""Render two POR plot pages from the selected CSV exports and configuration."""
import argparse
from html import escape
import io
import json
from pathlib import Path

import numpy as np
import pandas as pd

import annual_overlays as overlays
from purpose_plots import location_plot

ROOT = Path(__file__).resolve().parent
LEVELS = dict(action_cfs='Days above action / bankfull flow',
              flood_cfs='Days above flood flow', major_flood_cfs='Days above major flood flow')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('prior', type=Path, help='Existing CSV comparison folder')
    parser.add_argument('output', type=Path)
    parser.add_argument('--target-directory', type=Path, help='Watershed scripts/externalSVs folder')
    args = parser.parse_args()
    build(args.prior, args.output, args.target_directory)


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
                    dates = pd.date_range(f'{year-1}-10-01', f'{year}-09-30')
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
                    fig = location_plot(table, labels, kind)
                    peak = table[['baseline', 'alternative']].max().max()
                    fig.update_yaxes(range=[0, max(1, 1.05*peak)] if pd.notna(peak) else [0, 1],
                                     dtick=1 if pd.isna(peak) or peak <= 10 else None)
                    panels.append(fig.to_html(full_html=False, include_plotlyjs=len(panels) == 1))
        filename = f'mainstem_{regime.lower()}.html'
        (output/filename).write_text(
            f'<!doctype html><meta charset="utf-8"><title>{regime_name}</title>'
            f'<h1>Salem and Albany | {regime_name}</h1><a href="index.html">POR plots</a>'
            '<p>Days with routed flow strictly below a positive configured target. Each distinct schedule '
            'is applied to both cases and every year. These are fixed-schedule comparisons.</p>'
            + ''.join(panels), encoding='utf-8')
        links.append(f'<a href="{filename}">{regime_name}</a>')
    return '<p>Salem and Albany target comparisons | ' + ' | '.join(links) + '</p>'


def model_settings(model):
    compute = model['compute']
    baseline = compute.get('baseline_configuration', {})
    resolved = baseline.get('resolved') or {}
    report = {
        'Effective alternative settings': compute.get('effective_alternative_configuration'),
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
    baseline, alternative = map(model_settings, (models['Baseline'], models['Alternative']))
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
        pointer = compute.get('baseline_configuration', {}).get('pointer') or {}
        identities.append(f'<li>{escape(label)} | F-part {cell(compute.get("output_fpart"))} | '
                          f'compute {cell(compute.get("compute_id"))} | applied configuration '
                          f'{cell(pointer["id"]) if pointer.get("id") else "None recorded"}</li>')
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
        '<p>Compares captured values and baseline table checksums. Run IDs are shown for reference. '
        'Uncaptured external inputs and runtime rule behavior are outside this comparison.</p>'
        f'<h2>{len(changed)} changed settings</h2>' + differences
        + f'<details><summary>{len(matching)} matching settings</summary><table><thead>'
        '<tr><th>Setting</th><th>Shared value</th></tr></thead><tbody>'
        + ''.join(matching) + '</tbody></table></details>', encoding='utf-8')


def metric_panels(summary, labels):
    options, panels = [], []
    for n, ((purpose, metric), table) in enumerate(summary.groupby(['purpose', 'metric'])):
        title = escape(f'{purpose} / {metric}')
        options.append(f'<option value="{n}">{title}</option>')
        figures = [location_plot(table, labels, kind) for kind in ('box', 'duration')]
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


def build(prior, output, target_directory=None):
    source = json.loads((prior/'csv_provenance.json').read_text(encoding='utf-8-sig'))
    annual = pd.read_csv(prior/'annual_csv_comparison.csv').rename(columns={
        'reservoir':'location', 'water_year':'year', 'expected_days':'expected', 'paired_days':'paired'})
    annual['purpose'] = annual.metric.str.startswith('Estimated powerhouse').map(
        {True:'Hydropower', False:'Flood Control'})
    annual.loc[annual.purpose.eq('Flood Control'), 'metric'] = 'Days above Max Evac'
    annual['status'] = annual.purpose.map({'Hydropower':'Powerhouse-first capacity estimate',
                                         'Flood Control':'Outflow strictly above the exported curve'})
    labels = ('Baseline', 'Alternative')
    ramps = pd.read_csv(ROOT/'data/boat_ramp_elevations.csv')
    thresholds = pd.read_csv(ROOT/'data/flood_flow_thresholds.csv').query("location != 'Eugene'")
    schedules = pd.read_csv(ROOT/'model_metadata/scripts/externalRules/MinFlowConfig.csv', comment='#')
    records, targets, metrics, routed, models = {}, {}, [], {}, {}
    years = sorted(annual.year.unique())
    dates = pd.date_range(f'{years[0]-1}-10-01', f'{years[-1]}-12-01')

    for label in labels:
        case = source[label.lower()]
        models[label] = model = json.loads(Path(case['report']).read_text(encoding='utf-8-sig'))
        compute = model['compute']
        if (compute['compute_id'], compute['output_fpart']) != (case['compute_id'], case['f_part']):
            raise ValueError(f'{label}: report identity differs from CSV provenance')
        daily = pd.read_csv(case['csv'])
        stamps = pd.DatetimeIndex(pd.to_datetime(daily.pop('Timestamp'), errors='raise'))
        if stamps.hasnans or stamps.has_duplicates or not stamps.equals(stamps.normalize()):
            raise ValueError(f'{label}: expected unique daily midnight timestamps')
        daily.index = stamps - pd.Timedelta(days=1)
        daily = daily.apply(pd.to_numeric, errors='coerce').where(lambda x: np.isfinite(x) & x.gt(-900))
        routed[label] = daily[['Salem__Flow', 'Albany__Flow']]
        records[label], values = {}, {}
        metrics.append(values)
        config = compute.get('baseline_configuration', {})
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
                values['Water Supply', reservoir, 'Minimum total pool storage', 'acre-ft', 'min'] = values_series
                values['Water Supply', reservoir, 'Maximum daily pool storage', 'acre-ft', 'max'] = values_series

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
        schedule = schedules.set_index(['Month', 'Day']).reindex([
            (date.month, 28 if (date.month, date.day) == (2, 29) else date.day) for date in dates])
        schedule.index = dates
        for reservoir, target in schedule.items():
            outlet = 'Foster' if reservoir == 'Green Peter' else reservoir
            flow = daily[f'{outlet}__Flow-OUT'].reindex(dates)
            values['ESA flow compliance', reservoir, 'Days below reservoir BiOp schedule', 'days', 'sum'] = (
                (target.gt(0) & flow.lt(target - target.mul(.02).clip(lower=5)))
                .astype(float).where(flow.notna()))

    # Sum matched reservoirs each day. Count coincident flood or BiOp threshold
    # events once; a missing member leaves the system value unknown.
    groups = {}
    for key in sorted(metrics[0].keys() | metrics[1].keys()):
        purpose, _, metric, units, reducer = key
        if (purpose in ('Water Supply', 'Recreation') or metric in LEVELS.values()
                or metric == 'Days below reservoir BiOp schedule'):
            groups.setdefault((purpose, 'SYSTEM', metric, units, reducer), []).append(key)
    for key, members in groups.items():
        for case in metrics:
            daily = pd.concat([case.get(member, pd.Series(np.nan, index=dates))
                               for member in members], axis=1)
            total = daily.sum(axis=1, min_count=len(members))
            if key[2] in LEVELS.values() or key[2] == 'Days below reservoir BiOp schedule':
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
        for year in years:
            window = (pd.date_range(f'{year}-02-01', f'{year}-12-01') if purpose == 'Recreation'
                      else pd.date_range(f'{year-1}-10-01', f'{year}-09-30'))
            pair = pd.concat([case.get(key, missing).reindex(window) for case in metrics], axis=1)
            paired = len(pair.dropna())
            totals = [np.nan, np.nan]
            if paired == len(window):
                totals = pair.quantile(.1).tolist() if reducer == 'p10' else pair.agg(reducer).tolist()
            baseline, alternative = totals
            rows.append(dict(purpose=purpose, location=name, metric=metric, units=units, year=year,
                             expected=len(window), paired=paired, baseline=baseline,
                             alternative=alternative, change=alternative-baseline,
                             status='Elevation-only screen' if purpose == 'Recreation' else
                             'BiOp schedule screen' if purpose == 'ESA flow compliance' else 'Daily POR CSV'))
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

    regime_links = write_target_pages(output, target_directory, routed, years) if target_directory else ''
    (output/'index.html').write_text(
        '<!doctype html><meta charset="utf-8"><title>POR comparison</title>'
        '<h1>POR box and duration plots</h1><p><a href="annual_reservoir_overlays.html">'
        'Stacked annual reservoir plots</a> | <a href="system_metrics.html">System metrics</a> | '
        '<a href="model_settings.html">Model settings</a> | <a href="annual_comparison.csv">Annual data</a></p>'
        '<p>System flood and BiOp counts count a day once across locations. Max Evac totals are '
        'reservoir-days. System storage and ramp totals require all included reservoirs.</p>'
        + regime_links +
        '<p>Recreation uses pool elevation only. Combined Min Trib rule output and verified FIRO '
        'ramp-days are unavailable in these inputs.</p>'
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
            ROOT/'model_metadata/scripts/externalSVs/BasicProjectData.csv', {}, {})
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
