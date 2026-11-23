"""Plot the progressive WAT FIRO curves for Lookout Point on one figure."""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go

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


def build_figure(curves):
    builder = load_module("02_build_component_curves.py")
    project_id = "LOOKOUT_POINT"
    projects = pd.read_csv(builder.PHYSICAL_PROJECTS_FILE).set_index("project_id")
    project = projects.loc[project_id]
    issues = []
    rule = builder.build_rule_curve_lookup(pd.read_csv(builder.RULE_CURVES_FILE), issues)[project_id]
    raw_rating = pd.read_csv(builder.STORAGE_ELEVATION_FILE)
    rating = raw_rating.loc[raw_rating.Reservoir.eq(project.project_name), ["Elev", "Stor"]].dropna()
    rating = rating.sort_values("Elev").drop_duplicates("Elev", keep="last")
    if issues or len(rating) < 2:
        raise ValueError(f"Invalid Lookout Point model inputs: {issues}")

    min_con_storage = np.interp(project.min_con_elev_ft, rating.Elev, rating.Stor)

    def storage_above_mincon(elevation):
        return (np.interp(elevation, rating.Elev, rating.Stor) - min_con_storage) / 1000

    days = rule.index
    calendar = pd.MultiIndex.from_arrays([days.month, days.day], names=["Month", "Day"])
    colors = {**load_module("03_cap_validate_and_plot_curves.py").COMPONENT_COLORS, "M": "#00857c"}
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
    limits = [rule.min(), rule.max(), project.spillway_crest_elev_ft]
    for code, label in COMPONENTS.items():
        path = curves / f"FIRO_SPACEConfig_Progressive_{code}.csv"
        target = pd.read_csv(path).set_index(["Month", "Day"])[project.project_name].reindex(calendar)
        if not target.notna().any():
            raise ValueError(f"No Lookout Point targets in {path}")
        limits.extend([target.min(), target.max()])
        figure.add_trace(go.Scatter(
            x=days, y=target, yaxis="y2", mode="lines", name=f"{code} · {label}",
            line={"color": colors[code], "width": 2.4}, connectgaps=False,
            customdata=storage_above_mincon(target),
            hovertemplate="%{y:,.2f} ft · %{customdata:,.1f} KAF above MinCon<extra>%{fullData.name}</extra>",
        ))
    crest = project.spillway_crest_elev_ft
    figure.add_trace(go.Scatter(
        x=[days[0], days[-1]], y=[crest, crest], yaxis="y2", mode="lines",
        name=f"Spillway crest ({crest:g} ft)", line={"color": "#a1aab6", "dash": "dash", "width": 1.4},
        hovertemplate="Spillway crest %{y:.1f} ft<extra></extra>",
    ))
    # Use elevations as plotting coordinates on both sides. Only the left
    # tick labels are converted, so the nonlinear rating remains aligned.
    step = 10
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
        title={"text": "Lookout Point · FIRO component curves", "x": 0.04},
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    default = ROOT / "outputs/diagnostics/progressive_wat_csvs"
    parser.add_argument("--curves", type=Path, default=default)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = args.output or args.curves / "lookout_point_firo_components.html"
    figure = build_figure(args.curves)
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.write_html(output, include_plotlyjs=True, config={"responsive": True, "displaylogo": False})
    print(f"Lookout Point component plot: {output.resolve()}")


if __name__ == "__main__":
    main()
