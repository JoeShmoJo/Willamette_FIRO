"""Dedicated page for daily and annual water supply storage comparisons."""
from html import escape

import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from purpose_plots import distribution_report, storage_duration_plot


def daily_storage_grid(daily, labels):
    locations = list(daily)
    columns = min(3, len(locations))
    rows = (len(locations) + columns - 1) // columns
    fig = make_subplots(rows=rows, cols=columns,
                        subplot_titles=[escape('System' if site == 'SYSTEM' else site) for site in locations],
                        vertical_spacing=.24 / rows, horizontal_spacing=.10)
    for i, site in enumerate(locations):
        row, col = i // columns + 1, i % columns + 1
        pair = daily[site].dropna()
        for column, name, color in zip(pair, labels, ('#17638a', '#a44721')):
            ranked = pair[column].sort_values(ascending=False, kind='stable')
            exceedance = 100 * np.arange(1, len(ranked)+1) / (len(ranked)+1)
            fig.add_trace(go.Scatter(x=exceedance, y=ranked,
                                     customdata=ranked.index.strftime('%Y-%m-%d'),
                                     name=name, mode='lines', line_color=color,
                                     legendgroup=column, showlegend=i == 0,
                                     hovertemplate='%{customdata}: %{y:,.0f} acre-ft<extra>%{fullData.name}</extra>'),
                          row=row, col=col)
        fig.update_yaxes(title_text='acre-ft', automargin=True, row=row, col=col)
        fig.update_xaxes(title_text='Exceedance (%)', range=[0, 100], ticksuffix='%', row=row, col=col)
    fig.update_layout(template='plotly_white', height=245*rows+75,
                      legend=dict(orientation='h', x=1, xanchor='right', y=1, yanchor='bottom'),
                      margin=dict(t=75, b=52, l=70, r=22))
    return fig


def write_water_supply(output, annual, daily, relative, reference, labels, system_metrics, first, last):
    content = (
        '<!doctype html><html lang="en"><meta charset="utf-8"><title>Water Supply | ResSim</title>'
        '<style>body{font:15px system-ui;margin:2rem;color:#182534}select{font:inherit;max-width:100%;padding:.35rem}</style>'
        '<h1>Water Supply storage comparison</h1>'
        f'<p>Water years {first}–{last}. Baseline: {escape(labels[0])}. Alternative: {escape(labels[1])}.</p>'
        '<p><a href="index.html">Purpose comparison</a> · <a href="#daily-storage">Daily duration plots</a> · '
        '<a href="annual_comparison.csv">Annual and holiday CSV</a></p>'
    )
    if annual.empty:
        content += '<p>The selected runs have no daily pool storage records.</p>'
    else:
        content += (
            '<h2>Annual and holiday storage</h2>'
            '<p>Choose an annual or holiday metric for box plots and duration curves. Annual system peaks '
            'use the highest daily sum across all reservoirs within each complete water year. Memorial Day '
            'and Labor Day each contribute one daily value per year. The system holiday value sums the '
            'reservoirs on that holiday.</p>'
            + distribution_report(annual, labels, system_metrics)
            + '<h2 id="daily-storage">Daily storage duration plots</h2>'
            '<p>Each curve ranks daily modeled storage on dates available in both cases. '
            'The system panel sums the same reservoirs on each day and requires every member.</p>'
            + daily_storage_grid(daily, labels).to_html(full_html=False, include_plotlyjs=False)
        )
    if reference is not None:
        zero, date = reference['zero_acre_ft'], reference['baseline_date']
        season = reference['season']
        window = (f'{season["start"]} through {season["end"]}'
                  if season['type'] == 'fixed' else 'Memorial Day through Labor Day')
        content += (
            '<h2>System storage relative to seasonal minimum</h2>'
            f'<p>Both cases use the same zero of {zero:,.0f} acre-ft, the lowest daily Baseline system '
            f'total across complete paired conservation seasons ({escape(window)}, inclusive). '
            f'It occurred on {date}.</p>'
            '<p><a href="daily_relative_system_storage.csv">Daily relative storage CSV</a></p>'
            + storage_duration_plot(relative, labels).to_html(full_html=False, include_plotlyjs=False)
        )
    (output/'water_supply.html').write_text(content, encoding='utf-8')
