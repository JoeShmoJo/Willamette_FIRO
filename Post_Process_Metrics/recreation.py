"""POR boat-ramp-day metrics using actual pool and the higher RC/FIRO elevation."""
import argparse
import hashlib
import json
import shutil
import tempfile
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from pydsstools.heclib.dss import HecDss

from inspect_por import read_series
from run_evidence import read_run_evidence

ROOT = Path(__file__).resolve().parent


def season_dates(year, season):
    if season['type'] == 'memorial_to_labor':
        end_may = pd.Timestamp(year, 5, 31)
        start = end_may - pd.Timedelta(days=end_may.weekday())
        start_september = pd.Timestamp(year, 9, 1)
        end = start_september + pd.Timedelta(days=(-start_september.weekday()) % 7)
    elif season['type'] == 'fixed':
        start = pd.Timestamp(f'{year}-{season["start"]}')
        end = pd.Timestamp(f'{year}-{season["end"]}')
        if end < start:
            raise ValueError('Recreation seasons must be within one calendar year.')
    else:
        raise ValueError(f'Unknown season: {season}')
    return pd.date_range(start, end, freq='D')


def ramp_available(pool, rule_curve, firo, ramp_elevation, firo_enabled, firo_inactive=None):
    """Nullable 0/1; a missing required input is unknown, not an unavailable ramp.

    FIRO inactivity must be explicitly established by the source configuration.
    """
    if firo_inactive is None:
        firo_inactive = pd.Series(False, index=pool.index)
    enabled = firo_enabled.astype('boolean')
    ceiling = pd.concat([rule_curve, firo.where(enabled.fillna(False))], axis=1).max(axis=1)
    known = (pool.notna() & rule_curve.notna() & enabled.notna()
             & (~enabled.fillna(False) | firo.notna() | firo_inactive))
    return ((pool > ramp_elevation) & (ceiling > ramp_elevation)).astype('Float64').where(known)


def activation_schedule(path, reservoir, dates):
    """Read verified run-specific daily enabled flags; absence is unknown.

    These flags must describe whether the FIRO rule applies, not whether it won
    a tie with another release rule. A zero Flow-SPEC value alone is insufficient.
    """
    table = pd.read_csv(path, dtype={'enabled': 'string'}, parse_dates=['date'])
    if table.duplicated(['date', 'reservoir']).any():
        raise ValueError(f'Duplicate activation rows in {path}')
    raw = table.enabled.str.strip().str.lower()
    if not raw.dropna().isin(['true', 'false', 'unknown']).all():
        raise ValueError('Activation enabled values must be true, false, or unknown')
    table['enabled'] = raw.map({'true': True, 'false': False}).astype('boolean')
    return table[table.reservoir == reservoir].set_index('date').enabled.reindex(dates)


def firo_schedule(path, reservoir, dates):
    table = pd.read_csv(path, comment='#', encoding='utf-8-sig')
    table.columns = table.columns.str.strip()
    if table.duplicated(['Month', 'Day']).any():
        raise ValueError(f'Duplicate dates in {path}')
    table = table.set_index(['Month', 'Day'])
    # Validate a full generic-year schedule. Feb 29 follows the model checker's Feb 28 convention.
    expected = pd.date_range('2001-01-01', '2001-12-31')
    keys = [(day.month, day.day) for day in expected]
    if not set(keys).issubset(set(table.index)):
        raise ValueError(f'Incomplete FIRO schedule in {path}')
    columns = [c for c in table.columns if c.casefold() == reservoir.casefold()]
    if len(columns) > 1:
        raise ValueError(f'Ambiguous FIRO column: {reservoir}')
    if not columns:
        return pd.Series(np.nan, index=dates), pd.Series(True, index=dates)
    source = table[columns[0]]
    numeric = pd.to_numeric(source, errors='raise')
    lookup = [(d.month, 28 if d.month == 2 and d.day == 29 else d.day) for d in dates]
    values = pd.Series(numeric.reindex(lookup).to_numpy(), index=dates)
    return values, values.isna()  # A blank cell explicitly stands down the rule.


def load_reservoirs(path, fpart, reservoirs, dates, report=None):
    results, sources = {}, []
    # Even read-only DSS opens can update bookkeeping, so protect original files.
    with tempfile.TemporaryDirectory(prefix='recreation-dss-') as directory:
        local = Path(directory)/path.name
        shutil.copyfile(path, local)
        with HecDss.Open(local, mode='r') as fid:
            groups = defaultdict(list)
            for pathname in fid.search_path('/*/*/*/*/*/*/', sort=1):
                parts = pathname.split('/')
                if len(parts) == 8:
                    a, b, c, d, e, f = parts[1:7]
                    if e.casefold() == '1day' and f == fpart:
                        groups[(a, b, c)].append(pathname)
            for reservoir in reservoirs:
                values = {}
                for kind, bname, parameter in [('pool', reservoir+'-Pool', 'Elev'),
                                              ('rule_curve', reservoir+'-Rule Curve', 'Elev-ZONE')]:
                    matches = [key for key in groups if key[1].casefold() == bname.casefold()
                               and key[2].casefold() == parameter.casefold()]
                    if len(matches) != 1:
                        raise ValueError(f'Expected one {kind} series for {reservoir}, got {matches}')
                    paths = groups[matches[0]]
                    series, units = read_series(fid, paths)
                    if units.casefold() not in {'ft', 'feet'}:
                        raise ValueError(f'Expected elevation in feet, got {units}')
                    values[kind] = series.reindex(dates)
                    if kind == 'pool':
                        values['previous_pool'] = series.shift(1).reindex(dates)
                    sources.append(dict(reservoir=reservoir, kind=kind, units=units, paths=paths))
                if report is not None:
                    operations = [op for op in report['operations'] if op['reservoir'].casefold() == reservoir.casefold()]
                    if len(operations) != 1:
                        raise ValueError(f'Ambiguous/missing operation stack: {reservoir}')
                    zones = operations[0]['zones']
                    tops = {}
                    for zone in zones[:-1]:
                        bname = reservoir+'-'+zone['zone_name']
                        matches = [key for key in groups if key[1].casefold() == bname.casefold()
                                   and key[2].casefold() == 'elev-zone']
                        if len(matches) != 1:
                            raise ValueError(f'Missing/ambiguous zone elevation: {bname}')
                        series, units = read_series(fid, groups[matches[0]])
                        if units.casefold() not in {'ft', 'feet'}:
                            raise ValueError('Zone elevations must be in feet')
                        tops[zone['zone_name']] = series.reindex(dates)
                        sources.append(dict(reservoir=reservoir, kind='zone_top', zone=zone['zone_name'],
                                            units=units, paths=groups[matches[0]]))
                    zone_name, attached = zone_membership(values['previous_pool'], zones, tops)
                    values['zone'] = zone_name
                    values['firo_attached'] = attached
                results[reservoir] = values
    return results, sources


def zone_membership(previous_pool, zones, tops):
    """Match model_check: previous pool selects the lowest zone containing it."""
    if not zones:
        raise ValueError('Empty zone stack')
    selected = pd.Series(zones[-1]['zone_name'], index=previous_pool.index, dtype='string')
    valid = previous_pool.notna()
    for zone in reversed(zones[:-1]):
        top = tops[zone['zone_name']]
        valid &= top.notna()
        selected[previous_pool <= top] = zone['zone_name']
    present = {zone['zone_name']: any(rule.casefold() == 'firo_space'
                                    or rule.casefold().endswith('-firo_space')
                                    for rule in zone['rules']) for zone in zones}
    attached = selected.map(present).astype('boolean').where(valid)
    return selected.where(valid), attached


def seasonal_rollups(daily):
    records = []
    for (case, year, reservoir, ramp), group in daily.groupby(['case', 'year', 'reservoir', 'ramp_name']):
        valid = int(group.available.notna().sum())
        total = len(group)
        records.append(dict(case=case, year=year, reservoir=reservoir, ramp_name=ramp,
                            expected_ramp_days=total, valid_ramp_days=valid,
                            missing_ramp_days=total-valid,
                            observed_boat_ramp_days=float(group.available.sum()),
                            boat_ramp_days=float(group.available.sum()) if valid == total else np.nan))
    ramp = pd.DataFrame(records)
    def aggregate(keys, system=False):
        rows = []
        for key, group in ramp.groupby(keys):
            row = dict(zip(keys, key))
            if system:
                row['reservoir'] = 'SYSTEM'
            for name in ['expected_ramp_days', 'valid_ramp_days', 'missing_ramp_days', 'observed_boat_ramp_days']:
                row[name] = group[name].sum()
            row['boat_ramp_days'] = group.boat_ramp_days.sum(min_count=len(group))
            rows.append(row)
        return pd.DataFrame(rows)
    totals = pd.concat([aggregate(['case', 'year', 'reservoir']),
                        aggregate(['case', 'year'], system=True)], ignore_index=True)
    return ramp, totals


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT/'recreation_config.json')
    parser.add_argument('--output', type=Path, default=ROOT/'outputs/recreation')
    args = parser.parse_args()
    run(args.config, args.output)


def run(config_path, output):
    config = json.loads(config_path.read_text())
    base = config_path.resolve().parent
    labels = [case['name'] for case in config['cases']]
    if not labels or len(set(labels)) != len(labels):
        raise ValueError('Provide at least one case with unique names; first case is baseline.')
    if config['last_year'] < config['first_year']:
        raise ValueError('last_year is earlier than first_year')
    ramps_path = base/config['ramps']
    ramps = pd.read_csv(ramps_path)
    if ramps.empty or ramps.duplicated(['reservoir', 'ramp_name']).any():
        raise ValueError('Ramp table must be nonempty with unique reservoir/ramp names')
    if not np.isfinite(pd.to_numeric(ramps.elevation_ft, errors='raise')).all():
        raise ValueError('Ramp elevations must be finite')
    years = {year: season_dates(year, config['season'])
             for year in range(config['first_year'], config['last_year']+1)}
    dates = pd.DatetimeIndex([date for window in years.values() for date in window])
    daily, provenance = [], []
    fingerprints = {str(ramps_path): hashlib.sha256(ramps_path.read_bytes()).hexdigest()}
    for case in config['cases']:
        evidence = None
        report_path = base/case['model_report'] if case.get('model_report') else None
        report = json.loads(report_path.read_text()) if report_path else None
        if case.get('run_marker'):
            if report is None:
                raise ValueError('Run-marker activation also requires a model_report for zone membership')
            target, initialization, evidence = read_run_evidence(base/case['run_marker'], case['f_part'])
        elif case.get('firo_activation_csv'):
            target = base/case['firo_table']
        else:
            raise ValueError(f'{case["name"]}: FIRO activation is unverified. Supply a run-specific '
                             'firo_activation_csv (date,reservoir,enabled); the target spreadsheet '
                             'alone does not establish whether FIRO is enabled.')
        path = base/case['dss']
        activation_path = base/case['firo_activation_csv'] if case.get('firo_activation_csv') else None
        for source in [source for source in [path, target, activation_path, report_path] if source is not None]:
            fingerprints[str(source)] = hashlib.sha256(source.read_bytes()).hexdigest()
        results, sources = load_reservoirs(path, case['f_part'], ramps.reservoir.unique(), dates, report)
        provenance.append(dict(case=case['name'], dss=str(path), f_part=case['f_part'],
                               firo_table=str(target), firo_activation_csv=str(activation_path),
                               runtime_evidence=evidence, series=sources))
        for reservoir, ramp_group in ramps.groupby('reservoir'):
            pool = results[reservoir]['pool']
            rc = results[reservoir]['rule_curve']
            firo, inactive = firo_schedule(target, reservoir, dates)
            if evidence is not None:
                attached = results[reservoir]['firo_attached']
                initialized = initialization.get(reservoir, pd.NA)
                enabled = attached & pd.Series(initialized, index=dates, dtype='boolean')
            else:
                enabled = activation_schedule(activation_path, reservoir, dates)
            for ramp in ramp_group.itertuples():
                available = ramp_available(pool, rc, firo, ramp.elevation_ft, enabled, inactive)
                daily.append(pd.DataFrame(dict(date=dates, case=case['name'], year=dates.year,
                                              reservoir=reservoir, ramp_name=ramp.ramp_name,
                                              ramp_elevation_ft=ramp.elevation_ft, pool_elevation_ft=pool.to_numpy(),
                                              rule_curve_elevation_ft=rc.to_numpy(), firo_elevation_ft=firo.to_numpy(),
                                              firo_enabled=enabled.to_numpy(),
                                              operating_zone=results[reservoir].get('zone', pd.Series('', index=dates)).to_numpy(),
                                              firo_no_target=inactive.to_numpy(), available=available.to_numpy())))
    daily = pd.concat(daily, ignore_index=True)
    daily['available'] = pd.to_numeric(daily.available).astype('Float64')
    ramp_totals, totals = seasonal_rollups(daily)
    baseline = totals[totals.case == labels[0]][['year', 'reservoir', 'boat_ramp_days']]
    comparison = totals.merge(baseline.rename(columns={'boat_ramp_days': 'baseline_boat_ramp_days'}),
                              on=['year', 'reservoir'], validate='many_to_one')
    comparison['change_from_baseline'] = comparison.boat_ramp_days-comparison.baseline_boat_ramp_days
    statistics = []
    for (case, reservoir), group in totals.groupby(['case', 'reservoir']):
        values = group.boat_ramp_days.dropna()
        row = dict(case=case, reservoir=reservoir, complete_seasons=len(values),
                   incomplete_seasons=len(group)-len(values))
        row.update({f'p{p}': values.quantile(p/100) for p in [5, 10, 25, 50, 75, 90, 95]})
        statistics.append(row)
    output.mkdir(parents=True, exist_ok=True)
    for name, table in [('daily_ramp_availability', daily), ('seasonal_by_ramp', ramp_totals),
                        ('seasonal_totals', comparison), ('seasonal_percentiles', pd.DataFrame(statistics))]:
        table.to_csv(output/f'{name}.csv', index=False)
    figures = []
    for reservoir in sorted(totals.reservoir.unique()):
        fig = go.Figure()
        for case in labels:
            group = comparison[(comparison.case == case) & (comparison.reservoir == reservoir)]
            fig.add_trace(go.Box(y=group.boat_ramp_days, name=case, boxpoints='all',
                                 text=group.year.astype(str), hovertemplate='%{text}: %{y} ramp days<extra>%{fullData.name}</extra>'))
        fig.update_layout(title=f'{reservoir}: seasonal boat-ramp days', yaxis_title='Boat-ramp days')
        figures.append(fig.to_html(full_html=False, include_plotlyjs=not figures))
        duration, changes = go.Figure(), go.Figure()
        for case in labels:
            group = comparison[(comparison.case == case) & (comparison.reservoir == reservoir)]
            values = np.sort(group.boat_ramp_days.dropna().to_numpy())[::-1]
            duration.add_trace(go.Scatter(x=100*np.arange(1, len(values)+1)/(len(values)+1),
                                         y=values, name=case, mode='lines+markers'))
            if case != labels[0]:
                changes.add_trace(go.Box(y=group.change_from_baseline, name=case, boxpoints='all',
                                         text=group.year.astype(str)))
        duration.update_layout(title=f'{reservoir}: seasonal total exceedance',
                               xaxis_title='Exceedance probability (%)', yaxis_title='Seasonal boat-ramp days')
        figures.append(duration.to_html(full_html=False, include_plotlyjs=False))
        if changes.data:
            changes.update_layout(title=f'{reservoir}: paired change from {labels[0]}',
                                  yaxis_title='Change in boat-ramp days')
            figures.append(changes.to_html(full_html=False, include_plotlyjs=False))
    (output/'box_plots.html').write_text('<!doctype html><meta charset="utf-8"><title>Recreation</title>'
        f'<h1>Seasonal boat-ramp days</h1><p>Years {config["first_year"]}–{config["last_year"]}; '
        f'season: {config["season"]}. Each point is one complete season. System totals sum '
        'ramps before calculating percentiles. Strictly above both thresholds; no flood-zone credit.</p>'
        + '\n'.join(figures), encoding='utf-8')
    (output/'provenance.json').write_text(json.dumps(dict(config=config, sha256=fingerprints, sources=provenance,
        notes=['FIRO tables are supplied model metadata, not a DSS elevation output.',
               'FIRO requires matching initialization receipts and presence in the daily operating-zone stack.',
               'Disabled FIRO, no FIRO column, or a blank target uses the rule curve alone.',
               'Daily interval-end DSS stamps shifted back one day.',
               'Vertical datum agreement between workbook and DSS must be confirmed.']), indent=2), encoding='utf-8')
    print(comparison[comparison.reservoir == 'SYSTEM'].to_string(index=False))
    print(f'Wrote recreation outputs to {output}')
    return comparison


if __name__ == '__main__':
    main()
