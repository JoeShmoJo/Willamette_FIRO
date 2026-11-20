"""Compare estimated powerhouse throughput and evacuation-curve exceedance without DSS."""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

def curve(elevation, points):
    xy = np.asarray(points, dtype=float)
    if xy.ndim != 2 or xy.shape[1] != 2 or not len(xy) or not np.isfinite(xy).all():
        raise ValueError("Expected finite elevation and release pairs")
    if (np.diff(xy[:, 0]) <= 0).any() or (xy[:, 1] < 0).any():
        raise ValueError("Expected increasing elevations and nonnegative releases")
    return pd.Series(np.interp(elevation, xy[:, 0], xy[:, 1]), index=elevation.index).where(elevation.notna())


def evacuation_limit(op, previous):
    tables = [limit for zone in op['zones'] for limit in zone.get('evacuation_limits', {}).values()]
    if not tables:
        return None
    limit = tables[0]
    if any(table != limit for table in tables):
        raise ValueError("Zone-specific evacuation limits need daily zone boundaries")
    settings = limit.get('settings', {})
    if any(value for field, value in settings.items() if field.startswith('uses_')):
        raise ValueError("Evacuation rule modifiers need native evaluation")
    if limit.get('kind') == 'constant':
        return pd.Series(float(limit['value']), index=previous.index)
    variable = limit.get('independent_variable', {})
    if (limit.get('kind') != 'paired_values' or limit['interpolation_type'] != 0 or limit['seasonal']
            or variable.get('model_variable_id') != 10 or variable.get('time_series_function') != 'Previous Value'
            or variable.get('time_series_lag') != 0 or limit.get('y_units', '').casefold() != 'cfs'
            or any(len(point['y']) != 1 for point in limit['points'])):
        raise ValueError("Expected a single linear previous-pool-elevation evacuation curve")
    return curve(previous, [(point['x'], point['y'][0]) for point in limit['points']])


def load_case(csv_path, report_path, fpart, dates):
    report = json.loads(report_path.read_text(encoding='utf-8-sig'))
    compute = report['compute']
    if compute['output_fpart'] != fpart or not compute['compute_id']:
        raise ValueError(f"{report_path}: expected compute for {fpart}")
    daily = pd.read_csv(csv_path)
    stamps = pd.DatetimeIndex(pd.to_datetime(daily.pop('Timestamp'), errors='raise'))
    if stamps.hasnans or stamps.has_duplicates or not stamps.equals(stamps.normalize()):
        raise ValueError(f"{csv_path}: expected unique daily midnight timestamps")
    daily.index = stamps - pd.Timedelta(days=1)
    daily = daily.apply(pd.to_numeric, errors='coerce').replace([np.inf, -np.inf], np.nan)
    values = {}
    for op in report['operations']:
        reservoir = op['reservoir']
        try:
            pool = daily[f'{reservoir}__Elev'].where(lambda value: value.gt(-900))
            elevation = pool.reindex(dates)
            outflow = daily[f'{reservoir}__Flow-OUT'].reindex(dates).where(lambda x: x.ge(0))
            capacities = []
            for outlet in op['rating_tables']['outlet_capacities']:
                if outlet['outlet'].casefold() == 'power plant':
                    if outlet.get('columns') != ['elevation_ft', 'capacity_cfs']:
                        raise ValueError("Missing powerhouse capacity table or unexpected units")
                    capacities.append(curve(elevation, outlet['rows']))
            if capacities:
                key = ('Hydropower', reservoir, 'Estimated powerhouse throughput',
                       'acre-ft', 'powerhouse first, up to capacity', 'sum')
                values[key] = np.minimum(sum(capacities), outflow) * 86400 / 43560

            previous = pool.reindex(dates - pd.Timedelta(days=1)).set_axis(dates)
            limit = evacuation_limit(op, previous)
            if limit is not None:
                key = ('Flood Control', reservoir, 'Days above Max Evac',
                       'days', 'total outflow exceeds curve at previous pool elevation', 'sum')
                values[key] = outflow.gt(limit).astype(float).where(outflow.notna() & limit.notna())
        except (ValueError, KeyError) as error:
            raise ValueError(f"{report_path}: {reservoir}: {error}") from error
    return values, {'csv': str(csv_path), 'report': str(report_path), 'f_part': fpart,
                    'compute_id': compute['compute_id']}


def annual_rows(key, baseline, alternative, years):
    purpose, reservoir, metric, units, status, reducer = key
    period = 'water year' if purpose == 'Flood Control' else 'calendar year'
    for year in years:
        dates = (pd.date_range(f'{year-1}-10-01', f'{year}-09-30') if period == 'water year'
                 else pd.date_range(f'{year}-01-01', f'{year}-12-31'))
        base = baseline.reindex(dates)
        alt = alternative.reindex(dates)
        paired = base.notna() & alt.notna()
        base_value = alt_value = np.nan
        if len(dates) and paired.all():
            base_value, alt_value = base.agg(reducer), alt.agg(reducer)
        yield dict(purpose=purpose, reservoir=reservoir, metric=metric, units=units, status=status,
                   year=year, period=period, expected_days=len(dates), paired_days=int(paired.sum()),
                   baseline=base_value, alternative=alt_value, change=alt_value - base_value)


def main():

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', nargs=3, required=True, metavar=('CSV', 'REPORT', 'F_PART'))
    parser.add_argument('--alternative', nargs=3, required=True, metavar=('CSV', 'REPORT', 'F_PART'))
    parser.add_argument('--first-year', type=int, required=True)
    parser.add_argument('--last-year', type=int, required=True)
    parser.add_argument('--calendar-first-year', type=int)
    parser.add_argument('--calendar-last-year', type=int)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.first_year > args.last_year:
        parser.error('first year must be no later than last year')
    water_years = range(args.first_year, args.last_year + 1)
    first_calendar = args.calendar_first_year or args.first_year - 1
    last_calendar = args.calendar_last_year or args.last_year
    if first_calendar > last_calendar:
        parser.error('first calendar year must be no later than last calendar year')
    calendar_years = range(first_calendar, last_calendar + 1)
    dates = pd.date_range(min(f'{args.first_year-1}-10-01', f'{first_calendar}-01-01'),
                          max(f'{args.last_year}-09-30', f'{last_calendar}-12-31'))
    missing = pd.Series(np.nan, index=dates)
    cases = [load_case(Path(csv), Path(report), fpart, dates)
             for csv, report, fpart in (args.baseline, args.alternative)]
    (baseline, base_source), (alternative, alt_source) = cases
    rows = [row for key in sorted(baseline.keys() | alternative.keys())
            for row in annual_rows(key, baseline.get(key, missing), alternative.get(key, missing),
                                   water_years if key[0] == 'Flood Control' else calendar_years)]
    if not rows:
        raise ValueError('No supported metrics found in either report')
    args.output.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(args.output/'annual_csv_comparison.csv', index=False)
    (args.output/'csv_provenance.json').write_text(json.dumps({
        'baseline': base_source, 'alternative': alt_source,
        'timestamp_convention': 'daily interval-end midnight shifted back one day',
        'lookup': 'linear, clamped at endpoints',
        'evacuation_zone_gating': 'unavailable without daily zone boundaries',
    }, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
