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
    args = parser.parse_args()
    build(args.prior, args.output)


def build(prior, output):
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
    records, targets, metrics = {}, {}, []
    years = sorted(annual.year.unique())
    dates = pd.date_range(f'{years[0]-1}-10-01', f'{years[-1]}-12-01')

    for label in labels:
        case = source[label.lower()]
        compute = json.loads(Path(case['report']).read_text(encoding='utf-8-sig'))['compute']
        if (compute['compute_id'], compute['output_fpart']) != (case['compute_id'], case['f_part']):
            raise ValueError(f'{label}: report identity differs from CSV provenance')
        daily = pd.read_csv(case['csv'])
        stamps = pd.DatetimeIndex(pd.to_datetime(daily.pop('Timestamp'), errors='raise'))
        if stamps.hasnans or stamps.has_duplicates or not stamps.equals(stamps.normalize()):
            raise ValueError(f'{label}: expected unique daily midnight timestamps')
        daily.index = stamps - pd.Timedelta(days=1)
        daily = daily.apply(pd.to_numeric, errors='coerce').where(lambda x: np.isfinite(x) & x.gt(-900))
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

    options, panels = [], []
    for n, ((purpose, metric), table) in enumerate(summary.groupby(['purpose', 'metric'])):
        title = escape(f'{purpose} / {metric}')
        options.append(f'<option value="{n}">{title}</option>')
        figures = [location_plot(table, labels, kind) for kind in ('box', 'duration')]
        # Set an explicit range even for all-zero traces.
        if purpose == 'Flood Control' and table.units.eq('days').all():
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
    (output/'index.html').write_text(
        '<!doctype html><meta charset="utf-8"><title>POR comparison</title>'
        '<h1>POR box and duration plots</h1><p><a href="annual_reservoir_overlays.html">'
        'Stacked annual reservoir plots</a> | <a href="annual_comparison.csv">Annual data</a></p>'
        '<p>Recreation uses pool elevation only. Salem and Albany daily targets, Combined Min Trib '
        'rule output, and verified FIRO ramp-days are unavailable in these inputs.</p>'
        '<label for="pick">Metric</label> <select id="pick">' + ''.join(options) + '</select>'
        + ''.join(panels)
        + '<script>document.querySelector("#pick").onchange=e=>{document.querySelectorAll("section").forEach(s=>'
          's.hidden=s.id!=="metric-"+e.target.value);document.querySelectorAll("section:not([hidden]) .js-plotly-plot")'
          '.forEach(p=>Plotly.Plots.resize(p))}</script>', encoding='utf-8')

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
