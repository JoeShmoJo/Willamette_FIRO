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
CASE_COLORS = ['#17638a', '#a44721', '#5e4890', '#247455']


def water_year_overlay(series):
    """Align month/day across water years and separate the years with gaps."""
    valid = series.dropna()
    if valid.empty:
        return [], [], []
    dates = pd.date_range(valid.index.min(), valid.index.max())
    years = dates.year + (dates.month >= 10).astype(int)
    x = np.array([CALENDAR_DAYS[day.month, day.day] for day in dates], dtype=float)
    starts = np.flatnonzero(np.diff(years)) + 1
    return (np.insert(x, starts, np.nan),
            np.insert(series.reindex(dates).to_numpy(dtype=float), starts, np.nan),
            np.insert(years.to_numpy(), starts, 0))


def reservoir_figure(cases, ramps, crest, firo_curves):
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=.10,
                        subplot_titles=('Pool elevation and references', 'Daily flow'))
    missing = []
    definitions = [
        ('elev', 'Pool elevation', 1, 'solid', True, .28),
        ('flow-in', 'Inflow', 2, 'dot', 'legendonly', .34),
        ('flow-out', 'Outflow', 2, 'solid', True, .34),
        ('elev-zone', 'Rule curve', 1, 'dash', True, .85),
    ]
    for i, (label, series_by_parameter) in enumerate(cases.items()):
        color = CASE_COLORS[i % len(CASE_COLORS)]
        for parameter, title, row, dash, visible, opacity in definitions:
            if parameter not in series_by_parameter or series_by_parameter[parameter].dropna().empty:
                missing.append(f'{label} {title.lower()}')
                continue
            series = series_by_parameter[parameter]
            x, y, years = water_year_overlay(series)
            if parameter == 'elev-zone':
                # Draw a recurring rule curve once. Retain day-specific values when it varies by year.
                valid = pd.DataFrame({'day': x, 'elevation': y}).dropna()
                daily = valid.groupby('day').elevation
                if daily.nunique().le(1).all():
                    x = np.arange(len(CALENDAR))
                    y = daily.first().reindex(x).to_numpy()
                    years = None
            date_label = '%{x|%b %d}' if years is None else 'WY %{text}, %{x|%b %d}'
            # Keep the whole figure on SVG so offline reports work without WebGL.
            fig.add_trace(go.Scatter(x=CALENDAR_MS[0] + x * 86400000,
                                      y=y, text=years, name=f'{label} {title}', mode='lines',
                                      line=dict(color=color, dash=dash, width=1.6 if row == 1 else 1),
                                      opacity=opacity, visible=visible,
                                      meta='annual' if parameter != 'elev-zone' else None,
                                      hovertemplate=date_label + ': %{y:,.2f}<extra>%{fullData.name}</extra>'),
                          row=row, col=1)

    for label, target, color in firo_curves:
        fig.add_trace(go.Scatter(x=CALENDAR_MS, y=target, name=label, mode='lines',
                                 line=dict(color=color, width=2, dash='dashdot')), row=1, col=1)
    if pd.notna(crest):
        fig.add_trace(go.Scatter(x=CALENDAR_MS[[0, -1]], y=[crest, crest], mode='lines',
                                 name=f'Spillway crest ({crest:g} ft)',
                                 line=dict(color='#ae3c2b', width=2, dash='dot')), row=1, col=1)
    else:
        missing.append('spillway crest elevation')
    if ramps.empty:
        missing.append('boat-ramp elevations')
    for elevation, group in ramps.groupby('elevation_ft'):
        name = ', '.join(group.ramp_name)
        fig.add_trace(go.Scatter(x=CALENDAR_MS[[0, -1]], y=[elevation, elevation], mode='lines',
                                 name=f'{name} ({elevation:g} ft)',
                                 line=dict(color='#667684', dash='dot')), row=1, col=1)
    # Plot on an explicit numeric calendar so the browser never has to parse axis dates.
    month_starts = CALENDAR.day == 1
    fig.update_xaxes(type='linear', range=CALENDAR_MS[[0, -1]].tolist(), tickmode='array',
                     tickvals=CALENDAR_MS[month_starts].tolist(),
                     ticktext=CALENDAR[month_starts].strftime('%b').tolist())
    fig.update_xaxes(title_text='Water year (October–September)', row=2, col=1)
    fig.update_yaxes(title_text='Elevation (ft)', row=1, col=1)
    fig.update_yaxes(title_text='Flow (cfs)', row=2, col=1)
    fig.update_layout(template='plotly_white', height=660, margin=dict(t=45),
                      legend=dict(orientation='h', y=-.20))
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


def write_annual_overlays(output, results, ramps, firo_path, project_data, markers, fparts):
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
            expected_units = {'ft', 'feet'} if parameter in {'elev', 'elev-zone'} else {'cfs'}
            if not values.dropna().empty and units.casefold() not in expected_units:
                raise ValueError(f'{label} {location}/{parameter}: unsupported units {units!r}')
            case = by_reservoir.setdefault(name, {}).setdefault(label, {})
            if parameter in case:
                raise ValueError(f'{label} {location}/{parameter}: multiple daily series')
            case[parameter] = values

    links, sections = [], []
    available_years = set()
    for i, (reservoir, cases) in enumerate(sorted(by_reservoir.items())):
        links.append(f'<a href="#reservoir-{i}">{escape(reservoir)}</a>')
        ramp_rows = ramps[ramps.reservoir.str.casefold() == reservoir.casefold()]
        curves, notes = firo_overlays(reservoir, results, firo_path, evidence)
        for parameters in cases.values():
            if 'elev' in parameters:
                dates = parameters['elev'].dropna().index
                available_years.update(dates.year + (dates.month >= 10).astype(int))
        fig, missing = reservoir_figure({label: cases.get(label, {}) for label in results},
                                        ramp_rows, crest.get(reservoir.casefold()), curves)
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
    year_options = ''.join(f'<option value="{year}">{year}</option>' for year in sorted(available_years))
    output.write_text(
        '<!doctype html><html lang="en"><meta charset="utf-8"><title>Annual reservoir overlays</title>'
        '<style>body{font:15px system-ui;margin:2rem;color:#182534}'
        'nav{display:flex;gap:.5rem 1rem;flex-wrap:wrap}.reservoir-chart{min-height:660px}'
        'section{border-top:1px solid #dbe3eb;margin:2rem 0;scroll-margin-top:4rem}'
        '#overlay-controls{position:sticky;top:0;background:white;z-index:10;padding:.6rem 0;'
        'border-bottom:1px solid #dbe3eb;display:flex;gap:.7rem;flex-wrap:wrap;align-items:center}'
        '#overlay-controls button,#overlay-controls select{font:inherit}</style>'
        '<h1>Annual reservoir overlays</h1>'
        '<p>Each line overlays daily values for one water year. Hover to see its year. '
        'Click a legend item to show or hide it. Inflow starts hidden. Choose a year to highlight '
        'its paired traces, and use Up/Down while the year selector has focus.</p>'
        f'<p>Rule curves come from DSS Elev-ZONE. {firo_note}</p>'
        f'<p>FIRO source: {escape(firo_sources)}<br>Spillway crests: {escape(str(project_data))}</p>'
        '<nav>' + ''.join(links) + '</nav>'
        '<div id="overlay-controls"><label for="overlay-year">Water year</label>'
        '<button type="button" id="previous-year" aria-label="Previous water year">↑</button>'
        '<select id="overlay-year">' + year_options + '</select>'
        '<button type="button" id="next-year" aria-label="Next water year">↓</button>'
        '<label><input id="selected-year" type="checkbox" checked> Selected year</label>'
        '<label><input id="all-years" type="checkbox" checked> All years</label></div>'
        + ''.join(sections)
        + '<script>' + get_plotlyjs() + '</script>'
        + OVERLAY_CONTROLS,
        encoding='utf-8')


OVERLAY_CONTROLS = """<script>
const yearPicker = document.getElementById("overlay-year");
const selected = document.getElementById("selected-year");
const background = document.getElementById("all-years");
const previous = document.getElementById("previous-year");
const next = document.getElementById("next-year");
const charts = document.querySelectorAll(".reservoir-chart");

function updatePair(chart) {
  const sources = chart.annualSources;
  if (!sources?.length || !chart.data) return;
  const year = Number(yearPicker.value);
  const indices = [];
  const update = {x: [], y: [], name: [], visible: []};
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
    update.name.push(source.trace.name + " · WY " + year);
    const setting = chart.backgroundShown ? chart.data[source.index].visible : source.visibility;
    update.visible.push(selected.checked && y.some(Number.isFinite) && setting !== "legendonly" && setting !== false);
  }
  Plotly.restyle(chart, update, indices);
}

function updateBackground(chart) {
  if (!chart.annualSources?.length || !chart.data) return;
  if (chart.backgroundShown && !background.checked) {
    chart.annualSources.forEach((source) => { source.visibility = chart.data[source.index].visible ?? true; });
  }
  chart.backgroundShown = background.checked;
  Plotly.restyle(chart, {visible: chart.annualSources.map((source) => background.checked ? source.visibility : false)},
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
yearPicker.selectedIndex = yearPicker.options.length - 1;
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
      hovertemplate: "%{x|%b %d}: %{y:,.2f}<extra>%{fullData.name}</extra>"
    })));
  }
  chart.annualSources = annual.map((source, i) => ({...source, pairIndex: start + i}));
  chart.backgroundShown = true;
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
