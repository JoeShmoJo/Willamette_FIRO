"""Interactive annual and seasonal comparisons for the purpose report."""
from html import escape

import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots


def storage_duration_plot(storage, labels):
    fig = go.Figure()
    paired = storage.dropna()
    for column, label, color in zip(paired, labels, ('#17638a', '#a44721')):
        ranked = paired[column].sort_values(ascending=False, kind='stable')
        exceedance = 100 * np.arange(1, len(ranked) + 1) / (len(ranked) + 1)
        fig.add_trace(go.Scatter(x=exceedance, y=ranked, customdata=ranked.index.strftime('%Y-%m-%d'),
                                 name=label, mode='lines', line_color=color,
                                 hovertemplate='%{customdata}: %{y:,.0f} acre-ft at %{x:.2f}%'
                                               '<extra>%{fullData.name}</extra>'))
    fig.add_hline(y=0, line_dash='dash', line_color='#64748b')
    fig.update_layout(template='plotly_white', height=460,
                      title=f'Daily system storage relative to seasonal minimum · {len(paired):,} paired days',
                      xaxis=dict(title='Exceedance plotting position (%)', range=[0, 100], ticksuffix='%'),
                      yaxis_title='Storage relative to zero (acre-ft)')
    return fig


def stacked_distribution_plot(table, labels):
    locations = sorted(table.location.unique(), key=lambda location: (location != 'SYSTEM', location))
    titles = []
    for location in locations:
        rows = table[table.location == location]
        complete = rows[['baseline', 'alternative']].notna().all(axis=1).sum()
        name = 'System' if location == 'SYSTEM' else escape(location)
        titles.extend((f'{name}: box plot<br><sup>{complete} of {len(rows)} paired periods</sup>',
                       'Duration', 'Paired change by year'))
    fig = make_subplots(rows=len(locations), cols=3, subplot_titles=titles,
                        vertical_spacing=.32 / len(locations), horizontal_spacing=.09,
                        column_widths=[.27, .36, .37])
    colors = ('#17638a', '#a44721')
    for row, location in enumerate(locations, start=1):
        samples = table[table.location == location].sort_values('year')
        paired = samples.dropna(subset=['baseline', 'alternative'])
        units = samples['units'].iloc[0]
        for column, label, color in zip(('baseline', 'alternative'), labels, colors):
            fig.add_trace(go.Box(name=label, y=paired[column], text=paired.year, boxpoints='all',
                                 jitter=.25, marker_color=color, legendgroup=column,
                                 showlegend=row == 1,
                                 hovertemplate='%{text}: %{y:,.2f}<extra>%{fullData.name}</extra>'),
                          row=row, col=1)
            ranked = paired.sort_values(column, ascending=False, kind='stable')
            exceedance = 100 * np.arange(1, len(ranked) + 1) / (len(ranked) + 1)
            fig.add_trace(go.Scatter(name=label, x=exceedance, y=ranked[column], text=ranked.year,
                                     mode='lines+markers', line_color=color, legendgroup=column,
                                     showlegend=False,
                                     hovertemplate='%{text}: %{y:,.2f} at %{x:.1f}%<extra>%{fullData.name}</extra>'),
                          row=row, col=2)
        fig.add_trace(go.Bar(x=samples.year, y=samples.change, name='Change', showlegend=False,
                             marker_color='#526779',
                             hovertemplate='%{x}: %{y:+,.2f}<extra>Change</extra>'),
                      row=row, col=3)
        fig.update_xaxes(title_text='Exceedance (%)', range=[0, 100], ticksuffix='%', row=row, col=2)
        fig.update_xaxes(title_text='Year', tickformat='d', row=row, col=3)
        fig.update_yaxes(title_text=units, row=row, col=1)
        fig.update_yaxes(title_text=units, matches=f'y{3*row-2}' if row > 1 else 'y', row=row, col=2)
        fig.update_yaxes(title_text=f'Change ({units})', zeroline=True, zerolinewidth=1,
                         zerolinecolor='#364754', row=row, col=3)
    fig.update_annotations(font_size=13)
    fig.update_layout(template='plotly_white', height=300 * len(locations) + 55,
                      margin=dict(t=76, b=65, l=72, r=24),
                      legend=dict(orientation='h', y=1, yanchor='bottom', x=1, xanchor='right'))
    return fig


def grouped_box_plot(tables, labels):
    fig = make_subplots(rows=len(tables), cols=1,
                        subplot_titles=[title for title, _ in tables])
    for row, (_, table) in enumerate(tables, start=1):
        paired = table.dropna(subset=['baseline', 'alternative'])
        locations = sorted(table.location.unique())
        for column, label, color in zip(('baseline', 'alternative'), labels, ('#17638a', '#a44721')):
            fig.add_trace(go.Box(name=label, x=paired.location, y=paired[column],
                                 text=paired.year, boxpoints='outliers', marker_color=color,
                                 legendgroup=column, showlegend=row == 1,
                                 hovertemplate='%{x} · %{text}: %{y:,.2f}<extra>%{fullData.name}</extra>'),
                          row=row, col=1)
        fig.update_xaxes(categoryorder='array', categoryarray=locations, tickangle=-25, row=row, col=1)
        fig.update_yaxes(title_text=table.units.iloc[0], row=row, col=1)
    fig.update_layout(template='plotly_white', boxmode='group', height=360 * len(tables),
                      margin=dict(t=60, b=76, l=72, r=24),
                      legend=dict(orientation='h', y=1.025, x=1, xanchor='right'))
    return fig


def distribution_report(summary, labels, system_metrics, flood_levels):
    # A system aggregate may have a different name from its reservoir-level metric.
    site_metric = {system_name: name for name, (system_name, _) in system_metrics.items()}
    tables = summary.assign(plot_metric=summary.metric.replace(site_metric))
    options, panels = [], []
    levels = [(metric, tables[tables.metric == metric]) for metric in flood_levels.values()]
    options.append('<option value="flood-levels">Flood Control / All threshold levels</option>')
    panels.append('<section id="metric-flood-levels" class="metric-panel">'
                  '<p>Each panel compares annual days strictly above that threshold at every control point.</p>'
                  + grouped_box_plot(levels, labels).to_html(full_html=False, include_plotlyjs=True)
                  + '</section>')
    for index, ((purpose, metric), table) in enumerate(tables.groupby(['purpose', 'plot_metric'])):
        options.append(f'<option value="{index}">{escape(f"{purpose} / {metric}")}</option>')
        statuses = ' · '.join(table.status.unique())
        system = table.loc[table.location == 'SYSTEM', 'metric']
        system_note = f' <strong>System:</strong> {escape(system.iloc[0])}.' if not system.empty else ''
        sites = table[table.location != 'SYSTEM']
        details = stacked_distribution_plot(table, labels).to_html(full_html=False, include_plotlyjs=False)
        overview = ''
        if sites.location.nunique() > 1:
            overview = grouped_box_plot([('Location comparison', sites)], labels).to_html(
                full_html=False, include_plotlyjs=False)
            details = '<details class="plot-details"><summary>System and individual location plots</summary>' + details + '</details>'
        panels.append(f'<section id="metric-{index}" class="metric-panel" hidden>'
                      f'<p>{escape(statuses)}.{system_note}</p>'
                      + overview + details + '</section>')
    return ('<label for="metric">Metric</label> <select id="metric">'
            + ''.join(options)
            + '</select>' + ''.join(panels)
            + '<script>document.getElementById("metric").addEventListener("change", (event) => {'
              '  document.querySelector(".metric-panel:not([hidden])").hidden = true;'
              '  const panel = document.getElementById("metric-" + event.target.value);'
              '  panel.hidden = false;'
              '  resizePlots(panel);'
              '});'
              'function resizePlots(container) {'
              '  container.querySelectorAll(".js-plotly-plot").forEach((plot) => {'
              '    if (plot.offsetWidth) Plotly.Plots.resize(plot);'
              '  });'
              '}'
              'document.querySelectorAll(".plot-details").forEach((details) => {'
              '  details.addEventListener("toggle", () => { if (details.open) resizePlots(details); });'
              '});</script>')
