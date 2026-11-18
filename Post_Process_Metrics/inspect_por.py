"""Inventory paired POR DSS results and plot daily release/elevation duration curves.

Read-only inputs; no operating-purpose metrics or rule attribution are inferred.
"""
import argparse
import csv
import json
import shutil
import sys
import tempfile
import time
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


def daily_pool(key, parameters):
    _, location, parameter, interval, _ = key
    return (interval.casefold() == '1day' and location.casefold().endswith('-pool')
            and parameter.casefold() in parameters)


def simulation_cases(groups):
    parts = {key[4] for key in groups if daily_pool(key, {'elev'})}
    cases = []
    for label, suffix in [('Baseline', '-0'), ('Alternative', '-1')]:
        matches = sorted(part for part in parts if part.endswith(suffix))
        if len(matches) != 1:
            raise ValueError(f'Expected one daily pool elevation F-part ending in {suffix} for {label}; '
                             f'found {matches}. Available F-parts: {sorted(parts)}. '
                             'Specify the full F-parts explicitly.')
        cases.append((label, matches[0]))
    return cases


def case_catalog(fid):
    groups = defaultdict(list)
    for pathname in fid.search_path('/*/*/*/*/*/*/', sort=1):
        parts = pathname.split('/')
        if len(parts) == 8:
            a, b, c, _, interval, part = parts[1:7]
            groups[a, b, c, interval, part].append(pathname)
    return groups


def copy_snapshot(source, destination):
    for delay in (2, 5, None):
        try:
            shutil.copyfile(source, destination)
            return
        except PermissionError as error:
            if delay is None:
                raise PermissionError(
                    f'Access denied while copying DSS after 3 attempts. Source: {source}. '
                    f'Temporary destination: {destination}. '
                    'If ResSim is computing, wait for it to finish. Close DSSVue or other tools '
                    'using the file, then rerun. If the error persists, check read access to the '
                    'source and write access to the temporary directory.'
                ) from error
            print(f'DSS copy access denied; retrying in {delay} seconds: {source}', file=sys.stderr)
            time.sleep(delay)


def inspect(path, cases, output, include_rule_curves=False):
    # HEC-DSS may update bookkeeping even with mode='r'. Share one copy across cases.
    with tempfile.TemporaryDirectory(prefix='por-dss-') as directory:
        local = Path(directory) / path.name
        copy_snapshot(path, local)
        with HecDss.Open(local, mode='r') as fid:
            groups = case_catalog(fid)
            cases = simulation_cases(groups) if cases is None else cases
            return {label: (fpart, *inspect_case(fid, groups, label, fpart, output, include_rule_curves))
                    for label, fpart in cases}


def inspect_case(fid, groups, label, fpart, output, include_rule_curves=False):
    with (output / f'{label}_catalog.csv').open('w', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(['A', 'B', 'C', 'E', 'F', 'blocks', 'example_path'])
        for key, paths in sorted(groups.items()):
            writer.writerow([*key, len(paths), paths[0]])
    selected = {key: paths for key, paths in groups.items()
                if key[4] == fpart and daily_pool(key, {'elev', 'flow-in', 'flow-out'})}
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
    if include_rule_curves:
        for key, paths in groups.items():
            _, location, parameter, interval, part = key
            if (part == fpart and interval.casefold() == '1day' and parameter.casefold() == 'elev-zone'
                    and location.casefold().endswith('-rule curve')):
                results[key[:3]] = read_series(fid, paths)
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
    inputs = parser.add_mutually_exclusive_group()
    inputs.add_argument('--simulation-dss', type=Path,
                        help='One DSS file with Baseline (-0) and Alternative (-1) F-parts.')
    inputs.add_argument('--case', action='append', nargs=3, metavar=('LABEL', 'DSS', 'F_PART'),
                        help='Repeat for each case; the first case is baseline.')
    parser.add_argument('--output', type=Path, default=ROOT / 'outputs/por_inventory')
    parser.add_argument('--annual-overlays', action='store_true',
                        help='Also plot stacked annual elevation and flow traces with reference lines.')
    parser.add_argument('--firo-targets', type=Path,
                        default=ROOT/'model_metadata/scripts/externalRules/FIRO_SPACEConfig.csv',
                        help='Reference FIRO target schedule for the annual overlays.')
    parser.add_argument('--firo-marker', action='append', nargs=2, default=[], metavar=('CASE', 'JSON'),
                        help='Use a case-specific FIRO configuration marker and initialization receipts.')
    parser.add_argument('--project-data', type=Path,
                        default=ROOT/'model_metadata/scripts/externalSVs/BasicProjectData.csv',
                        help='BasicProjectData CSV with spillway crest elevations for the annual overlays.')
    args = parser.parse_args()
    cases = args.case or [('Baseline', str(ROOT/'data/Baseline.dss'), 'ALL_D-----0'),
                          ('Alternative', str(ROOT/'data/Alternative.dss'), 'ALL_D-----0')]
    labels = [case[0] for case in cases]
    if len(set(labels)) != len(labels) or any(not s.replace('_', '').replace('-', '').isalnum() for s in labels):
        parser.error('Case labels must be unique and contain only letters, numbers, underscores or hyphens.')
    ramps = pd.read_csv(ROOT / 'data/boat_ramp_elevations.csv')
    ramp_reservoirs = ramps.reservoir.str.casefold()
    args.output.mkdir(parents=True, exist_ok=True)
    if args.simulation_dss:
        path = args.simulation_dss.resolve()
        loaded = inspect(path, None, args.output, args.annual_overlays)
        cases = [(label, str(path), entry[0]) for label, entry in loaded.items()]
        labels = list(loaded)
    else:
        loaded = {}
        by_path = defaultdict(list)
        for label, path, fpart in cases:
            by_path[Path(path).resolve()].append((label, fpart))
        for path, file_cases in by_path.items():
            loaded.update(inspect(path, file_cases, args.output, args.annual_overlays))
    all_results = {label: loaded[label][1] for label in labels}
    rows = [row for label in labels for row in loaded[label][2]]
    pd.DataFrame(rows).to_csv(args.output/'coverage.csv', index=False)
    keys = set.union(*(set(result) for result in all_results.values()))
    comparisons, figures, elevation_figures = [], [], []
    baseline = labels[0]
    for key in sorted(keys):
        if not key[1].casefold().endswith('-pool'):
            continue
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
                reservoir = key[1][:-len('-pool')]
                reservoir_ramps = ramps[ramp_reservoirs == reservoir.casefold()]
                add_ramp_lines(fig, reservoir_ramps, curve_units)
                elevation_units = next(iter(curve_units))
                if elevation_units.casefold() == 'feet':
                    elevation_units = 'ft'
                title = reservoir if not reservoir_ramps.empty else f'{reservoir} (no ramp elevations supplied)'
                fig.update_layout(title=title, template='plotly_white',
                                  xaxis=dict(title='Percent of time elevation is equaled or exceeded',
                                             range=[0, 100], ticksuffix='%'),
                                  yaxis_title=f'Pool elevation ({elevation_units})',
                                  legend=dict(orientation='h', y=-0.22))
                elevation_figures.append(fig.to_html(full_html=False, include_plotlyjs=not elevation_figures))
            else:
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
    (args.output/'elevation_duration_plots.html').write_text(
        '<!doctype html><html lang="en"><meta charset="utf-8"><title>Pool elevation duration plots</title>'
        '<style>body{font:16px system-ui;margin:2rem auto;max-width:1100px;padding:0 1rem}'
        '.plotly-graph-div{margin-bottom:2rem}</style>'
        '<h1>Pool elevation duration plots</h1>'
        '<p>Each curve ranks daily simulated pool elevations from highest to lowest over the available period. '
        'At 50%, the elevation is approximately the median. Dashed lines show boat-ramp elevations. '
        'Hover over a ramp line to see how often each case was strictly above it.</p>'
        + '\n'.join(elevation_figures), encoding='utf-8')
    for label, path, fpart in cases:
        print(f'{label}: F={fpart} in {path}')
    print(pd.DataFrame(rows)[['case', 'first_day', 'last_day', 'valid_days', 'missing_days']]
          .drop_duplicates().to_string(index=False))
    print(f'Wrote catalogs, coverage, paired comparisons and duration plots to {args.output}')
    if args.annual_overlays:
        from annual_overlays import write_annual_overlays

        report = args.output/'annual_reservoir_overlays.html'
        markers = {label: Path(path) for label, path in args.firo_marker}
        if len(markers) != len(args.firo_marker) or markers.keys() - all_results.keys():
            parser.error('--firo-marker requires unique case labels that match the DSS cases.')
        write_annual_overlays(report, all_results, ramps, args.firo_targets, args.project_data,
                              markers, {label: fpart for label, _, fpart in cases})
        print(f'Wrote stacked annual reservoir plots to {report}')


if __name__ == '__main__':
    main()
