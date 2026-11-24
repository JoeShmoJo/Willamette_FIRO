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
from plotly.offline import get_plotlyjs

from compare_k_scaling import load_module, shared_limits
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
    ratings = builder.build_rating_lookup(builder.read_storage_ratings(), issues)
    rules = builder.build_rule_curve_lookup(builder.read_rule_curves(), ratings, issues)
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


def build_figure(project, rule, rating, colors, targets, show_axis_controls=True):
    min_con = project.min_con_elev_ft
    min_storage = np.interp(min_con, rating.elevation_ft, rating.storage_kaf)
    storage_rating = rating.storage_kaf - min_storage

    days = rule.index
    calendar = pd.MultiIndex.from_arrays([days.month, days.day], names=["Month", "Day"])
    figure = go.Figure()

    def add_curve(x, elevation, name, line):
        storage = np.interp(elevation, rating.elevation_ft, storage_rating)
        figure.add_trace(go.Scatter(
            x=x, y=storage, mode="lines", name=name, line=line, connectgaps=False,
            customdata=np.column_stack((storage, elevation)),
            hovertemplate=("%{customdata[0]:,.2f} KAF above MinCon · "
                           "%{customdata[1]:,.2f} ft<extra>%{fullData.name}</extra>"),
        ))

    add_curve(days, rule, "Rule curve", {"color": "#273242", "width": 2.6})
    for code, table in targets.items():
        target = table[project.project_name].reindex(calendar)
        if target.notna().any():
            add_curve(days, target, f"{code} · {COMPONENTS[code]}", {"color": colors[code], "width": 2.4})
    crest = project.spillway_crest_elev_ft
    if pd.notna(crest):
        add_curve([days[0], days[-1]], [crest, crest], f"Spillway crest ({crest:g} ft)",
                  {"color": "#a1aab6", "dash": "dash", "width": 1.4})

    buttons = []
    for dimension, label, origin, primary, secondary in (
        (0, "Even storage ticks", 0, storage_rating, rating.elevation_ft),
        (1, "Even elevation ticks", min_con, rating.elevation_ft, storage_rating),
    ):
        coordinates = [trace.customdata[:, dimension] for trace in figure.data]
        limits = np.concatenate(coordinates)
        low, high = np.nanmin(limits), np.nanmax(limits)
        spacing = (high - low) / 8 or 1
        magnitude = 10 ** np.floor(np.log10(spacing))
        step = next(value * magnitude for value in (1, 2, 5, 10) if value * magnitude >= spacing)
        ticks = origin + np.arange(np.ceil((low - origin) / step), np.floor((high - origin) / step) + 1) * step
        positions = dict(range=[low - step / 3, high + step / 3], tickmode="array", tickvals=ticks, fixedrange=True)
        converted = np.interp(ticks, primary, secondary)
        tick_labels = [ticks, converted] if dimension == 0 else [converted, ticks]
        layout = {
            "yaxis": dict(**positions, title="Storage above MinCon (KAF)", ticktext=[f"{v:,.4g}" for v in tick_labels[0]]),
            "yaxis2": dict(**positions, title="Elevation (ft)", ticktext=[f"{v:,.1f}".removesuffix(".0") for v in tick_labels[1]],
                           overlaying="y", side="right", anchor="x", showgrid=False),
        }
        buttons.append(dict(label=label, method="update", args=[{"y": coordinates}, layout]))
        if dimension == 0:
            figure.update_layout(**layout)

    figure.update_layout(
        title={"text": project.project_name, "x": 0.04},
        template="plotly_white", height=455, hovermode="closest",
        xaxis={"dtick": "M1", "tickformat": "%b", "hoverformat": "%b %d"},
        updatemenus=[dict(type="buttons", direction="right", x=1, xanchor="right", y=1.18, buttons=buttons, visible=show_axis_controls)],
        legend={"orientation": "h", "y": -0.17, "x": 0},
        margin={"l": 100, "r": 95, "t": 100, "b": 80},
    )
    return figure


def constraint_table(projects, rules, ratings, targets, groups):
    """Report peak unrouted storage above the rule curve from the plotted CSV."""
    daily = []
    for key, project in projects.iterrows():
        rule = rules[key]
        calendar = pd.MultiIndex.from_arrays([rule.index.month, rule.index.day], names=["Month", "Day"])
        target = targets[project.project_name].reindex(calendar).to_numpy()
        rating = ratings[key]
        target_storage = np.interp(target, rating.elevation_ft, rating.storage_kaf)
        rule_storage = np.interp(rule, rating.elevation_ft, rating.storage_kaf)
        daily.append(np.maximum(np.nan_to_num(target_storage - rule_storage), 0))
    offsets = np.column_stack(daily)
    names = list(projects.project_name) + [name for _, name, _, _ in groups]
    limits = list(projects.physical_cap_kaf) + [limit for _, _, limit, _ in groups]
    peaks = list(offsets.max(axis=0)) + [offsets[:, members].sum(axis=1).max() for _, _, _, members in groups]
    header = "".join(f"<th scope='col'>{escape(name)}</th>" for name in names)
    rows = zip(
        ("Constraint (KAF)", "Maximum achieved (KAF)", "Utilized (%)"),
        ([f"{v:,.2f}" for v in limits], [f"{v:,.2f}" for v in peaks],
         [f"{peak / limit:.1%}" if limit > 0 else "—" for peak, limit in zip(peaks, limits)]),
    )
    body = "".join(f"<tr><th scope='row'>{label}</th>" + "".join(f"<td>{v}</td>" for v in values) + "</tr>"
                   for label, values in rows)
    return f"<div class='table'><table><thead><tr><th>Metric</th>{header}</tr></thead><tbody>{body}</tbody></table></div>"


def write_alternative_review(output, projects, rules, ratings, colors, targets, source_details, prefix="PGFIRO"):
    allocator = load_module("01_allocate_static_firo_space.py")
    limits, units, points, _, network = allocator.load_inputs()
    _, relationships = allocator.build_control_point_relationships(network, points, [])
    # Limits and membership come from the same input tables as the optimizer.
    projects = projects.drop(columns=["allocation_unit_id", "physical_cap_kaf"]).join(
        limits.set_index("project_id")[["allocation_unit_id", "physical_cap_kaf"]],
    )
    groups = shared_limits(projects, units, relationships)
    script = output.parent / "plotly.min.js"
    script.write_text(get_plotlyjs(), encoding="utf-8")
    style = (
        "body{max-width:1200px;margin:24px auto;padding:0 20px;font:16px system-ui;color:#243142}"
        "nav a{display:inline-block;margin:0 1em .5em 0}section{border-top:1px solid #ddd;margin-top:1.5em}"
        ".table{overflow:auto}table{border-collapse:collapse}th,td{padding:.45em .75em;border-bottom:1px solid #ddd}"
        "th:first-child{position:sticky;left:0;background:#fff;text-align:left;white-space:nowrap}"
        "td{text-align:right}thead{background:#f1f5f9}details{margin:1em 0}"
    )

    def write_page(path, title, content):
        path.write_text(
            '<!doctype html><html lang="en"><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>{title}</title><style>{style}</style><h1>{title}</h1>{content}</html>', encoding="utf-8",
        )

    nav = "<nav>" + "".join(f'<a href="{prefix}_{code}.html">{code} · {COMPONENTS[code]}</a>' for code in targets) + "</nav>"
    for code, table in targets.items():
        figures = []
        for key, project in projects.iterrows():
            fig = build_figure(project, rules[key], ratings[key], colors, {code: table}, show_axis_controls=False)
            inactive = "<p>FIRO is inactive at this reservoir for this alternative.</p>" if table[project.project_name].isna().all() else ""
            figures.append("<section>" + inactive + fig.to_html(
                full_html=False, include_plotlyjs=False, config={"responsive": True, "displaylogo": False},
            ) + "</section>")
        write_page(
            output.with_name(f"{prefix}_{code}.html"), f"{prefix}_{code} · {COMPONENTS[code]}",
            '<script src="plotly.min.js"></script>' + nav + source_details.get(code, "")
            + "<p>Maximum achieved is the peak daily storage above the rule curve. Control-point values sum "
              "upstream reservoirs on the same day before taking the peak.</p>"
            + constraint_table(projects, rules, ratings, table, groups)
            + '<p><label for="axis">Even tick increments </label><select id="axis">'
              '<option value="0">Storage (KAF)</option><option value="1">Elevation (ft)</option>'
              '</select></p>' + "".join(figures)
            + '<script>document.querySelector("#axis").addEventListener("change", function () {'
              'for (const chart of document.querySelectorAll(".js-plotly-plot")) {'
              'const [data, layout] = chart.layout.updatemenus[0].buttons[Number(this.value)].args;'
              'Plotly.update(chart, data, layout);'
              '}});</script>',
        )
    write_page(output, "FIRO alternatives", nav)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    default = ROOT / "outputs/diagnostics/progressive_wat_csvs"
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--curves", type=Path)
    source.add_argument("--watershed", type=Path, help="Read installed PGFIRO overrides and plot all reservoirs")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--review", action="store_true", help="Write one review page per generated alternative")
    args = parser.parse_args()
    curves = args.curves or default
    projects, rules, ratings, colors = load_plot_inputs()
    names = projects.project_name.tolist()
    filename = "index.html" if args.watershed or args.review else "lookout_point_firo_components.html"
    output = args.output or curves / filename
    output.parent.mkdir(parents=True, exist_ok=True)
    if args.watershed:
        watershed = args.watershed.resolve()
        targets, sources = installed_targets(watershed, names)
        details = {
            case[-1]: f"<details><summary>Installed CSV</summary>{escape(str(path))} · SHA-256 {checksum[:12]}</details>"
            for case, _, path, checksum in sources
        }
        write_alternative_review(output, projects, rules, ratings, colors, targets, details)
        print(f"Verified {len(sources)} installed override/CSV pairs and plotted {len(projects)} reservoirs.")
    else:
        targets = {
            code: read_targets(curves / f"FIRO_SPACEConfig_Progressive_{code}.csv", names)[0]
            for code in COMPONENTS
        }
        if args.review:
            write_alternative_review(output, projects, rules, ratings, colors, targets, {})
        else:
            project = projects.loc["LOOKOUT_POINT"]
            figure = build_figure(project, rules[project.name], ratings[project.name], colors, targets)
            figure.write_html(output, include_plotlyjs=True, config={"responsive": True, "displaylogo": False})
    print(f"FIRO component plot: {output.resolve()}")


if __name__ == "__main__":
    main()
