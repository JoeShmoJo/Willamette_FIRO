"""Stack daily reservoir elevations and flows on a common water-year calendar."""
from html import escape

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.offline import get_plotlyjs
from plotly.subplots import make_subplots

from run_evidence import read_run_evidence

CALENDAR = pd.date_range('1999-10-01', '2000-09-30')
CALENDAR_DAYS = {(day.month, day.day): i for i, day in enumerate(CALENDAR)}
CALENDAR_MS = CALENDAR.to_numpy(dtype='datetime64[ms]').astype(np.float64)
CSV_CALENDAR = pd.date_range('1999-08-01', '2000-07-31')
CASE_COLORS = ['#17638a', '#a44721', '#5e4890', '#247455', '#926624',
               '#943c78', '#34777e', '#657525', '#80592e', '#4458a6', '#8d4350']


def water_year_overlay(series, calendar=CALENDAR):
    """Align month/day across water years and separate the years with gaps."""
    valid = series.dropna()
    if valid.empty:
        return [], [], []
    dates = pd.date_range(valid.index.min(), valid.index.max())
    years = dates.year + (dates.month >= calendar[0].month).astype(int)
    calendar_days = (CALENDAR_DAYS if calendar is CALENDAR else
                     {(day.month, day.day): i for i, day in enumerate(calendar)})
    x = np.array([calendar_days[day.month, day.day] for day in dates], dtype=float)
    starts = np.flatnonzero(np.diff(years)) + 1
    return (np.insert(x, starts, np.nan),
            np.insert(series.reindex(dates).to_numpy(dtype=float), starts, np.nan),
            np.insert(years.to_numpy(), starts, 0))


def add_storage_scale(fig, rating):
    if rating is None:
        fig.update_yaxes(showticklabels=False, showgrid=False, row=1, col=1, secondary_y=False)
        return
    elevations, storage, min_con = rating
    plotted = np.concatenate([np.asarray(trace.y, dtype=float) for trace in fig.data if trace.yaxis == 'y2']
                             or [np.array([])])
    plotted = plotted[np.isfinite(plotted)]
    if not plotted.size:
        return
    lower, upper = plotted.min(), plotted.max()
    spacing = max((upper - lower) / 6, .1)
    power = 10 ** np.floor(np.log10(spacing))
    interval = next(step * power for step in (1, 2, 5, 10) if step * power >= spacing)
    first = np.floor(lower / interval) * interval
    last = max(np.ceil(upper / interval) * interval, first + interval)
    ticks = np.arange(first, last + interval / 2, interval)
    labels = ['' if not elevations[0] <= tick <= elevations[-1] else
              f'{max(0, np.interp(tick, elevations, storage) - min_con):,.0f}' for tick in ticks]
    # Keep the left layout axis mounted without drawing a second daily series.
    fig.add_trace(go.Scatter(x=[fig.layout.xaxis.range[0]], y=[first], mode='markers',
                             opacity=0, showlegend=False, hoverinfo='skip'), row=1, col=1, secondary_y=False)
    fig.update_yaxes(range=[first, last], tickmode='array', tickvals=ticks, row=1, col=1, secondary_y=True)
    fig.update_yaxes(range=[first, last], matches='y2', tickmode='array', tickvals=ticks, ticktext=labels,
                     showgrid=False, title_text='Storage above Min Con (acre-ft)',
                     row=1, col=1, secondary_y=False)


def reservoir_figure(cases, ramps, crest, firo_curves, *, trial_controls=False, native_rule_curves=True, calendar=CALENDAR, storage_rating=None):
    storage_axis = not native_rule_curves
    period = 'Plot year' if storage_axis else 'Water year'
    calendar_ms = (CALENDAR_MS if calendar is CALENDAR else
                   calendar.to_numpy(dtype='datetime64[ms]').astype(np.float64))
    title = 'Pool elevation and references'
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=.10,
                        specs=[[{'secondary_y': storage_axis}], [{}]],
                        subplot_titles=(title, 'Daily flow'))
    missing = []
    definitions = [
        ('elev', 'Pool elevation', 1, 'solid', True, .28),
        ('flow-in', 'Inflow', 2, 'dot', 'legendonly', .34),
        ('flow-out', 'Outflow', 2, 'solid', True, .34),
        ('elev-zone', 'Rule curve', 1, 'dash', True, .85),
    ]
    if not native_rule_curves:
        definitions.pop()
    for i, (label, series_by_parameter) in enumerate(cases.items()):
        color = CASE_COLORS[i % len(CASE_COLORS)]
        for parameter, title, row, dash, visible, opacity in definitions:
            if parameter not in series_by_parameter or series_by_parameter[parameter].dropna().empty:
                missing.append(f'{label} {title.lower()}')
                continue
            series = series_by_parameter[parameter]
            x, y, years = water_year_overlay(series, calendar)
            if parameter == 'elev-zone':
                # Draw a recurring rule curve once. Retain day-specific values when it varies by year.
                valid = pd.DataFrame({'day': x, 'elevation': y}).dropna()
                daily = valid.groupby('day').elevation
                if daily.nunique().le(1).all():
                    x = np.arange(len(calendar))
                    y = daily.first().reindex(x).to_numpy()
                    years = None
            date_label = '%{x|%b %d}' if years is None else period + ' %{text}, %{x|%b %d}'
            # Keep the whole figure on SVG so offline reports work without WebGL.
            fig.add_trace(go.Scatter(x=calendar_ms[0] + x * 86400000,
                                      y=y, text=years, name=f'{label} {title}', mode='lines',
                                      line=dict(color=color, dash=dash, width=1.6 if row == 1 else 1),
                                      opacity=opacity, visible=visible,
                                      legendgroup=label if trial_controls else None,
                                      meta='annual' if parameter != 'elev-zone' else None,
                                      hovertemplate=date_label + ': %{y:,.2f}<extra>%{fullData.name}</extra>'),
                          row=row, col=1, secondary_y=storage_axis and parameter in ('elev', 'elev-zone'))

    for label, target, color in firo_curves:
        is_firo = label.endswith(' configured FIRO target')
        group = label.removesuffix(' configured FIRO target') if trial_controls and is_firo else None
        hover = ('%{text}: %{y:,.2f} ft<extra>%{fullData.name} · Recurring schedule</extra>'
                 if is_firo else '%{text}: %{y:,.2f} ft<extra>%{fullData.name}</extra>')
        fig.add_trace(go.Scatter(
            x=calendar_ms, y=target, text=calendar.strftime('%b %d').tolist(), name=label, mode='lines',
            line=dict(color=color, width=2, dash='dot' if is_firo else 'dashdot'),
            legendgroup=group, hovertemplate=hover), row=1, col=1, secondary_y=storage_axis)
    if pd.notna(crest):
        fig.add_trace(go.Scatter(x=calendar_ms[[0, -1]], y=[crest, crest], mode='lines',
                                 name=f'Spillway crest ({crest:g} ft)',
                                 line=dict(color='#ae3c2b', width=2, dash='dot')), row=1, col=1, secondary_y=storage_axis)
    else:
        missing.append('spillway crest elevation')
    if ramps.empty:
        missing.append('boat-ramp elevations')
    for elevation, group in ramps.groupby('elevation_ft'):
        name = ', '.join(group.ramp_name)
        fig.add_trace(go.Scatter(x=calendar_ms[[0, -1]], y=[elevation, elevation], mode='lines',
                                 name=f'{name} ({elevation:g} ft)',
                                 line=dict(color='#667684', dash='dot')), row=1, col=1, secondary_y=storage_axis)
    # Plot on an explicit numeric calendar so the browser never has to parse axis dates.
    month_starts = calendar.day == 1
    fig.update_xaxes(type='linear', range=calendar_ms[[0, -1]].tolist(), tickmode='array',
                     tickvals=calendar_ms[month_starts].tolist(),
                     ticktext=calendar[month_starts].strftime('%b').tolist())
    fig.update_xaxes(title_text=(period + ' (August–July)' if storage_axis else
                                 'Water year (October–September)'), row=2, col=1)
    fig.update_yaxes(title_text='Elevation (ft)', row=1, col=1, secondary_y=storage_axis)
    if storage_axis:
        add_storage_scale(fig, storage_rating)
    fig.update_yaxes(title_text='Flow (cfs)', row=2, col=1)
    fig.update_layout(template='plotly_white', height=660, margin=dict(t=45),
                      legend=dict(orientation='h', y=-.20, groupclick='toggleitem'))
    return fig, missing


def firo_overlays(reservoir, labels, firo_path, evidence):
    from recreation import firo_schedule

    curves, notes = [], []
    if not evidence:
        target, _ = firo_schedule(firo_path, reservoir, CALENDAR)
        if target.notna().any():
            curves.append(('FIRO target reference', target, '#6b4589'))
        else:
            notes.append('FIRO target schedule unavailable')
        return curves, notes

    for i, label in enumerate(labels):
        if label not in evidence:
            notes.append(f'{label} FIRO configuration not supplied')
            continue
        path, activation = evidence[label]
        enabled = activation.get(reservoir.casefold())
        if path is None or enabled is False:
            notes.append(f'{label} FIRO off')
        elif enabled is None:
            notes.append(f'{label} FIRO activation receipt unavailable')
        else:
            target, _ = firo_schedule(path, reservoir, CALENDAR)
            if target.notna().any():
                curves.append((f'{label} FIRO target', target, CASE_COLORS[i % len(CASE_COLORS)]))
            else:
                notes.append(f'{label} has no scheduled FIRO target')
    return curves, notes


def write_annual_overlays(output, results, ramps, firo_path, project_data, markers, fparts, *,
                          reference_curves=None, trial_controls=False, rule_note=None, storage_axes=None):
    with project_data.open(encoding='utf-8-sig') as stream:
        header = next((i for i, line in enumerate(stream) if line.startswith('Variable,')), None)
    if header is None:
        raise ValueError(f'No Variable header in {project_data}')
    projects = pd.read_csv(project_data, skiprows=header, comment='#', encoding='utf-8-sig')
    crest = pd.to_numeric(projects.set_index('Variable').loc['SpillwayCrestElev'], errors='raise')
    crest.index = crest.index.str.strip().str.casefold()
    evidence = {}
    for label, marker in markers.items():
        target, activation, _ = read_run_evidence(marker, fparts[label], allow_disabled_without_receipts=True)
        evidence[label] = target, {name.casefold(): active for name, active in activation.items()}
    by_reservoir = {}
    for label, records in results.items():
        for (_, location, parameter), (values, units) in records.items():
            if location.casefold().endswith('-pool'):
                name = location[:-len('-Pool')]
            elif location.casefold().endswith('-rule curve'):
                name = location[:-len('-Rule Curve')]
            else:
                continue
            parameter = parameter.casefold()
            expected_units = ({'ft', 'feet'} if parameter in {'elev', 'elev-zone'} else
                              {'acre-ft'} if parameter == 'stor-above-min-con' else {'cfs'})
            if not values.dropna().empty and units.casefold() not in expected_units:
                raise ValueError(f'{label} {location}/{parameter}: unsupported units {units!r}')
            case = by_reservoir.setdefault(name, {}).setdefault(label, {})
            if parameter in case:
                raise ValueError(f'{label} {location}/{parameter}: multiple daily series')
            case[parameter] = values

    calendar = CSV_CALENDAR if reference_curves else CALENDAR
    year_label = 'Plot year' if reference_curves else 'Water year'
    reservoir_options, sections = [], []
    available_years = set()
    shared_elevation_dates = None
    for i, (reservoir, cases) in enumerate(sorted(by_reservoir.items())):
        reservoir_options.append(f'<option value="reservoir-{i}">{escape(reservoir)}</option>')
        ramp_rows = ramps[ramps.reservoir.str.casefold() == reservoir.casefold()]
        curves, notes = (reference_curves or firo_overlays)(reservoir, results, firo_path, evidence)
        for parameters in cases.values():
            if 'elev' in parameters:
                dates = parameters['elev'].dropna().index
                available_years.update(dates.year + (dates.month >= calendar[0].month).astype(int))
                if reference_curves and not dates.empty:
                    shared_elevation_dates = (dates.unique() if shared_elevation_dates is None else
                                              shared_elevation_dates.intersection(dates))
        fig, missing = reservoir_figure({label: cases.get(label, {}) for label in results},
                                        ramp_rows, crest.get(reservoir.casefold()), curves,
                                        trial_controls=trial_controls, native_rule_curves=reference_curves is None,
                                        calendar=calendar,
                                        storage_rating=(storage_axes or {}).get(reservoir.casefold()))
        if reference_curves and reservoir.casefold() not in (storage_axes or {}):
            notes.append('Baseline elevation–storage rating or minimum conservation level unavailable')
        if missing:
            notes.append(f'Unavailable: {", ".join(missing)}')
        note = f'<p>{escape(". ".join(notes))}.</p>' if notes else ''
        spec = fig.to_json().replace('<', '\\u003c')
        sections.append(f'<section id="reservoir-{i}"><h2>{escape(reservoir)}</h2>{note}'
                        '<div class="reservoir-chart"></div>'
                        f'<script type="application/json">{spec}</script></section>')
    if markers:
        firo_note = ('FIRO targets come from the matched run configurations. Displayed schedules '
                     'describe initialized FIRO rules. Daily application can still depend on the operating zone.')
        firo_sources = ', '.join(f'{label}: {marker}' for label, marker in markers.items())
    else:
        firo_note = ('The FIRO line is the recurring target schedule from the reference CSV. '
                     'It does not establish whether FIRO was active in either run.')
        firo_sources = str(firo_path)
    complete_years = available_years
    if reference_curves and shared_elevation_dates is not None:
        complete_years = set()
        for year in available_years:
            start = pd.Timestamp(year - 1, 8, 1)
            end = pd.Timestamp(year, 8, 1)
            if ((shared_elevation_dates >= start) & (shared_elevation_dates < end)).sum() == (end - start).days:
                complete_years.add(year)
    default_year = max(complete_years or available_years, default=None)
    year_options = ''.join(
        f'<option value="{year}"{" selected" if year == default_year else ""}>'
        f'{year}{" (partial)" if year not in complete_years else ""}</option>'
        for year in sorted(available_years))
    run_controls = ''
    if trial_controls:
        run_controls = '<fieldset><legend>Show runs</legend>' + ' '.join(
            f'<label><input type="checkbox" data-run="{escape(label, quote=True)}" checked> {escape(label)}</label>'
            for label in results) + '</fieldset>'
    if reference_curves:
        data_note = ('Pool series come from the trial CSV exports. FIRO target lines require captured '
                     'enablement and a captured schedule. Dotted FIRO targets repeat by month and day. '
                     'They stay fixed when you change the selected plot year. '
                     'One line shows pool elevation on the right and the equivalent storage above Min Con on the left. '
                     'The storage scale uses the baseline elevation–storage rating for all runs. '
                     'Storage labels are blank outside that rating’s range. '
                     'The chart initially shows the selected year. Turn on All years to add the faint background traces. '
                     'Plot years run August 1 through July 31 and are labeled by the ending year. '
                     'The selector starts at the latest complete plot year when available. '
                     'Partial years are labeled and show only the dates available. '
                     'Min Con is the lowest reference rule curve elevation.')
        if rule_note:
            data_note += ' ' + rule_note + ' This reference does not come from the selected compute.'
    else:
        data_note = f'Rule curves come from DSS Elev-ZONE. {firo_note}'
    output.write_text(
        '<!doctype html><html lang="en"><meta charset="utf-8"><title>Annual reservoir overlays</title>'
        '<style>body{font:15px system-ui;margin:2rem;color:#182534}'
        '.reservoir-chart{min-height:660px}'
        'section{border-top:1px solid #dbe3eb;margin:2rem 0;scroll-margin-top:var(--overlay-scroll-offset,4rem)}'
        '#overlay-controls{position:sticky;top:0;background:white;z-index:10;padding:.6rem 0;'
        'border-bottom:1px solid #dbe3eb;display:flex;gap:.7rem;flex-wrap:wrap;align-items:center}'
        '#overlay-controls button,#overlay-controls select{font:inherit}</style>'
        '<h1>Annual reservoir overlays</h1>'
        f'<p>Each line overlays daily values for one {year_label.lower()}. Hover to see its year. '
        'Click a legend item to show or hide it. Inflow starts hidden. Choose a year to highlight '
        'its traces, and use Up/Down while the year selector has focus.</p>'
        f'<p>{escape(data_note)}</p>'
        f'<p>FIRO source: {escape(firo_sources)}<br>Spillway crests: {escape(str(project_data))}</p>'
        '<div id="overlay-controls"><label for="overlay-reservoir">Reservoir</label>'
        '<select id="overlay-reservoir"><option value="">Choose a reservoir</option>'
        + ''.join(reservoir_options) + '</select>'
        f'<label for="overlay-year">{year_label}</label>'
        '<button type="button" id="previous-year" aria-label="Previous year">↑</button>'
        f'<select id="overlay-year" data-year-label="{year_label}">' + year_options + '</select>'
        '<button type="button" id="next-year" aria-label="Next year">↓</button>'
        '<label><input id="selected-year" type="checkbox" checked> Selected year</label>'
        f'<label><input id="all-years" type="checkbox"{" checked" if not reference_curves else ""}> All years</label>'
        + run_controls + '</div>'
        + ''.join(sections)
        + '<script>' + get_plotlyjs() + '</script>'
        + OVERLAY_CONTROLS,
        encoding='utf-8')


OVERLAY_CONTROLS = """<script>
const toolbar = document.getElementById("overlay-controls");
const reservoirPicker = document.getElementById("overlay-reservoir");
function updateScrollOffset() {
  document.documentElement.style.setProperty("--overlay-scroll-offset", (toolbar.offsetHeight + 12) + "px");
}
new ResizeObserver(updateScrollOffset).observe(toolbar);
reservoirPicker.addEventListener("change", () => {
  if (!reservoirPicker.value) return;
  updateScrollOffset();
  document.getElementById(reservoirPicker.value)?.scrollIntoView({block: "start"});
});
const yearPicker = document.getElementById("overlay-year");
const selected = document.getElementById("selected-year");
const background = document.getElementById("all-years");
const previous = document.getElementById("previous-year");
const next = document.getElementById("next-year");
const charts = document.querySelectorAll(".reservoir-chart");
const runToggles = new Map(Array.from(document.querySelectorAll("[data-run]"),
  input => [input.dataset.run, input]));
const runEnabled = trace => runToggles.get(trace.legendgroup)?.checked ?? true;

function updateRun(chart, label, enabled) {
  if (!chart.annualSources || !chart.data) return;
  const indices = [], visibility = [];
  const sources = new Map(chart.annualSources.map(source => [source.index, source]));
  chart.data.forEach((trace, index) => {
    if (trace.legendgroup !== label) return;
    const source = sources.get(index);
    if (!enabled && !chart.hiddenRunTraces.has(index)) {
      chart.hiddenRunTraces.set(index, source && !chart.backgroundShown
        ? source.visibility : trace.visible ?? true);
    }
    const preferred = chart.hiddenRunTraces.get(index) ?? trace.visible ?? true;
    indices.push(index);
    visibility.push(enabled && (!source || chart.backgroundShown) ? preferred : false);
    if (enabled) {
      if (source) source.visibility = preferred;
      chart.hiddenRunTraces.delete(index);
    }
  });
  if (indices.length) Plotly.restyle(chart, {visible: visibility}, indices);
  updatePair(chart);
}

function updatePair(chart) {
  const sources = chart.annualSources;
  if (!sources?.length || !chart.data) return;
  const year = Number(yearPicker.value);
  const indices = [];
  const update = {x: [], y: [], text: [], name: [], visible: [], showlegend: []};
  for (const source of sources) {
    const x = [], y = [];
    for (let i = 0; i < source.trace.text.length; i++) {
      if (Number(source.trace.text[i]) === year) {
        x.push(source.trace.x[i]);
        y.push(source.trace.y[i]);
      }
    }
    indices.push(source.pairIndex);
    update.x.push(x);
    update.y.push(y);
    update.text.push(x.map(value => new Date(value).toISOString().slice(5, 10)));
    update.name.push(source.trace.name + " · " + yearPicker.dataset.yearLabel + " " + year);
    const setting = chart.backgroundShown ? chart.data[source.index].visible : source.visibility;
    const valid = selected.checked && runEnabled(source.trace) && y.some(Number.isFinite);
    const legend = valid && !chart.backgroundShown;
    update.showlegend.push(legend);
    update.visible.push(!valid ? false : setting === "legendonly" || setting === false
      ? (legend ? "legendonly" : false) : true);
  }
  Plotly.restyle(chart, update, indices);
}

function updateBackground(chart) {
  if (!chart.annualSources?.length || !chart.data) return;
  if (chart.backgroundShown && !background.checked) {
    chart.annualSources.forEach((source) => { if (runEnabled(source.trace)) source.visibility = chart.data[source.index].visible ?? true; });
  }
  chart.backgroundShown = background.checked;
  Plotly.restyle(chart, {visible: chart.annualSources.map((source) => background.checked && runEnabled(source.trace) ? source.visibility : false)},
                 chart.annualSources.map((source) => source.index));
  updatePair(chart);
}

function updateYear() {
  charts.forEach(updatePair);
}
function stepYear(direction) {
  const count = yearPicker.options.length;
  if (!count) return;
  yearPicker.selectedIndex = (yearPicker.selectedIndex + direction + count) % count;
  updateYear();
}
previous.disabled = next.disabled = yearPicker.options.length < 2;
previous.addEventListener("click", () => stepYear(-1));
next.addEventListener("click", () => stepYear(1));
yearPicker.addEventListener("keydown", (event) => {
  if (event.key === "ArrowUp" || event.key === "ArrowDown") {
    event.preventDefault();
    stepYear(event.key === "ArrowUp" ? -1 : 1);
  }
});
yearPicker.addEventListener("change", updateYear);
selected.addEventListener("change", updateYear);
background.addEventListener("change", () => charts.forEach(updateBackground));
runToggles.forEach((input, label) => input.addEventListener("change", () =>
  charts.forEach(chart => updateRun(chart, label, input.checked))));
updateYear();

async function mount(chart) {
  const spec = JSON.parse(chart.nextElementSibling.textContent);
  if (chart.traceVisibility) {
    spec.data.forEach((trace, i) => { trace.visible = chart.traceVisibility[i]; });
  }
  await Plotly.newPlot(chart, spec.data, spec.layout, {responsive: true});
  const annual = chart._fullData.flatMap((trace, index) => trace.meta === "annual"
    ? [{trace, index, visibility: chart.data[index].visible ?? true}] : []);
  const start = chart.data.length;
  if (annual.length) {
    await Plotly.addTraces(chart, annual.map(({trace}) => ({
      type: "scatter", mode: "lines", x: [], y: [], visible: false, showlegend: false,
      xaxis: trace.xaxis, yaxis: trace.yaxis, line: {...trace.line, width: 3.2},
      hovertemplate: "%{text}: %{y:,.2f}<extra>%{fullData.name}</extra>"
    })));
  }
  chart.annualSources = annual.map((source, i) => ({...source, pairIndex: start + i}));
  chart.backgroundShown = true;
  chart.hiddenRunTraces = new Map();
  runToggles.forEach((input, label) => {
    if (!input.checked) updateRun(chart, label, false);
  });
  chart.on("plotly_legendclick", event => {
    if (chart.backgroundShown) return;
    const source = chart.annualSources.find(item => item.pairIndex === event.curveNumber);
    if (!source) return;
    source.visibility = source.visibility === "legendonly" || source.visibility === false ? true : "legendonly";
    updatePair(chart);
    return false;
  });
  chart.on("plotly_restyle", ([update, indices]) => {
    if (update.visible && chart.backgroundShown && indices.some((i) => i < start)) {
      window.requestAnimationFrame(() => updatePair(chart));
    }
  });
  if (background.checked) updatePair(chart);
  else updateBackground(chart);
}

const observer = new IntersectionObserver((entries) => {
  for (const entry of entries) {
    const chart = entry.target;
    if (!entry.isIntersecting && chart.data && !chart.mounting) {
      const original = chart.data.length - (chart.annualSources?.length ?? 0);
      const visibility = chart.data.slice(0, original).map((trace) => trace.visible);
      if (!chart.backgroundShown) {
        chart.annualSources.forEach((source) => { visibility[source.index] = source.visibility; });
      }
      chart.hiddenRunTraces.forEach((setting, index) => { visibility[index] = setting; });
      chart.traceVisibility = visibility;
      chart.annualSources = null;
      Plotly.purge(chart);
    } else if (entry.isIntersecting && !chart.data && !chart.mounting) {
      chart.mounting = true;
      mount(chart).finally(() => { chart.mounting = false; });
    }
  }
}, {rootMargin: "400px"});
charts.forEach((chart) => observer.observe(chart));
</script>"""
