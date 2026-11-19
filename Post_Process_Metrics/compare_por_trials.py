"""Run the existing CSV plots for trials 1 and 2 versus trial 0."""
import argparse
from datetime import datetime
from html import escape
import json
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

import pandas as pd

from run_csv_por_plots import build


def select_case(run, trial):
    fpart = f'ALL_D-----{trial}'
    csv = run / ('ALL_D.csv.gz' if trial == 0 else f'ALL_D_trial{trial}.csv.gz')
    if not csv.is_file():
        raise ValueError(f'Missing trial {trial} CSV: {csv}')
    candidates = sorted((run / 'modelReports').glob(f'{fpart}_*.json'),
                        key=lambda path: path.stat().st_mtime_ns, reverse=True)
    if not candidates:
        raise ValueError(f'Missing per-compute report for {fpart}')
    report = candidates[0]
    if abs(report.stat().st_mtime - csv.stat().st_mtime) > 120:
        raise ValueError(f'{fpart}: latest report and CSV were written more than two minutes apart. '
                         f'Check that both files came from the same compute: {report.name}, {csv.name}')
    compute = json.loads(report.read_text(encoding='utf-8-sig'))['compute']
    if compute['output_fpart'] != fpart or report.stem != f'{fpart}_{compute["compute_id"]}':
        raise ValueError(f'{report}: compute identity differs from the report filename')
    configuration = compute.get('baseline_configuration') or {}
    pointer = configuration.get('pointer') or {}
    if pointer.get('assigned_fpart') not in (None, fpart):
        raise ValueError(f'{report}: configuration was assigned to a different trial')
    name = (configuration.get('resolved') or {}).get('name') or pointer.get('name') or 'No configuration captured'
    return (str(csv), str(report), fpart), name


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run_folder', type=Path)
    parser.add_argument('--targets', required=True, type=Path)
    args = parser.parse_args()
    run = args.run_folder.resolve()
    cases = [select_case(run, trial) for trial in range(3)]
    dates = [pd.DatetimeIndex(pd.to_datetime(pd.read_csv(case[0], usecols=['Timestamp'])['Timestamp']))
             for case, _ in cases]
    if any(not dates[0].equals(index) for index in dates[1:]):
        raise ValueError('The three CSV exports have different daily timestamps')
    days = dates[0] - pd.Timedelta(days=1)
    water_years = days.year + (days.month >= 10).astype(int)
    output = run / 'por_csv_plots' / (datetime.now().strftime('%Y%m%d-%H%M%S-') + uuid4().hex[:8])
    staging = output / 'csv_metrics'
    rows = []
    for position, (case, name) in enumerate(cases):
        print(f'{case[2]} | {name} | {Path(case[1]).name} | {Path(case[0]).name}', flush=True)
        if position == 0:
            continue
        prior = staging / f'trial{position}'
        subprocess.run([sys.executable, str(Path(__file__).with_name('compare_por_csv.py')),
                        '--baseline', *cases[0][0], '--alternative', *case,
                        '--first-year', str(water_years.min()), '--last-year', str(water_years.max()),
                        '--output', str(prior)], check=True)
        build(prior, output / f'trial{position}', args.targets)
        rows.append(f'<li><a href="trial{position}/index.html">Trial {position} ({escape(name)}) versus trial 0</a></li>')
    page = output / 'index.html'
    page.write_text('<!doctype html><meta charset="utf-8"><title>POR trial comparison</title>'
                    '<h1>POR trial comparison</h1><p>Trial 0 baseline: '
                    + escape(cases[0][1]) + '</p><ul>' + ''.join(rows) + '</ul>', encoding='utf-8')
    print(page)


if __name__ == '__main__':
    main()
