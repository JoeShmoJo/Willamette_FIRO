"""Plot the progressive WAT FIRO curves for Lookout Point on one figure."""

import argparse
import hashlib
from html import escape
from io import BytesIO
from pathlib import Path
import re

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
from plotly.offline import get_plotlyjs

from compare_k_scaling import load_module
from run import ROOT


COMPONENTS = {
    "A": "Flat winter pool",
    "C": "Early refill",
    "E": "Early MaxCon",
    "H": "Spillway crest",
    "I": "April 1 refill",
    "J": "Delayed drawdown",
    "K": "Advanced refill",
    "M": "Constant storage offset",
}


def load_plot_inputs():
    builder = load_module("02_build_component_curves.py")
    projects = pd.read_csv(builder.PHYSICAL_PROJECTS_FILE).set_index("project_id")
    issues = []
    rules = builder.build_rule_curve_lookup(pd.read_csv(builder.RULE_CURVES_FILE), issues)
    raw_rating = pd.read_csv(builder.STORAGE_ELEVATION_FILE)
    ratings = {}
    for name, table in raw_rating.groupby("Reservoir"):
        ratings[name] = table[["Elev", "Stor"]].dropna().sort_values("Elev").drop_duplicates("Elev", keep="last")
    if issues:
        raise ValueError(f"Invalid rule-curve inputs: {issues}")
    colors = {**load_module("03_cap_validate_and_plot_curves.py").COMPONENT_COLORS, "M": "#00857c"}
    return projects, rules, ratings, colors


def read_targets(path, names):
    raw = path.read_bytes()
    table = pd.read_csv(BytesIO(raw), comment="#").set_index(["Month", "Day"], verify_integrity=True)
    dates = pd.date_range("2001-01-01", "2001-12-31")
    calendar = pd.MultiIndex.from_arrays([dates.month, dates.day], names=["Month", "Day"])
    if len(table) != len(calendar) or not table.sort_index().index.equals(calendar):
        raise ValueError(f"Expected a complete non-leap calendar in {path}")
    if not set(names).issubset(table.columns):
        raise ValueError(f"Missing modeled reservoir columns in {path}")
    numeric = table[names].apply(pd.to_numeric, errors="raise")
    if np.isinf(numeric.to_numpy()).any():
        raise ValueError(f"Invalid target elevation in {path}")
    return numeric, hashlib.sha256(raw).hexdigest()


def installed_targets(watershed, names):
    targets = {}
    sources = []
    for code in COMPONENTS:
        case = f"PGFIRO_{code}"
        override = watershed / "scripts/alt_config/WAT" / f"{case}.txt"
        text = override.read_text(encoding="utf-8-sig")
        active = re.findall(r"(?im)^\s*firoActive\s*:\s*(true|false)\b", text)
        paths = re.findall(r'(?m)^\s*firoSpaceConfigCSV\s*:\s*"([^"]+)"', text)
        if len(active) != 1 or active[0].lower() != "true" or len(paths) != 1:
            raise ValueError(f"Expected an active FIRO setting and one curve path in {override}")
        path = (watershed / paths[0].replace("\\", "/")).resolve()
        if not path.is_relative_to(watershed):
            raise ValueError(f"Curve path is outside the watershed: {path}")
        targets[code], checksum = read_targets(path, names)
        sources.append((case, override.relative_to(watershed), path.relative_to(watershed), checksum))
    return targets, sources


def build_figure(project, rule, rating, colors, targets):
    if len(rating) < 2:
        raise ValueError(f"Invalid storage rating for {project.project_name}")

    min_con_storage = np.interp(project.min_con_elev_ft, rating.Elev, rating.Stor)

    def storage_above_mincon(elevation):
        return (np.interp(elevation, rating.Elev, rating.Stor) - min_con_storage) / 1000

    days = rule.index
    calendar = pd.MultiIndex.from_arrays([days.month, days.day], names=["Month", "Day"])
    figure = go.Figure()
    figure.add_trace(go.Scatter(
        x=[days[0]], y=[rule.iloc[0]], yaxis="y", mode="markers", opacity=0,
        showlegend=False, hoverinfo="skip",
    ))
    figure.add_trace(go.Scatter(
        x=days, y=rule, yaxis="y2", mode="lines", name="Rule curve",
        line={"color": "#273242", "width": 2.6},
        customdata=storage_above_mincon(rule),
        hovertemplate="%{y:,.2f} ft · %{customdata:,.1f} KAF above MinCon<extra>%{fullData.name}</extra>",
    ))
    limits = [rule.min(), rule.max()]
    for code, label in COMPONENTS.items():
        target = targets[code][project.project_name].reindex(calendar)
        if not target.notna().any():
            continue
        limits.extend([target.min(), target.max()])
        figure.add_trace(go.Scatter(
            x=days, y=target, yaxis="y2", mode="lines", name=f"{code} · {label}",
            line={"color": colors[code], "width": 2.4}, connectgaps=False,
            customdata=storage_above_mincon(target),
            hovertemplate="%{y:,.2f} ft · %{customdata:,.1f} KAF above MinCon<extra>%{fullData.name}</extra>",
        ))
    crest = project.spillway_crest_elev_ft
    if pd.notna(crest):
        limits.append(crest)
        figure.add_trace(go.Scatter(
            x=[days[0], days[-1]], y=[crest, crest], yaxis="y2", mode="lines",
            name=f"Spillway crest ({crest:g} ft)", line={"color": "#a1aab6", "dash": "dash", "width": 1.4},
            hovertemplate="Spillway crest %{y:.1f} ft<extra></extra>",
        ))
    # Use elevations as plotting coordinates on both sides. Only the left
    # tick labels are converted, so the nonlinear rating remains aligned.
    spacing = max((max(limits) - min(limits)) / 10, 1)
    magnitude = 10 ** np.floor(np.log10(spacing))
    step = next(value * magnitude for value in (1, 2, 5, 10) if value * magnitude >= spacing)
    min_con = project.min_con_elev_ft
    first = min_con + step * np.floor((min(limits) - min_con) / step)
    ticks = np.arange(first, max(limits) + step, step)
    storage_labels = [
        f"{value:,.0f}" if rating.Elev.min() <= tick <= rating.Elev.max() else ""
        for tick, value in zip(ticks, storage_above_mincon(ticks))
    ]
    axis = {
        "range": [min(limits) - 5, max(limits) + 5],
        "tickmode": "array", "tickvals": ticks, "fixedrange": True,
    }
    figure.update_layout(
        title={"text": f"{project.project_name} · FIRO component curves", "x": 0.04},
        template="plotly_white", height=565, autosize=True, hovermode="closest",
        xaxis={"dtick": "M1", "tickformat": "%b", "hoverformat": "%b %d"},
        yaxis={**axis, "side": "left", "title": "Storage above MinCon (KAF)",
               "ticktext": storage_labels, "showgrid": False},
        yaxis2={**axis, "side": "right", "title": "Elevation (ft)", "overlaying": "y", "anchor": "x"},
        legend={"orientation": "h", "y": -0.16, "x": 0,
                "itemclick": "toggle", "itemdoubleclick": "toggleothers"},
        margin={"l": 95, "r": 80, "t": 70, "b": 115},
    )
    return figure


def write_watershed_review(output, watershed, projects, rules, ratings, colors, targets, sources):
    options = []
    figures = []
    notes = []
    for index, (project_id, project) in enumerate(projects.iterrows()):
        name = project.project_name
        selected = " selected" if project_id == "LOOKOUT_POINT" else ""
        options.append(f'<option value="{index}"{selected}>{escape(name)}</option>')
        figures.append(pio.to_json(build_figure(project, rules[project_id], ratings[name], colors, targets)))
        blank = [f"PGFIRO_{code}" for code, table in targets.items() if table[name].isna().all()]
        note = "No targets in " + ", ".join(blank) if blank else "All eight cases have targets."
        notes.append(f'<p data-case="{index}" hidden>{escape(note)}</p>')

    rows = []
    for case, override, path, checksum in sources:
        rows.append(
            f"<tr><th>{case}</th><td>{escape(override.as_posix())}</td>"
            f'<td>{escape(path.as_posix())}</td><td title="{checksum}">{checksum[:12]}</td></tr>'
        )
    payload = ("[" + ",".join(figures) + "]").replace("<", "\\u003c")
    output.write_text(
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<title>Installed WAT FIRO curves</title><style>'
        'body{margin:24px;font:16px system-ui;color:#243142}select{font:inherit;padding:.3em}'
        'table{border-collapse:collapse}th,td{padding:.35em .7em;text-align:left;border-bottom:1px solid #ddd}'
        'details{overflow-x:auto}summary{cursor:pointer}</style></head><body>'
        '<h1>Installed WAT FIRO curves</h1>'
        f'<p>Watershed: {escape(str(watershed))}</p>'
        '<label for="reservoir">Reservoir </label><select id="reservoir">'
        + "".join(options) + '</select>' + "".join(notes) +
        '<p>Component lines come from the installed WAT overrides. The ordinary rule curve and '
        'storage rating are the FIRO model references. Click a legend item to toggle it.</p>'
        '<div id="chart"></div><details><summary>Installed source files</summary>'
        '<table><thead><tr><th>WAT alternative</th><th>Override</th><th>CSV</th><th>SHA-256 prefix</th></tr>'
        '</thead><tbody>' + "".join(rows) + '</tbody></table></details>'
        '<script>' + get_plotlyjs() + '</script>'
        '<script id="figures" type="application/json">' + payload + '</script>'
        '<script>const figures=JSON.parse(document.getElementById("figures").textContent);'
        'const selector=document.getElementById("reservoir");function draw(){'
        'const fig=figures[selector.value];document.querySelectorAll("[data-case]").forEach('
        'note=>note.hidden=note.dataset.case!==selector.value);'
        'Plotly.react("chart",fig.data,fig.layout,{responsive:true,displaylogo:false});'
        '}selector.addEventListener("change",draw);draw();</script></body></html>',
        encoding="utf-8",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    default = ROOT / "outputs/diagnostics/progressive_wat_csvs"
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--curves", type=Path)
    source.add_argument("--watershed", type=Path, help="Read installed PGFIRO overrides and plot all reservoirs")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    curves = args.curves or default
    projects, rules, ratings, colors = load_plot_inputs()
    names = projects.project_name.tolist()
    filename = "installed_wat_firo_curves.html" if args.watershed else "lookout_point_firo_components.html"
    output = args.output or curves / filename
    output.parent.mkdir(parents=True, exist_ok=True)
    if args.watershed:
        watershed = args.watershed.resolve()
        targets, sources = installed_targets(watershed, names)
        write_watershed_review(output, watershed, projects, rules, ratings, colors, targets, sources)
        print(f"Verified {len(sources)} installed override/CSV pairs and plotted {len(projects)} reservoirs.")
    else:
        targets = {
            code: read_targets(curves / f"FIRO_SPACEConfig_Progressive_{code}.csv", names)[0]
            for code in COMPONENTS
        }
        project = projects.loc["LOOKOUT_POINT"]
        figure = build_figure(project, rules[project.name], ratings[project.project_name], colors, targets)
        figure.write_html(output, include_plotlyjs=True, config={"responsive": True, "displaylogo": False})
    print(f"FIRO component plot: {output.resolve()}")


if __name__ == "__main__":
    main()
