"""Compare six purposes for the paired daily ResSim period-of-record snapshots."""
import argparse
import hashlib
import json
import tempfile
from contextlib import ExitStack
from html import escape
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
from pydsstools.heclib.dss import HecDss

from inspect_por import case_catalog, copy_snapshot, read_series, simulation_cases
from purpose_plots import distribution_report
from water_supply import water_supply_panel
from recreation import firo_schedule as recurring_schedule
from recreation import run as run_recreation, season_dates, zone_membership

ROOT = Path(__file__).resolve().parent
SITES = ('Albany', 'Salem')
FLOOD_LEVELS = {
    'action_cfs': 'Days above action / bankfull flow',
    'flood_cfs': 'Days above flood flow',
    'major_flood_cfs': 'Days above major flood flow',
}
RESERVOIR_MINIMUM = 'Days below reservoir ESA minimum reference'
COMBINED_MINIMUM = 'Days below combined minimum release'
RELEASE_METRICS = (RESERVOIR_MINIMUM, COMBINED_MINIMUM)
EVACUATION_RULES = {'max evacuation release', 'max evacuation rate'}

PURPOSES = {
    'Flood Control': 'Threshold metrics count daily routed flows strictly above the specified cfs levels. '
    'Peak daily routed flow is also shown. Special-release days use total '
    'pool outflow strictly above the saved Max Evacuation Release (Hills Creek: Max Evacuation Rate) '
    'when the rule is in the daily operating-zone stack. Flood damages require impact information.',
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
    'and compliance criteria. Reservoir screens compare the supplied BiOp schedule and the saved '
    'Combined Min Trib rule with the corresponding outlet release. Neither establishes regulatory compliance.',
}

SYSTEM_METRICS = {
    'Special-release days': ('Special-release reservoir-days', 'reservoir-days'),
    'Powerplant discharge volume': ('Total powerplant throughput', 'acre-ft'),
    'Minimum total pool storage': ('Minimum combined pool storage', 'acre-ft'),
    'Pool elevation above ramp': ('System pool elevation above ramp', 'ramp-days'),
    **{metric: (f'{metric} at any control point', 'days') for metric in FLOOD_LEVELS.values()},
    **{metric: (f'{metric} at any assessed project', 'days') for metric in RELEASE_METRICS},
}

SYSTEM_STORAGE = ('Water Supply', 'SYSTEM', 'Minimum combined pool storage', 'acre-ft', 'proxy', 'min')
MAX_RELATIVE_STORAGE = ('Water Supply', 'SYSTEM', 'Maximum combined storage relative to seasonal minimum',
                        'acre-ft', 'relative to observed Baseline seasonal minimum', 'max')


def relative_system_storage(metrics, season_windows, water_dates):
    daily = pd.concat([case[SYSTEM_STORAGE] for case in metrics], axis=1, keys=['baseline', 'alternative'])
    complete = [dates for dates in season_windows if daily.reindex(dates).notna().to_numpy().all()]
    if not complete:
        return None, None
    reference_days = complete[0].append(complete[1:])
    reference_date = daily.loc[reference_days, 'baseline'].idxmin()
    zero = daily.at[reference_date, 'baseline']
    return daily.reindex(water_dates) - zero, {
        'zero_acre_ft': float(zero), 'baseline_date': str(reference_date.date()),
        'complete_paired_seasons': len(complete),
    }


def add_system_metrics(metrics, missing, release_sites=None):
    # Use the same members in both cases. A missing member makes the daily total unknown.
    groups = defaultdict(list)
    for key in sorted(metrics[0].keys() | metrics[1].keys()):
        purpose, location, metric, _, status, reducer = key
        if metric in RELEASE_METRICS and (metric, location) not in (release_sites or ()):
            continue
        if metric in SYSTEM_METRICS:
            name, units = SYSTEM_METRICS[metric]
            groups[purpose, 'SYSTEM', name, units, status, reducer].append(key)
    for key, members in groups.items():
        for case in metrics:
            daily = pd.concat([case.get(member, missing) for member in members], axis=1)
            total = daily.sum(axis=1, min_count=len(members))
            # Count overlapping threshold events once on a system day.
            if members[0][2] in (*FLOOD_LEVELS.values(), *RELEASE_METRICS):
                total = total.gt(0).astype(float).where(total.notna())
            case[key] = total
    return {key[2]: [member[1] for member in members] for key, members in groups.items()}


def open_snapshot(stack, path):
    directory = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix='purposes-dss-')))
    local = directory / path.name
    copy_snapshot(path, local)
    with local.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    fid = stack.enter_context(HecDss.Open(local, mode='r'))
    return fid, case_catalog(fid), digest


def read_flood_thresholds(path):
    thresholds = pd.read_csv(path, encoding='utf-8-sig')
    identities = ['station_id', 'location', 'dss_location']
    thresholds = thresholds[[*identities, *FLOOD_LEVELS]]
    for name in identities:
        field = thresholds[name].astype('string').str.strip()
        if field.isna().any() or field.eq('').any() or field.str.casefold().duplicated().any():
            raise ValueError(f'{path}: {name} must be nonempty and unique.')
        thresholds[name] = field
    thresholds[list(FLOOD_LEVELS)] = thresholds[list(FLOOD_LEVELS)].apply(pd.to_numeric, errors='raise')
    levels = thresholds[list(FLOOD_LEVELS)].to_numpy()
    if (thresholds.empty or not np.isfinite(levels).all() or (levels <= 0).any()
            or (np.diff(levels, axis=1) <= 0).any()):
        raise ValueError(f'{path}: require positive, increasing action, flood, and major flood thresholds.')
    return thresholds


def days_above(flow, threshold):
    return flow.gt(threshold).astype(float).where(flow.notna())


def release_shortfall(outflow, target):
    # Same model-checker tolerance: 5 cfs or 2 percent of the target, whichever is greater.
    tolerance = target.mul(.02).clip(lower=5)
    return (target.gt(0) & outflow.lt(target - tolerance)).astype(float).where(
        outflow.notna() & target.ge(0)
    )


def load_case(fid, catalog, path, fpart, report, dates, flood_thresholds, esa_minimums,
              reference=False, ramps=None):
    groups = {(a, b, c): paths for (a, b, c, interval, part), paths in catalog.items()
              if interval.casefold() == '1day' and part == fpart}
    sources, values, daily_checks, targets = [], {}, {}, {}
    if not groups:
        raise ValueError(f'{path.name}: no daily records for F={fpart}')

    cache = {}

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
        paths = tuple(matches[0])
        if paths not in cache:
            cache[paths] = read_series(fid, paths)
            sources.append({'paths': paths, 'units': cache[paths][1]})
        data, units = cache[paths]
        if units.casefold() not in expected_units:
            raise ValueError(f'{locations}/{parameter}: unsupported units {units!r}')
        return data.where(np.isfinite(data))

    routed_flows = {}
    for station in flood_thresholds.itertuples(index=False):
        flow = series(station.dss_location, 'Flow', {'cfs'}, optional=True).reindex(dates)
        routed_flows[station.dss_location.casefold()] = flow
        location = station.location
        values['Flood Control', location, 'Peak daily routed flow', 'cfs', 'proxy', 'max'] = flow
        for field, metric in FLOOD_LEVELS.items():
            values['Flood Control', location, metric, 'days', 'daily routed flow threshold', 'sum'] = (
                days_above(flow, getattr(station, field))
            )
    for site in SITES:
        name = f'Willamette_at {site}'
        if name.casefold() not in routed_flows:
            routed_flows[name.casefold()] = series(name, 'Flow', {'cfs'}, optional=True).reindex(dates)
        values['Water Quality', site, '10th percentile daily routed flow', 'cfs', 'proxy', 'p10'] = (
            routed_flows[name.casefold()]
        )
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

    for _, location, parameter in sorted(groups):
        if location.casefold().endswith('-pool') and parameter.casefold() == 'stor':
            reservoir = location[:-len('-Pool')]
            storage = series(location, 'Stor', {'ac-ft', 'acre-ft'}).reindex(dates)
            values['Water Supply', reservoir, 'Minimum total pool storage', 'acre-ft', 'proxy', 'min'] = storage

    schedule_locations = {name.strip().casefold() for name in pd.read_csv(
        esa_minimums, comment='#', encoding='utf-8-sig', nrows=0).columns} - {'month', 'day'}
    reservoirs = sorted({location[:-len('-Pool')] for _, location, parameter in groups
                         if location.casefold().endswith('-pool') and parameter.casefold() == 'flow-out'})
    for reservoir in reservoirs:
        outflow = series(f'{reservoir}-Pool', 'Flow-OUT', {'cfs'}).reindex(dates)
        combined = series(f'{reservoir}-Combined Min Trib', 'Flow-SPEC', {'cfs'}, optional=True).reindex(dates)
        # The configured Green Peter tributary target is assessed downstream at Foster.
        release_at = 'Foster' if reservoir.casefold() == 'green peter' else reservoir
        if reservoir.casefold() in schedule_locations:
            esa_target, _ = recurring_schedule(esa_minimums, reservoir, dates)
            esa_target = esa_target.fillna(0.)
        else:
            esa_target = pd.Series(np.nan, index=dates)
        esa_outflow = series(f'{release_at}-Pool', 'Flow-OUT', {'cfs'}, optional=True).reindex(dates)
        for name, target, release, point, status in [
            (RESERVOIR_MINIMUM, esa_target, esa_outflow, release_at,
             'BiOp schedule screen'),
            (COMBINED_MINIMUM, combined, outflow, reservoir, 'saved Combined Min Trib rule'),
        ]:
            short = release_shortfall(release, target)
            values['ESA flow compliance', reservoir, name, 'days', status, 'sum'] = short
            daily_checks[name, reservoir] = pd.DataFrame({
                'release_location': point, 'outflow_cfs': release, 'reference_cfs': target,
                'below_minimum': short,
            })

    if ramps is not None:
        for reservoir, ramp_group in ramps.groupby('reservoir'):
            location = f'{reservoir}-Pool'
            pool = series(location, 'Elev', {'ft', 'feet'}, optional=True).reindex(dates)
            # Keep every workbook reservoir in the system denominator, even if its DSS series is missing.
            count = sum(pool.gt(elevation).astype(float) for elevation in ramp_group.elevation_ft)
            values['Recreation', reservoir, 'Pool elevation above ramp', 'ramp-days',
                   'Elevation-only screen; FIRO eligibility unverified', 'sum'] = count.where(pool.notna())

    for operation in report['operations'] if report is not None else []:
        reservoir = operation['reservoir']
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


def annual_rows(key, baseline, alternative, expected, period='water year'):
    purpose, location, metric, units, status, reducer = key
    years = expected.index.year
    if period == 'water year':
        years = years + (expected.index.month >= 10).astype(int)
    for year, window in expected.groupby(years):
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
                   year=year, period=period, expected=len(dates), paired=int(paired.sum()),
                   baseline=base_value, alternative=alt_value, change=alt_value - base_value)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sources = parser.add_mutually_exclusive_group()
    sources.add_argument('--config', type=Path, help='Run-specific paired analysis configuration.')
    sources.add_argument('--simulation-dss', type=Path, help='One DSS with Baseline (-0) and Alternative (-1).')
    parser.add_argument('--first-year', type=int)
    parser.add_argument('--last-year', type=int)
    parser.add_argument('--storage-season', nargs=2, metavar=('START_MM-DD', 'END_MM-DD'),
                        help='Season used to find the shared storage zero. Defaults to the configured season.')
    parser.add_argument('--flood-thresholds', type=Path, default=ROOT/'data/flood_flow_thresholds.csv')
    parser.add_argument('--esa-minimums', type=Path,
                        default=ROOT/'model_metadata/scripts/externalRules/MinFlowConfig.csv',
                        help='Recurring tributary BiOp minimum-flow schedule (cfs).')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    local_mode = args.simulation_dss is not None
    config_path = args.config or ROOT/'recreation_config.json'
    base = config_path.resolve().parent
    config = json.loads(config_path.read_text())
    output = args.output or ROOT/'outputs'/('purpose_comparison_local' if local_mode else 'purpose_comparison')
    if local_mode:
        if args.first_year is None or args.last_year is None:
            parser.error('--simulation-dss requires --first-year and --last-year.')
        config.update(first_year=args.first_year, last_year=args.last_year)
    elif args.first_year is not None or args.last_year is not None:
        parser.error('Set the study years in --config, or use both year flags with --simulation-dss.')

    flood_thresholds = read_flood_thresholds(args.flood_thresholds)
    first, last = config['first_year'], config['last_year']
    if first > last:
        parser.error('first_year must be no later than last_year.')
    water_dates = pd.date_range(f'{first-1}-10-01', f'{last}-09-30')
    expected = pd.Series(True, index=water_dates)
    storage_season = config['season']
    if args.storage_season:
        start, end = args.storage_season
        storage_season = dict(type='fixed', start=start, end=end)
    storage_windows = [season_dates(year, storage_season) for year in range(first, last+1)]
    ramps = season_expected = None
    dates = water_dates.union(storage_windows[0].append(storage_windows[1:]))
    if local_mode:
        ramps = pd.read_csv(base/config['ramps'])
        season_dates_all = pd.DatetimeIndex([
            date for year in range(first, last+1) for date in season_dates(year, config['season'])
        ])
        season_expected = pd.Series(True, index=season_dates_all)
        dates = dates.union(season_dates_all)

    metrics, provenance, daily = [], [], []
    release_sites = set()
    with ExitStack() as stack:
        opened = {}
        if local_mode:
            path = args.simulation_dss.resolve()
            fid, catalog, digest = open_snapshot(stack, path)
            opened[path] = fid, catalog, digest
            config['cases'] = [dict(name=label, dss=str(path), f_part=fpart)
                               for label, fpart in simulation_cases(catalog)]

        cases = config['cases']
        labels = [case['name'] for case in cases]
        if len(cases) != 2 or len(set(labels)) != 2 or (
                not local_mode and not all(case.get('model_report') for case in cases)):
            parser.error('Supply two uniquely named cases in baseline/alternative order, each with a model report.')

        for i, case in enumerate(cases):
            dss = (base/case['dss']).resolve()
            report = base/case['model_report'] if case.get('model_report') else None
            if dss not in opened:
                opened[dss] = open_snapshot(stack, dss)
            fid, catalog, digest = opened[dss]
            hashes = {str(dss): digest}
            model = None
            if report:
                report_bytes = report.read_bytes()
                hashes[str(report)] = hashlib.sha256(report_bytes).hexdigest()
                model = json.loads(report_bytes)
            values, series_sources, checks, targets = load_case(fid, catalog, dss, case['f_part'], model,
                                                                dates, flood_thresholds, args.esa_minimums,
                                                                reference=i == 1, ramps=ramps)
            metrics.append(values)
            for (check, location), table in checks.items():
                if check in RELEASE_METRICS and table.reference_cfs.ge(0).any():
                    release_sites.add((check, location))
                daily.append(table.assign(check=check, location=location, case=case['name']))
            provenance.append(dict(case=case['name'], f_part=case['f_part'], series=series_sources,
                                   sha256=hashes))

    rows = []
    missing = pd.Series(np.nan, index=dates)
    system_members = add_system_metrics(metrics, missing, release_sites)
    for key in sorted(metrics[0].keys() | metrics[1].keys()):
        base_series, alt_series = (case.get(key, missing) for case in metrics)
        if key[0] == 'Recreation':
            rows.extend(annual_rows(key, base_series, alt_series, season_expected, 'recreation season'))
        else:
            rows.extend(annual_rows(key, base_series, alt_series, expected))

    storage = storage_reference = None
    if SYSTEM_STORAGE[2] in system_members:
        storage, storage_reference = relative_system_storage(metrics, storage_windows, water_dates)
    if storage_reference is not None:
        storage_reference['season'] = storage_season
        rows.extend(annual_rows(MAX_RELATIVE_STORAGE, storage.baseline, storage.alternative, expected))

    storage_rows = [row for row in rows if row['purpose'] == 'Water Supply']
    storage_daily = {}
    for key in sorted(metrics[0].keys() | metrics[1].keys(), key=lambda key: (key[1] == 'SYSTEM', key)):
        if key[0] != 'Water Supply':
            continue
        location = key[1]
        pair = pd.concat([case.get(key, missing).reindex(water_dates) for case in metrics], axis=1,
                         keys=['baseline', 'alternative'])
        storage_daily[location] = pair
        peak_key = ('Water Supply', location, 'Maximum daily pool storage', 'acre-ft', 'daily modeled storage', 'max')
        storage_rows.extend(annual_rows(peak_key, pair.baseline, pair.alternative, expected))
        for holiday, position in [('Memorial Day', 0), ('Labor Day', -1)]:
            holidays = pd.DatetimeIndex([season_dates(year, {'type': 'memorial_to_labor'})[position]
                                         for year in range(first, last+1)])
            holiday_key = ('Water Supply', location, f'{holiday} storage', 'acre-ft',
                           'daily modeled storage on the holiday', 'max')
            storage_rows.extend(annual_rows(holiday_key, pair.baseline, pair.alternative,
                                            pd.Series(True, index=holidays), 'holiday'))
    # Preserve the original rows and add the new annual and holiday storage metrics.
    rows = [row for row in rows if row['purpose'] != 'Water Supply'] + storage_rows

    for site in SITES:
        reference = targets[site].reindex(water_dates)
        reference = reference.where(reference.ge(0))
        eligible = reference.gt(0)
        flow_key = ('Water Quality', site, '10th percentile daily routed flow', 'cfs', 'proxy', 'p10')
        flows = [values[flow_key].reindex(water_dates) for values in metrics]
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

    if not local_mode:
        recreation = run_recreation(config_path, output/'recreation')
        for row in recreation[recreation.case == labels[1]].itertuples():
            rows.append(dict(purpose='Recreation', location=row.reservoir, metric='Seasonal boat-ramp days',
                             units='ramp-days', status='study definition',
                             year=row.year, period='recreation season', expected=np.nan, paired=np.nan,
                             baseline=row.baseline_boat_ramp_days, alternative=row.boat_ramp_days,
                             change=row.change_from_baseline))

    summary = pd.DataFrame(rows).sort_values(['purpose', 'location', 'metric', 'year'])
    output.mkdir(parents=True, exist_ok=True)
    summary.to_csv(output/'annual_comparison.csv', index=False)
    flood_thresholds.to_csv(output/'flood_flow_thresholds_used.csv', index=False)
    pd.concat(daily).rename_axis('date').to_csv(output/'daily_threshold_checks.csv')
    # Always overwrite the CSV so a rerun with incomplete coverage cannot leave stale values.
    storage_csv = storage if storage is not None else pd.DataFrame(columns=['baseline', 'alternative'])
    storage_csv.rename_axis('date').to_csv(output/'daily_relative_system_storage.csv')
    methods = PURPOSES.copy()
    if local_mode:
        methods['Recreation'] = (
            'The elevation-only screen counts ramp-days strictly above the ramp threshold from '
            'February 1 through December 1. Verified ramp-days require the rule curve and FIRO evidence.'
        )
    (output/'provenance.json').write_text(
        json.dumps(dict(config=config, start=str(water_dates[0].date()), end=str(water_dates[-1].date()),
                        mode='DSS-only' if local_mode else 'configured run evidence',
                        baseline=labels[0], alternative=labels[1], sources=provenance, methods=methods,
                        system_members=system_members, storage_reference=storage_reference,
                        flood_thresholds=str(args.flood_thresholds.resolve()),
                        esa_minimums=str(args.esa_minimums.resolve())),
                   indent=2), encoding='utf-8')
    sections = []
    for purpose, note in methods.items():
        table = summary[summary.purpose == purpose].drop(columns='purpose')
        thresholds_html = ''
        if purpose == 'Flood Control':
            thresholds_html = ('<h3>Control-point flow thresholds (cfs)</h3>'
                               + flood_thresholds.to_html(index=False))
        sections.append(f'<details><summary>{purpose} data table</summary><p>{note}</p>'
                        + thresholds_html + table.to_html(index=False, na_rep='—', float_format=lambda x: f'{x:,.2f}')
                        + '</details>')
    recreation_note = (
        'Local DSS mode uses an elevation-only ramp screen. Verified recreation ramp-days and '
        'special-release counts require matching run evidence.'
        if local_mode else 'See the <a href="recreation/box_plots.html">recreation plots</a> for seasonal coverage.'
    )
    source_note = f'<p>Local DSS: {escape(str(args.simulation_dss.resolve()))}</p>' if local_mode else ''
    (output/'index.html').write_text(
        '<!doctype html><meta charset="utf-8"><title>ResSim purpose comparison</title>'
        '<style>body{font:15px system-ui;margin:2rem;color:#182534}table{border-collapse:collapse}'
        'select{font:inherit;max-width:100%;padding:.35rem}'
        'th,td{border-bottom:1px solid #dbe3eb;padding:.3rem .65rem;text-align:left}'
        'th{background:#eef4f8}tr:nth-child(even){background:#f7f9fb}</style>'
        '<h1>ResSim period-of-record purpose comparison</h1>'
        f'<p>Water years {first}–{last}. Baseline: {escape(labels[0])}. Alternative: {escape(labels[1])}. '
        'Change is alternative minus baseline. Annual results require all expected paired dates. '
        f'{recreation_note}</p>'
        f'{source_note}'
        '<p><a href="annual_comparison.csv">Annual CSV</a> · '
        '<a href="daily_threshold_checks.csv">Daily threshold checks</a> · '
        '<a href="flood_flow_thresholds_used.csv">Flood flow thresholds used (cfs)</a></p>'
        '<p>Choose a metric to see box plots first and duration plots below. Each location has its own y-axis. The system appears last where available. '
        'The duration plot ranks those annual or seasonal values. The bars show the change in the same year.</p>'
        '<p>System throughput can include the same water at successive plants. '
        'System flood counts record a day once when any control point exceeds the selected threshold. '
        'System release counts record a day once when any assessed project falls below its target. '
        'System results require data from all included locations.</p>'
        + distribution_report(
            summary, labels, SYSTEM_METRICS, FLOOD_LEVELS,
            extra_panels=[('Water Supply / Daily storage duration',
                           water_supply_panel(storage_daily, storage, storage_reference, labels))],
        )
        + ''.join(sections), encoding='utf-8')
    print(f'Wrote six-purpose comparison to {output / "index.html"}')


if __name__ == '__main__':
    main()
