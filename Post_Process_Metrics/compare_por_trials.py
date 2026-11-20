"""Compare configured ALL_D POR trials against trial 0."""
import argparse
from datetime import datetime
from html import escape
import json
from pathlib import Path
import re
import subprocess
import sys
from uuid import uuid4

import pandas as pd
import plotly.graph_objects as go
from plotly.offline import get_plotlyjs
from plotly.colors import qualitative

from run_csv_por_plots import build, write_compliance_pages


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


def trial_numbers(run):
    queue = run / 'standalone-trial-configurations.json'
    if queue.is_file():
        assignments = json.loads(queue.read_text(encoding='utf-8-sig'))['assignments']
        return sorted({int(match[1]) for fpart in assignments
                       if (match := re.fullmatch(r'ALL_D-----(\d+)', fpart)) and int(match[1]) > 0})
    return sorted({int(match[1]) for path in run.glob('ALL_D_trial*.csv.gz')
                   if (match := re.fullmatch(r'ALL_D_trial(\d+)\.csv\.gz', path.name)) and int(match[1]) > 0})


def timestamps(case):
    index = pd.DatetimeIndex(pd.to_datetime(pd.read_csv(case[0], usecols=['Timestamp'])['Timestamp']))
    if index.empty or index.hasnans or index.has_duplicates or not index.equals(index.normalize()):
        raise ValueError(f'{case[0]}: expected nonempty, unique daily midnight timestamps')
    return index


def comparison_panels(summary, labels):
    options, panels = [], []
    for i, ((purpose, metric, location, units), rows) in enumerate(
            summary.groupby(['purpose', 'metric', 'location', 'units'])):
        title = escape(f'{purpose} / {metric} / {location}')
        options.append(f'<option value="{i}">{title}</option>')
        samples = rows.pivot(index='year', columns='trial', values='alternative').reindex(columns=list(labels)[1:])
        baseline = rows.groupby('year').baseline.first()
        samples.insert(0, 0, baseline)
        available = samples.loc[:, samples.notna().any()]
        common = available.dropna().index if 0 in available else []
        fig = go.Figure()
        stats = []
        for trial, label in labels.items():
            values = samples.loc[common, trial].dropna()
            if values.empty:
                stats.append([label, 0] + [None] * 7)
                continue
            q1, median, q3 = values.quantile([.25, .5, .75])
            iqr = q3 - q1
            lower = values[values >= q1 - 1.5 * iqr].min()
            upper = values[values <= q3 + 1.5 * iqr].max()
            stats.append([label, len(values), values.min(), lower, q1, median, q3, upper, values.max()])
            color = qualitative.Plotly[list(labels).index(trial) % len(qualitative.Plotly)]
            tag = f'Trial {trial}' if trial else 'Baseline (-0)'
            fig.add_trace(go.Box(x=[tag], q1=[q1], median=[median], q3=[q3], lowerfence=[lower],
                                 upperfence=[upper], name=label, marker_color=color,
                                 legendgroup=tag, boxpoints=False))
            fig.add_trace(go.Scatter(x=[tag] * len(values), y=values.tolist(), text=values.index.tolist(),
                                     name=label, marker=dict(color=color, opacity=.6, size=5),
                                     mode='markers', legendgroup=tag, showlegend=False,
                                     hovertemplate='WY %{text}: %{y:,.2f}<extra>%{fullData.name}</extra>'))
        fig.update_layout(template='plotly_white', yaxis_title=units,
                          legend=dict(groupclick='togglegroup'), height=385, margin=dict(t=20))
        if purpose == 'Flood Control' and units in ('days', 'reservoir-days'):
            fig.update_yaxes(rangemode='tozero')
        table = pd.DataFrame(stats, columns=['Run', 'Years', 'Minimum', 'Lower whisker', 'Q1',
                                             'Median', 'Q3', 'Upper whisker', 'Maximum'])
        body = fig.to_html(full_html=False, include_plotlyjs=False)
        body += table.to_html(index=False, na_rep='—', float_format=lambda value: f'{value:,.2f}')
        panels.append(f'<section id="metric-{i}"{" hidden" if i else ""}>{body}</section>')
    return ('<script src="plotly.min.js"></script><style>table{border-collapse:collapse}td,th{padding:.35em}</style>'
            '<p>Boxes and points use complete years shared by the trials with data for this metric. '
            'Trials with zero years have no box. Points represent individual water years. '
            'Click a trial in the legend to hide or show it.</p>'
            '<label for="metric">Metric and location</label> <select id="metric">' + ''.join(options)
            + '</select>' + ''.join(panels)
            + '<script>document.querySelector("#metric").onchange=e=>{document.querySelectorAll("section")'
              '.forEach(s=>s.hidden=s.id!=="metric-"+e.target.value);document.querySelectorAll('
              '"section:not([hidden]) .js-plotly-plot").forEach(p=>Plotly.Plots.resize(p))}</script>')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run_folder', type=Path)
    parser.add_argument('--targets', required=True, type=Path)
    args = parser.parse_args()
    run = args.run_folder.resolve()
    baseline, baseline_name = select_case(run, 0)
    dates = timestamps(baseline)
    days = dates - pd.Timedelta(days=1)
    water_years = days.year + (days.month >= 10).astype(int)
    cases, skipped = {}, []
    for trial in trial_numbers(run):
        try:
            case, name = select_case(run, trial)
            if not dates.equals(timestamps(case)):
                raise ValueError('CSV timestamps differ from trial 0')
        except (ValueError, KeyError, OSError) as error:
            skipped.append(f'Trial {trial}: {error}')
            continue
        cases[trial] = (case, name)
    if not cases:
        raise ValueError('No alternatives with a matching CSV and compute report. ' + ' '.join(skipped))

    output = run / 'por_csv_plots' / (datetime.now().strftime('%Y%m%d-%H%M%S-') + uuid4().hex[:8])
    staging = output / 'csv_metrics'
    labels = {0: f'Baseline (-0): {baseline_name}'}
    links, summaries = [], []
    for trial, (case, name) in cases.items():
        print(f'{case[2]} | {name} | {Path(case[1]).name} | {Path(case[0]).name}', flush=True)
        prior = staging / f'trial{trial}'
        subprocess.run([sys.executable, str(Path(__file__).with_name('compare_por_csv.py')),
                        '--baseline', *baseline, '--alternative', *case,
                        '--first-year', str(water_years.min()), '--last-year', str(water_years.max()),
                        '--output', str(prior)], check=True)
        pair = output / f'trial{trial}'
        build(prior, pair, args.targets)
        summaries.append(pd.read_csv(pair / 'annual_comparison.csv').assign(trial=trial))
        labels[trial] = f'Trial {trial}: {name}'
        links.append(f'<li><a href="trial{trial}/index.html">{escape(labels[trial])} versus baseline</a></li>')

    summary = pd.concat(summaries, ignore_index=True)
    summary.to_csv(output / 'annual_comparison.csv', index=False)
    (output / 'plotly.min.js').write_text(get_plotlyjs(), encoding='utf-8')
    compliance = write_compliance_pages(output, summary, lambda table: comparison_panels(table, labels))
    if skipped:
        print('Excluded results: ' + '; '.join(skipped), flush=True)
    excluded = ('<h2>Excluded results</h2><ul>' + ''.join(f'<li>{escape(reason)}</li>' for reason in skipped)
                + '</ul>') if skipped else ''
    page = output / 'index.html'
    page.write_text('<!doctype html><meta charset="utf-8"><title>POR trial comparison</title>'
                    '<h1>POR trial comparison</h1><p>' + escape(labels[0]) + '</p>'
                    + compliance + '<p><a href="annual_comparison.csv">Annual comparison data</a></p>'
                    '<p>System maximum storage is the water-year maximum of the daily sum across reservoirs. '
                    'Holiday storage and ramp counts use the holiday date only.</p>'
                    '<details><summary>Individual trial reports, duration plots and model settings</summary><ul>'
                    + ''.join(links) + '</ul></details>' + excluded
                    + comparison_panels(summary, labels), encoding='utf-8')
    print(page)


if __name__ == '__main__':
    main()
