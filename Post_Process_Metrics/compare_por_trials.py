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

from run_csv_por_plots import build, metric_groups, metric_heading, write_csv_overlays, write_model_settings


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


def distribution_charts(samples, labels, purpose, period, units, *, daily=False, bankfull=None):
    available = samples.loc[:, samples.notna().any()]
    common = available.dropna().index if 0 in available else []
    fig = go.Figure()
    duration = go.Figure()
    stats = []
    for index, (trial, label) in enumerate(labels.items()):
        values = samples.loc[common, trial].dropna()
        if values.empty:
            stats.append([label, 0] + [None] * 6)
            continue
        q1, median, q3 = values.quantile([.25, .5, .75])
        minimum, maximum = values.min(), values.max()
        mean = values.mean()
        stats.append([label, len(values), minimum, q1, median, q3, maximum, mean])
        color = qualitative.Plotly[index % len(qualitative.Plotly)]
        fig.add_trace(go.Box(x=[label], q1=[q1], median=[median], q3=[q3], lowerfence=[minimum],
                             upperfence=[maximum], name=label, marker_color=color,
                             legendgroup=label, mean=[mean], boxmean=True, boxpoints=False, hoverinfo='skip'))
        if not daily:
            fig.add_trace(go.Scatter(x=[label] * len(values), y=values.tolist(), text=values.index.tolist(),
                                     name=label, marker=dict(color=color, opacity=.6, size=5),
                                     mode='markers', legendgroup=label, showlegend=False,
                                     hovertemplate=period.title() + ' %{text}: %{y:,.2f}<extra>%{fullData.name}</extra>'))
        ranked = values.sort_values(ascending=False, kind='stable')
        size = len(ranked)
        positions = range(size)
        max_points = 1200
        if daily and size > max_points:
            # Keep the endpoints and sample exact ranks from the full daily series.
            positions = [i * (size - 1) // (max_points - 1) for i in range(max_points)]
        plotted = ranked.iloc[positions]
        exceedance = [100 * (i + 1) / (size + 1) for i in positions]
        date_labels = plotted.index.strftime('%Y-%m-%d').tolist() if daily else plotted.index.tolist()
        duration.add_trace(go.Scatter(
            x=exceedance, y=plotted.tolist(), text=date_labels, name=label,
            mode='lines' if daily and size > 1 else 'lines+markers', line_color=color, marker=dict(size=5),
            hovertemplate=('Date' if daily else period.title())
            + ' %{text}: %{y:,.2f} at %{x:.2f}%<extra>%{fullData.name}</extra>'))

    for chart in (fig, duration):
        chart.update_layout(template='plotly_white', yaxis_title=units,
                            legend=dict(groupclick='togglegroup', orientation='h', y=-.25),
                            height=390, margin=dict(t=12, b=100))
        if purpose == 'Flood Control' and units in ('days', 'reservoir-days'):
            chart.update_yaxes(rangemode='tozero')
    fig.update_xaxes(tickangle=-35 if len(labels) > 4 else 0, automargin=True)
    duration.update_xaxes(title_text='Exceedance (%)', range=[0, 100], ticksuffix='%')
    if bankfull:
        distinct = {}
        for label, (value, _) in bankfull.items():
            distinct.setdefault(value, []).append(label)
        for value, runs in distinct.items():
            name = 'Bankfull' if len(distinct) == 1 else 'Bankfull · ' + ', '.join(runs)
            duration.add_trace(go.Scatter(
                x=[0, 100], y=[value, value], mode='lines', name=f'{name} ({value:,.0f} cfs)',
                line=dict(color='#4b5563', dash='dash'),
                hovertemplate='%{fullData.name}<extra></extra>'))
    table = pd.DataFrame(stats, columns=['Run', 'Days' if daily else 'Years', 'Minimum', '25th percentile',
                                         '50th percentile', '75th percentile', 'Maximum', 'Mean'])
    body = fig.to_html(full_html=False, include_plotlyjs=False)
    body += '<details open><summary>Box plot statistics</summary>' + table.to_html(index=False, na_rep='—', float_format=lambda value: f'{value:,.2f}') + '</details>'
    curve = duration.to_html(full_html=False, include_plotlyjs=False)
    prefix = 'daily-' if daily else ''
    return (f'<div data-view="{prefix}box"{" hidden" if daily else ""}>{body}</div>'
            f'<div data-view="{prefix}duration" hidden>{curve}</div>')


def location_panel(rows, labels, purpose, period, location, units, daily_flows, bankfull):
    samples = rows.pivot(index='year', columns='trial', values='alternative').reindex(columns=list(labels)[1:])
    baseline = rows.groupby('year').baseline.first()
    samples.insert(0, 0, baseline)
    title = 'System' if location == 'SYSTEM' else escape(location)
    criterion = f'<p>{escape(rows.status.iloc[0])}</p>' if purpose == 'Reservoir elevation' else ''
    thresholds = {labels[trial]: bankfull[trial][location] for trial in labels} if daily_flows and bankfull else None
    charts = distribution_charts(samples, labels, purpose, period, units, bankfull=thresholds)
    if daily_flows:
        samples = pd.DataFrame({trial: daily_flows[trial][location] for trial in labels})
        charts += distribution_charts(samples, labels, purpose, period, units, daily=True, bankfull=thresholds)
    return f'<article><h3>{title}</h3>{criterion}{charts}</article>'


def comparison_panels(summary, labels, daily_flows=None, bankfull=None):
    options, panels = [], []
    width = min(780, max(340, 160 + 52 * len(labels)))
    for i, ((purpose, metric, period), rows) in enumerate(metric_groups(summary)):
        title, heading = metric_heading(purpose, metric, period)
        daily = daily_flows if (purpose, metric) == ('Flood Control', 'Peak daily routed flow') else None
        daily_flag = ' data-daily="true"' if daily else ''
        if daily:
            title = 'Flood Control / Routed flow at control points'
            heading = (f'<div data-annual-heading>{heading}</div>'
                       '<div data-daily-heading hidden><h2 style="font-size:1.8rem;margin-bottom:.25em">'
                       'Daily routed flow at control points</h2>'
                       '<p>Daily views use individual days shared by the included runs. '
                       'For long records, duration plots display up to 1,200 ranked points per run. '
                       'Box statistics use every matched day.</p></div>')
        options.append(f'<option value="{i}"{daily_flag}>{title}</option>')
        locations = list(rows.groupby(['location', 'units']))
        locations.sort(key=lambda item: (item[0][0] != 'SYSTEM', item[0]))
        body = ''.join(location_panel(group, labels, purpose, period, location, units, daily, bankfull)
                       for (location, units), group in locations)
        charts = (f'<div class="reservoir-grid" style="--panel-width:{width}px">{body}</div>'
                  if body else '<p>No comparison data are available.</p>')
        panels.append(f'<section id="metric-{i}"{" hidden" if i else ""}>{heading}{charts}</section>')
    return ('<script src="plotly.min.js"></script><style>'
            '.reservoir-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,var(--panel-width)),1fr));'
            'gap:16px;align-items:start}.reservoir-grid article{min-width:0;border:1px solid #ddd;padding:8px;'
            'overflow-x:auto}.reservoir-grid h3{margin:4px 0;font-size:1.1rem}'
            'table{border-collapse:collapse}td,th{padding:.35em}</style>'
            '<p>Annual plots use complete years shared by the trials with data for each location. '
            'Click a trial in a legend to hide or show it.</p>'
            '<label for="metric">Metric</label> <select id="metric">' + ''.join(options)
            + '</select> <label for="plot-view">View</label> <select id="plot-view">'
              '<option value="box">Box plots and statistics</option>'
              '<option value="duration">Duration plots</option>'
              '<option value="daily-box" hidden disabled>Daily box plots and statistics</option>'
              '<option value="daily-duration" hidden disabled>Daily duration plots</option></select>' + ''.join(panels)
            + '<script>const metric=document.querySelector("#metric"),view=document.querySelector("#plot-view");'
              'function updatePlots(){const daily=metric.selectedOptions[0].dataset.daily==="true";'
              'if(!daily&&view.value.startsWith("daily-"))view.value=view.value.slice(6);'
              'view.querySelectorAll("option[value^=daily-]").forEach(option=>option.hidden=option.disabled=!daily);'
              'const dailyView=view.value.startsWith("daily-");'
              'document.querySelectorAll("[data-daily-heading]").forEach(heading=>heading.hidden=!dailyView);'
              'document.querySelectorAll("[data-annual-heading]").forEach(heading=>heading.hidden=dailyView);'
              'document.querySelectorAll("section").forEach(section=>'
              'section.hidden=section.id!=="metric-"+metric.value);'
              'document.querySelectorAll("[data-view]").forEach(panel=>panel.hidden=panel.dataset.view!==view.value);'
              'document.querySelectorAll("section:not([hidden]) [data-view]:not([hidden]) .js-plotly-plot")'
              '.forEach(plot=>Plotly.Plots.resize(plot))}metric.onchange=view.onchange=updatePlots;updatePlots();</script>')


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
    labels = {0: 'Baseline'}
    configurations = {0: baseline_name}
    links, summaries = [], []
    overlay_records, overlay_targets, settings_models, daily_flows, bankfull = {}, {}, {}, {}, {}
    for trial, (case, name) in cases.items():
        print(f'{case[2]} | {name} | {Path(case[1]).name} | {Path(case[0]).name}', flush=True)
        prior = staging / f'trial{trial}'
        subprocess.run([sys.executable, str(Path(__file__).with_name('compare_por_csv.py')),
                        '--baseline', *baseline, '--alternative', *case,
                        '--first-year', str(water_years.min()), '--last-year', str(water_years.max()),
                        '--calendar-first-year', str(days.year.min()), '--calendar-last-year', str(days.year.max()),
                        '--output', str(prior)], check=True)
        pair = output / f'trial{trial}'
        records, targets, models, control_point_flows, pair_bankfull = build(
            prior, pair, args.targets, stacked_url='../annual_reservoir_overlays.html',
            settings_url=f'../model_settings.html#trial-{trial}')
        label = f'Trial {trial}'
        daily_flows.setdefault(0, control_point_flows['Baseline'])
        daily_flows[trial] = control_point_flows['Alternative']
        bankfull.setdefault(0, pair_bankfull['Baseline'])
        bankfull[trial] = pair_bankfull['Alternative']
        settings_models.setdefault('Baseline', models['Baseline'])
        settings_models[label] = models['Alternative']
        overlay_records.setdefault('Baseline', records['Baseline'])
        overlay_records[label] = records['Alternative']
        if 'Baseline' in targets:
            overlay_targets.setdefault('Baseline', targets['Baseline'])
        if 'Alternative' in targets:
            overlay_targets[label] = targets['Alternative']
        summaries.append(pd.read_csv(pair / 'annual_comparison.csv').assign(trial=trial))
        labels[trial] = f'Trial {trial}'
        configurations[trial] = name
        links.append(f'<li><a href="trial{trial}/index.html">{labels[trial]} versus baseline</a></li>')

    summary = pd.concat(summaries, ignore_index=True)
    summary.to_csv(output / 'annual_comparison.csv', index=False)
    (output / 'plotly.min.js').write_text(get_plotlyjs(), encoding='utf-8')
    configuration_list = '<h2>Configurations</h2><ul>' + ''.join(
        f'<li><strong>{label}</strong> — {escape(configurations[trial])}</li>'
        for trial, label in labels.items()) + '</ul>'
    write_csv_overlays(output/'annual_reservoir_overlays.html', overlay_records, overlay_targets, settings_models['Baseline'], args.targets,
                       trial_controls=True)
    write_model_settings(output/'model_settings.html', settings_models)
    stacked_link = ('<p><a href="annual_reservoir_overlays.html" target="_blank" rel="noopener">'
                    'Stacked reservoir plots for all trials (new tab)</a></p>')
    if skipped:
        print('Excluded results: ' + '; '.join(skipped), flush=True)
    excluded = ('<h2>Excluded results</h2><ul>' + ''.join(f'<li>{escape(reason)}</li>' for reason in skipped)
                + '</ul>') if skipped else ''
    page = output / 'index.html'
    page.write_text('<!doctype html><meta charset="utf-8"><title>POR trial comparison</title>'
                    '<h1>POR trial comparison</h1>' + configuration_list
                    + stacked_link + '<p><a href="model_settings.html" target="_blank" rel="noopener">'
                    'Configuration comparison (new tab)</a> | <a href="annual_comparison.csv">Annual comparison data</a></p>'
                    '<p>Flood metrics use water years. Other metrics use calendar years. System maximum storage is the calendar-year maximum of the daily sum of storage above Min Con across reservoirs. '
                    'Holiday storage and ramp counts use the holiday date only.</p>'
                    '<p>Elevation criteria use Lookout Point and Detroit spillway crests and Cougar’s 1,571 ft threshold.</p>'
                    '<details><summary>Individual trial reports and duration plots</summary><ul>'
                    + ''.join(links) + '</ul></details>' + excluded
                    + comparison_panels(summary, labels, daily_flows, bankfull), encoding='utf-8')
    print(page)


if __name__ == '__main__':
    main()
