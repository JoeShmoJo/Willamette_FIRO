"""Daily water supply storage charts for the purpose report."""
from html import escape

import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from purpose_plots import storage_duration_plot


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


def water_supply_panel(daily, relative, reference, labels):
    content = '<h2>Daily storage duration plots</h2>'
    if not daily:
        return content + '<p>The selected runs have no daily pool storage records.</p>'
    content += (
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
    return content
