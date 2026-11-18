"""Compare six purposes for the paired daily ResSim period-of-record snapshots."""
import argparse
import hashlib
import json
import shutil
import tempfile
from html import escape
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
from pydsstools.heclib.dss import HecDss

from inspect_por import read_series
from recreation import run as run_recreation, zone_membership

ROOT = Path(__file__).resolve().parent
SITES = ('Albany', 'Salem')
EVACUATION_RULES = {'max evacuation release', 'max evacuation rate'}

PURPOSES = {
    'Flood Control': 'Peak daily routed flow is a flood exposure proxy. Special-release days use total '
    'pool outflow strictly above the saved Max Evacuation Release (Hills Creek: Max Evacuation Rate) '
    'when the rule is in the daily operating-zone stack. Bankfull and damages need approved thresholds '
    'and impact information.',
    'Hydropower': 'Powerplant discharge volume is a throughput proxy. Energy and value require '
    'net head, efficiency, operating limits and generation or pricing data.',
    'Recreation': 'Ramp-days within the configured season require actual pool elevation and '
    'max(rule curve, enabled FIRO target) strictly above the ramp. See the recreation report for '
    'season and activation evidence. Confirm ramp elevation datum before adopting results.',
    'Water Quality': 'The 10th percentile of daily routed flow is a low-flow context proxy. '
    'Temperature, dissolved oxygen and water-quality compliance need constituent data or a calibrated model.',
    'Water Supply': 'Minimum simulated total pool storage is a storage proxy. Usable supply and '
    'reliability require approved storage bounds, accounting, demand and delivery data.',
    'ESA flow compliance': 'Both cases are screened against the positive daily minimum-flow target '
    'saved in the second case (Alternative by default). This shared model reference is a proxy. '
    'ESA compliance is unavailable pending verified applicable, water-year-specific ESA targets '
    'and compliance criteria. The supplied Baseline lacks a usable saved minimum target.',
}


def load_case(path, fpart, report, dates, reference=False):
    groups, sources, values, daily_checks, targets = defaultdict(list), [], {}, {}, {}
    with tempfile.TemporaryDirectory(prefix='purposes-dss-') as directory:
        local = Path(directory) / path.name
        shutil.copyfile(path, local)
        with HecDss.Open(local, mode='r') as fid:
            for pathname in fid.search_path('/*/*/*/*/*/*/', sort=1):
                _, a, b, c, _, interval, part, _ = pathname.split('/')
                if interval.casefold() == '1day' and part == fpart:
                    groups[a, b, c].append(pathname)

            def series(locations, parameter, expected_units, optional=False):
                locations = (locations,) if isinstance(locations, str) else locations
                names = {location.casefold() for location in locations}
                matches = [paths for (_, b, c), paths in groups.items()
                           if b.casefold() in names
                           and c.casefold() == parameter.casefold()]
                if optional and not matches:
                    return pd.Series(np.nan, index=dates)
                if len(matches) != 1:
                    raise ValueError(f'{path.name}: expected one daily {locations}/{parameter} series, got {len(matches)}')
                data, units = read_series(fid, matches[0])
                if units.casefold() not in expected_units:
                    raise ValueError(f'{locations}/{parameter}: unsupported units {units!r}')
                sources.append({'paths': matches[0], 'units': units})
                return data.where(np.isfinite(data))

            for site in SITES:
                flow = series(f'Willamette_at {site}', 'Flow', {'cfs'}).reindex(dates)
                values['Flood Control', site, 'Peak daily routed flow', 'cfs', 'proxy', 'max'] = flow
                values['Water Quality', site, '10th percentile daily routed flow', 'cfs', 'proxy', 'p10'] = flow
                if reference:
                    targets[site] = series(f'Min_Flow_Target_{site}', 'Flow-Min', {'cfs'},
                                           optional=True).reindex(dates)

            for _, location, parameter in sorted(groups):
                if location.casefold().endswith('-power plant') and parameter.casefold() == 'flow':
                    plant = location[:-len('-Power Plant')]
                    flow = series(location, parameter, {'cfs'}).reindex(dates)
                    values['Hydropower', plant, 'Powerplant discharge volume', 'acre-ft', 'proxy', 'sum'] = (
                        flow * 86400 / 43560
                    )

            for operation in report['operations']:
                reservoir = operation['reservoir']
                storage = series(f'{reservoir}-Pool', 'Stor', {'ac-ft', 'acre-ft'}).reindex(dates)
                values['Water Supply', reservoir, 'Minimum total pool storage', 'acre-ft', 'proxy', 'min'] = storage
                zones = operation['zones']
                active_rule = {}
                for zone in zones:
                    matches = [rule for rule in zone['rules'] if rule.casefold() in EVACUATION_RULES]
                    if len(matches) > 1:
                        raise ValueError(f'Ambiguous evacuation rules for {reservoir} / {zone["zone_name"]}')
                    if matches:
                        active_rule[zone['zone_name']] = matches[0]
                if not active_rule:
                    continue

                pool = series(f'{reservoir}-Pool', 'Elev', {'ft', 'feet'})
                previous = pool.reindex(dates - pd.Timedelta(days=1)).set_axis(dates)
                tops = {zone['zone_name']: series(f'{reservoir}-{zone["zone_name"]}', 'Elev-ZONE',
                                                 {'ft', 'feet'}).reindex(dates) for zone in zones[:-1]}
                operating_zone, _ = zone_membership(previous, zones, tops)
                applicable_rule = operating_zone.map(active_rule)
                limit = pd.Series(np.nan, index=dates)
                for rule in dict.fromkeys(active_rule.values()):
                    # Some DSS labels insert Dam before the rule name.
                    names = (f'{reservoir}-{rule}', f'{reservoir}-Dam-{rule}')
                    rule_limit = series(names, 'Flow-MAX', {'cfs'}, optional=True).reindex(dates)
                    limit = limit.mask(applicable_rule.eq(rule), rule_limit)
                outflow = series(f'{reservoir}-Pool', 'Flow-OUT', {'cfs'}).reindex(dates)
                event = special_release(outflow, limit, operating_zone, applicable_rule)
                values['Flood Control', reservoir, 'Special-release days', 'days', 'study definition', 'sum'] = event
                daily_checks['Special release', reservoir] = pd.DataFrame({
                    'zone': operating_zone, 'rule': applicable_rule, 'outflow_cfs': outflow,
                    'limit_cfs': limit, 'special_release_day': event,
                })
    return values, sources, daily_checks, targets


def special_release(outflow, limit, zone, rule):
    known = zone.notna() & (rule.isna() | (outflow.notna() & limit.notna()))
    return (rule.notna() & outflow.gt(limit)).astype(float).where(known)


def annual_rows(key, baseline, alternative, expected):
    purpose, location, metric, units, status, reducer = key
    water_year = expected.index.year + (expected.index.month >= 10).astype(int)
    for year, window in expected.groupby(water_year):
        dates = window.index[window]
        base = baseline.reindex(dates)
        alt = alternative.reindex(dates)
        paired = base.notna() & alt.notna()

        # Keep incomplete windows visible without presenting partial counts as annual totals.
        base_value = alt_value = np.nan
        if len(dates) and paired.all():
            if reducer == 'p10':
                base_value, alt_value = base.quantile(.1), alt.quantile(.1)
            else:
                base_value, alt_value = base.agg(reducer), alt.agg(reducer)
        yield dict(purpose=purpose, location=location, metric=metric, units=units, status=status,
                   year=year, period='water year', expected=len(dates), paired=int(paired.sum()),
                   baseline=base_value, alternative=alt_value, change=alt_value - base_value)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT/'recreation_config.json')
    parser.add_argument('--output', type=Path, default=ROOT/'outputs/purpose_comparison')
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    base = args.config.resolve().parent
    cases = config['cases']
    labels = [case['name'] for case in cases]
    if len(cases) != 2 or len(set(labels)) != 2 or not all(case.get('model_report') for case in cases):
        parser.error('Supply two uniquely named cases in baseline/alternative order, each with a model report.')
    first, last = config['first_year'], config['last_year']
    if first > last:
        parser.error('first_year must be no later than last_year.')
    dates = pd.date_range(f'{first-1}-10-01', f'{last}-09-30')
    expected = pd.Series(True, index=dates)
    metrics, provenance, daily = [], [], []
    for i, case in enumerate(cases):
        dss, report = (base/case[key] for key in ('dss', 'model_report'))
        values, sources, checks, targets = load_case(dss, case['f_part'], json.loads(report.read_text()),
                                            dates, reference=i == 1)
        metrics.append(values)
        for (check, location), table in checks.items():
            daily.append(table.assign(check=check, location=location, case=case['name']))
        provenance.append(dict(case=case['name'], f_part=case['f_part'], series=sources,
                               sha256={str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in (dss, report)}))

    rows = []
    missing = pd.Series(np.nan, index=dates)
    for key in sorted(metrics[0].keys() | metrics[1].keys()):
        rows.extend(annual_rows(key, metrics[0].get(key, missing), metrics[1].get(key, missing), expected))

    for site in SITES:
        reference = targets[site].where(targets[site].ge(0))
        eligible = reference.gt(0)
        flow_key = ('Flood Control', site, 'Peak daily routed flow', 'cfs', 'proxy', 'max')
        flows = [values[flow_key] for values in metrics]
        below = [flow.lt(reference).astype(float).where(flow.notna() & eligible) for flow in flows]
        # Missing target days make the annual target screen incomplete; zero means no positive reference.
        key = ('ESA flow compliance', site, 'Days below shared model minimum-flow reference',
               'days', 'proxy; ESA compliance unavailable', 'sum')
        rows.extend(annual_rows(key, *below, eligible | reference.isna()))
        daily.append(pd.DataFrame({'check': 'ESA flow comparison', 'location': site,
                                   'reference_case': labels[1],
                                   'reference_cfs': reference, 'baseline_flow_cfs': flows[0],
                                   'alternative_flow_cfs': flows[1], 'baseline_below': below[0],
                                   'alternative_below': below[1]}))

    recreation = run_recreation(args.config, args.output/'recreation')
    for row in recreation[recreation.case == labels[1]].itertuples():
        rows.append(dict(purpose='Recreation', location=row.reservoir, metric='Seasonal boat-ramp days',
                         units='ramp-days', status='study definition',
                         year=row.year, period='recreation season', expected=np.nan, paired=np.nan,
                         baseline=row.baseline_boat_ramp_days, alternative=row.boat_ramp_days,
                         change=row.change_from_baseline))

    summary = pd.DataFrame(rows).sort_values(['purpose', 'location', 'metric', 'year'])
    args.output.mkdir(parents=True, exist_ok=True)
    summary.to_csv(args.output/'annual_comparison.csv', index=False)
    pd.concat(daily).rename_axis('date').to_csv(args.output/'daily_threshold_checks.csv')
    (args.output/'provenance.json').write_text(
        json.dumps(dict(config=config, start=str(dates[0].date()), end=str(dates[-1].date()),
                        baseline=labels[0], alternative=labels[1], sources=provenance, methods=PURPOSES),
                   indent=2), encoding='utf-8')
    sections = []
    for purpose, note in PURPOSES.items():
        table = summary[summary.purpose == purpose].drop(columns='purpose')
        sections.append(f'<h2>{purpose}</h2><p>{note}</p>'
                        + table.to_html(index=False, na_rep='—', float_format=lambda x: f'{x:,.2f}'))
    (args.output/'index.html').write_text(
        '<!doctype html><meta charset="utf-8"><title>ResSim purpose comparison</title>'
        '<style>body{font:15px system-ui;margin:2rem;color:#182534}table{border-collapse:collapse}'
        'th,td{border-bottom:1px solid #dbe3eb;padding:.3rem .65rem;text-align:left}'
        'th{background:#eef4f8}tr:nth-child(even){background:#f7f9fb}</style>'
        '<h1>ResSim period-of-record purpose comparison</h1>'
        f'<p>Water years {first}–{last}. Baseline: {escape(labels[0])}. Alternative: {escape(labels[1])}. '
        'Change is alternative minus baseline. Annual results require all expected paired dates. '
        'Recreation coverage is in its separate outputs.</p>'
        '<p><a href="annual_comparison.csv">Annual CSV</a> · '
        '<a href="daily_threshold_checks.csv">Daily threshold checks</a> · '
        '<a href="recreation/box_plots.html">Recreation plots</a></p>'
        + ''.join(sections), encoding='utf-8')
    print(f'Wrote six-purpose comparison to {args.output / "index.html"}')


if __name__ == '__main__':
    main()
