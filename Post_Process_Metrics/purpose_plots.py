"""Interactive annual and seasonal comparisons for the purpose report."""
from html import escape

import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots


def distribution_plot(summary, labels):
    fig = make_subplots(rows=2, cols=2, specs=[[{}, {}], [{'colspan': 2}, None]],
                        subplot_titles=('Distribution', 'Duration', 'Paired change by year'),
                        vertical_spacing=.18, horizontal_spacing=.13)
    groups = list(summary.groupby(['purpose', 'location', 'metric'], sort=False))
    groups.sort(key=lambda item: (item[0][1] != 'SYSTEM', *item[0]))
    buttons = []
    colors = ('#17638a', '#a44721')
    for (purpose, location, metric), table in groups:
        table = table.sort_values('year')
        paired = table.dropna(subset=['baseline', 'alternative'])
        units = table['units'].iloc[0]
        start = len(fig.data)
        for column, label, color in zip(('baseline', 'alternative'), labels, colors):
            fig.add_trace(go.Box(name=label, y=paired[column], text=paired.year, boxpoints='all',
                                 jitter=.25, marker_color=color, legendgroup=column,
                                 hovertemplate='%{text}: %{y:,.2f}<extra>%{fullData.name}</extra>'),
                          row=1, col=1)
            ranked = paired.sort_values(column, ascending=False, kind='stable')
            exceedance = 100 * np.arange(1, len(ranked) + 1) / (len(ranked) + 1)
            fig.add_trace(go.Scatter(name=label, x=exceedance, y=ranked[column], text=ranked.year,
                                     mode='lines+markers', line_color=color, legendgroup=column,
                                     showlegend=False,
                                     hovertemplate='%{text}: %{y:,.2f} at %{x:.1f}%<extra>%{fullData.name}</extra>'),
                          row=1, col=2)
        fig.add_trace(go.Bar(x=table.year, y=table.change, name='Change', showlegend=False,
                             marker_color='#526779',
                             hovertemplate='%{x}: %{y:+,.2f}<extra>Change</extra>'),
                      row=2, col=1)

        title = f'{location} · {metric}'
        status = table['status'].iloc[0]
        paired_count = f'{len(paired)} of {len(table)} complete paired periods'
        metric_title = f'{escape(title)}<br><sup>{escape(status)} · {paired_count}</sup>'
        buttons.append(dict(label=escape(f'{purpose} / {title}'), method='update',
                            args=[{}, {'title.text': metric_title,
                                       'yaxis.title.text': units, 'yaxis.autorange': True,
                                       'yaxis2.title.text': units, 'yaxis2.autorange': True,
                                       'yaxis3.title.text': f'Change ({units})', 'yaxis3.autorange': True}],
                            traces=slice(start, len(fig.data))))

    for i, button in enumerate(buttons):
        selected = button.pop('traces')
        button['args'][0]['visible'] = [j in range(selected.start, selected.stop)
                                       for j in range(len(fig.data))]
        if i == 0:
            for trace, visible in zip(fig.data, button['args'][0]['visible']):
                trace.visible = visible
            fig.update_layout(button['args'][1])

    fig.update_xaxes(title_text='Exceedance plotting position (%)', range=[0, 100],
                     ticksuffix='%', row=1, col=2)
    fig.update_xaxes(title_text='Water year or recreation season year', tickformat='d', row=2, col=1)
    fig.update_yaxes(zeroline=True, zerolinewidth=1, zerolinecolor='#364754', row=2, col=1)
    fig.update_layout(template='plotly_white', height=760, margin=dict(t=150),
                      legend=dict(orientation='h', y=1.07),
                      updatemenus=[dict(buttons=buttons, x=0, xanchor='left', y=1.20, yanchor='bottom')])
    return fig
