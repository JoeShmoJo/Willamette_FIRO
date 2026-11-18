"""Inventory paired POR DSS results and plot daily release/elevation duration curves.

Read-only inputs; no operating-purpose metrics or rule attribution are inferred.
"""
import argparse
import csv
import json
import shutil
import tempfile
import warnings
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from pydsstools.heclib.dss import HecDss

ROOT = Path(__file__).resolve().parent


def read_series(fid, paths):
    pieces, units = [], set()
    for path in paths:
        record = fid.read_ts(path, trim_missing=True)
        if record is None or record.times is None or record.values is None:
            continue
        times = [t.datetime() if callable(getattr(t, 'datetime', None)) else t
                 for t in record.times]
        if not times:
            continue
        values = np.asarray(record.values, dtype=float).copy()
        values[values < -1e37] = np.nan
        missing = getattr(record, 'nodata', None)
        if missing is not None:
            values[np.asarray(missing, dtype=bool)] = np.nan
        units.add(str(record.data_units).strip())
        pieces.append(pd.Series(values, index=pd.DatetimeIndex(times)))
    if len(units) > 1:
        raise ValueError(f'Inconsistent units: {units}')
    if not pieces:
        return pd.Series(dtype=float), next(iter(units), '')
    series = pd.concat(pieces).sort_index()
    if series.index.has_duplicates:
        raise ValueError(f'Overlapping date blocks: {paths[0]}')
    if not (series.index == series.index.normalize()).all():
        raise ValueError(f'Expected midnight daily DSS stamps: {paths[0]}')
    # ResSim daily interval-end 24:00 is reported as next-day midnight.
    series.index -= pd.Timedelta(days=1)
    return series, next(iter(units), '')


def inspect(label, path, fpart, output):
    # HEC-DSS may update bookkeeping even with mode='r'. Never open the source.
    with tempfile.TemporaryDirectory(prefix='por-dss-') as directory:
        local = Path(directory) / path.name
        shutil.copyfile(path, local)
        return inspect_copy(label, local, fpart, output)


def inspect_copy(label, path, fpart, output):
    groups = defaultdict(list)
    with HecDss.Open(path, mode='r') as fid:
        for pathname in fid.search_path('/*/*/*/*/*/*/', sort=1):
            parts = pathname.split('/')
            if len(parts) == 8:
                a, b, c, d, e, f = parts[1:7]
                groups[a, b, c, e, f].append(pathname)
        with (output / f'{label}_catalog.csv').open('w', newline='') as stream:
            writer = csv.writer(stream)
            writer.writerow(['A', 'B', 'C', 'E', 'F', 'blocks', 'example_path'])
            for key, paths in sorted(groups.items()):
                writer.writerow([*key, len(paths), paths[0]])
        selected = {key: paths for key, paths in groups.items()
                    if key[4] == fpart and key[3].casefold() == '1day'
                    and key[1].casefold().endswith('-pool')
                    and key[2].casefold() in {'elev', 'flow-in', 'flow-out'}}
        if not selected:
            raise ValueError(f'No daily pool results for {label}, F={fpart}')
        results, rows = {}, []
        for key, paths in sorted(selected.items()):
            series, units = read_series(fid, paths)
            valid = series.dropna()
            expected = (series.index.max() - series.index.min()).days + 1 if len(series) else 0
            rows.append(dict(case=label, A=key[0], location=key[1], parameter=key[2],
                             units=units, first_day=str(series.index.min()) if len(series) else '',
                             last_day=str(series.index.max()) if len(series) else '',
                             expected_days=expected, valid_days=len(valid),
                             missing_days=expected-len(valid),
                             mean=valid.mean(), minimum=valid.min(), maximum=valid.max()))
            results[key[:3]] = (series, units)
    return results, rows


def add_ramp_lines(fig, ramps, units):
    if ramps.empty:
        return
    if any(unit.casefold() not in {'ft', 'feet'} for unit in units):
        warnings.warn(f'Boat-ramp elevations omitted for {ramps.iloc[0].reservoir}: '
                      'DSS elevation units must be feet.', stacklevel=2)
        return
    case_curves = tuple(fig.data)
    # A single line represents all ramps at the same elevation.
    for elevation, same_level in ramps.groupby('elevation_ft', sort=False):
        names = ', '.join(same_level.ramp_name)
        details = [f'{names}<br>Ramp elevation: {elevation:g} ft']
        for curve in case_curves:
            if len(curve.y):
                share = 100 * np.mean(curve.y > elevation)
                details.append(f'{curve.name}: {share:.1f}% of valid days strictly above')
        fig.add_trace(go.Scatter(
            x=[0, 100], y=[elevation, elevation], mode='lines',
            name=f'{names} ({elevation:g} ft)', line=dict(color='#64748b', dash='dash'),
            hovertemplate='<br>'.join(details) + '<extra></extra>',
        ))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', action='append', nargs=3, metavar=('LABEL', 'DSS', 'F_PART'),
                        help='Repeat for each case; first case is baseline.')
    parser.add_argument('--output', type=Path, default=ROOT / 'outputs/por_inventory')
    args = parser.parse_args()
    cases = args.case or [('Baseline', str(ROOT/'data/Baseline.dss'), 'ALL_D-----0'),
                          ('Alternative', str(ROOT/'data/Alternative.dss'), 'ALL_D-----0')]
    labels = [case[0] for case in cases]
    if len(set(labels)) != len(labels) or any(not s.replace('_', '').replace('-', '').isalnum() for s in labels):
        parser.error('Case labels must be unique and contain only letters, numbers, underscores or hyphens.')
    ramps = pd.read_csv(ROOT / 'data/boat_ramp_elevations.csv')
    ramp_reservoirs = ramps.reservoir.str.casefold()
    args.output.mkdir(parents=True, exist_ok=True)
    all_results, rows = {}, []
    for label, path, fpart in cases:
        all_results[label], case_rows = inspect(label, Path(path), fpart, args.output)
        rows.extend(case_rows)
    pd.DataFrame(rows).to_csv(args.output/'coverage.csv', index=False)
    keys = set.union(*(set(result) for result in all_results.values()))
    comparisons, figures = [], []
    baseline = labels[0]
    for key in sorted(keys):
        fig = go.Figure()
        curve_units = set()
        for label, result in all_results.items():
            if key not in result:
                continue
            series, units = result[key]
            if key[2].casefold() in {'elev', 'flow-out'}:
                curve_units.add(units)
                values = np.sort(series.dropna().to_numpy())[::-1]
                fig.add_trace(go.Scatter(x=100*np.arange(1, len(values)+1)/(len(values)+1),
                                        y=values, name=label, mode='lines'))
            if label != baseline and key in all_results[baseline]:
                base, base_units = all_results[baseline][key]
                if units != base_units:
                    raise ValueError(f'Case units differ for {key}')
                paired = pd.concat([base.rename('baseline'), series.rename('alternative')], axis=1).dropna()
                comparisons.append(dict(case=label, location=key[1], parameter=key[2], units=units,
                                        paired_days=len(paired),
                                        mean_paired_change=(paired.alternative-paired.baseline).mean()))
        if fig.data:
            if key[2].casefold() == 'elev':
                reservoir = key[1][:-len('-pool')].casefold()
                add_ramp_lines(fig, ramps[ramp_reservoirs == reservoir], curve_units)
            fig.update_layout(title=f'{key[1]}: {key[2]} — available daily values',
                              xaxis_title='Exceedance probability (%)', yaxis_title=units)
            figures.append(fig.to_html(full_html=False, include_plotlyjs=True if not figures else False))
    pd.DataFrame(comparisons).to_csv(args.output/'paired_daily_comparison.csv', index=False)
    (args.output/'duration_plots.html').write_text(
        '<!doctype html><meta charset="utf-8"><title>POR duration plots</title>'
        '<h1>Daily duration plots</h1><p>Each curve uses its available daily values; '
        'check coverage.csv before comparing unequal periods.</p>'
        '<p>Dashed lines mark boat-ramp elevations. Hover over a line to see the share '
        'of valid days each case was strictly above it. This comparison uses actual '
        'pool elevation across the full period and excludes recreation-season and '
        'operating-rule criteria.</p>'
        + '\n'.join(figures), encoding='utf-8')
    (args.output/'inputs.json').write_text(json.dumps(cases, indent=2), encoding='utf-8')
    print(pd.DataFrame(rows)[['case', 'first_day', 'last_day', 'valid_days', 'missing_days']]
          .drop_duplicates().to_string(index=False))
    print(f'Wrote catalogs, coverage, paired comparisons and duration plots to {args.output}')


if __name__ == '__main__':
    main()
