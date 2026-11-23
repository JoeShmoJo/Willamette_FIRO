"""Build one WAT FIRO-space CSV per implemented component across all projects."""

import argparse
from html import escape
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory

import numpy as np
import pandas as pd

from run import ROOT


H_PROJECTS = {"GREEN_PETER", "DETROIT", "LOOKOUT_POINT"}


def export_curves(model, destination, codes, projects, builder, ratings):
    exports = {}
    capped_components = pd.read_csv(
        model / "outputs/diagnostics/scenarios/after/35_component_daily_curves_capped.csv",
        parse_dates=["date"],
    )
    days = pd.date_range("2001-01-01", "2001-12-31")
    calendar = pd.MultiIndex.from_arrays([days.month, days.day], names=["Month", "Day"])
    project_names = projects.set_index("project_id")["project_name"]
    for alternative_id, code in enumerate(codes, start=1):
        source = model / f"outputs/final/alternative_{alternative_id:02d}_combined_curves.csv"
        curves = pd.read_csv(source, parse_dates=["date"])
        curves["Month"] = curves["date"].dt.month
        curves["Day"] = curves["date"].dt.day
        coverage = curves.groupby("project_id").size()
        expected = H_PROJECTS if code == "H" else set(project_names.index)
        if set(coverage.index) != expected or not coverage.eq(len(days)).all():
            raise ValueError(f"Component {code} lacks a full year for its applicable projects")
        # Leave days controlled by the ordinary rule curve blank in ResSim.
        active = curves["combined_offset_kaf"] > 1e-8
        if not curves.loc[active, "controlling_component"].eq(code).all():
            raise ValueError(f"Component {code} has unexpected controlling components")
        if (curves["combined_offset_kaf"] > curves["allocated_project_firo_space_kaf"] + 1e-6).any():
            raise ValueError(f"Component {code} exceeds its project allocation")
        curves["target"] = np.nan
        for project, rows in curves.groupby("project_id"):
            storage = rows.loc[active.loc[rows.index], "combined_storage_kaf"]
            rating = ratings[project]
            elevations = storage.map(lambda value: builder.storage_kaf_to_elevation(value, rating))
            recovered = elevations.map(lambda value: builder.elevation_to_storage_kaf(value, rating))
            if not np.allclose(recovered, storage, atol=1e-6, rtol=0):
                raise ValueError(f"Component {code}, {project}: elevation conversion changed storage")
            curves.loc[elevations.index, "target"] = elevations
        if code in {"J", "K"}:
            # Keep the zero-offset MinCon contact visible and in the WAT target.
            component = capped_components.loc[
                (capped_components["alternative_id"] == alternative_id)
                & capped_components["component_storage_kaf"].notna()
            ].sort_values("date")
            groups = component.groupby("project_id")
            contacts = groups.tail(1) if code == "J" else groups.head(1)
            min_con = projects.set_index("project_id")["min_con_elev_ft"]
            for contact in contacts.itertuples():
                at_contact = curves["project_id"].eq(contact.project_id) & curves["date"].eq(contact.date)
                if active.loc[at_contact].any():
                    continue
                elevation = min_con.loc[contact.project_id]
                storage = builder.elevation_to_storage_kaf(elevation, ratings[contact.project_id])
                if abs(storage - contact.rule_storage_kaf) <= 1e-6:
                    curves.loc[at_contact, "target"] = elevation

        wide = curves.pivot(index=["Month", "Day"], columns="project_id", values="target")
        if not wide.index.equals(calendar):
            raise ValueError(f"Component {code} lacks the expected non-leap calendar")
        if set(wide.columns[wide.notna().any()]) != expected:
            raise ValueError(f"Component {code} lacks active targets for its applicable projects")
        exports[code] = wide.reindex(columns=project_names.index).rename(columns=project_names)

    destination.mkdir(parents=True, exist_ok=True)
    for code, wide in exports.items():
        path = destination / f"FIRO_SPACEConfig_Component_{code}.csv"
        wide.to_csv(path)
        print(f"{path}: {len(wide)} days, {len(wide.columns)} reservoirs, "
              f"{wide.notna().sum().sum()} populated targets")

    return exports


def reservoir_allocation_summary(project, unit, peak, point_ids):
    """Explain the budget above a reservoir's final curve."""
    baseline = project.baseline_project_firo_space_kaf
    assigned = project.redistributed_project_firo_space_kaf
    physical = project.project_physical_cap_kaf
    used = peak.combined_offset_kaf
    scale = max(physical, assigned, used, 1e-6)
    metrics = (
        ("Initial share", baseline),
        ("Final allocation", assigned),
        ("Peak curve use", used),
        ("Physical limit", physical),
    )
    cards = "".join(f"<div><dt>{label}</dt><dd>{value:,.2f}</dd></div>" for label, value in metrics)
    binding = [
        f'<a href="#{point_ids[name]}">{escape(name)}</a>'
        for name in str(unit.redistributed_limiting_control_points).split("|")
        if name in point_ids
    ]
    reasons = []
    if binding:
        reasons.append("Allocation constrained by fully assigned downstream space at " + ", ".join(binding))
    if unit.effective_physical_cap_kaf - unit.redistributed_firo_space_kaf <= 1e-6:
        reasons.append("Physical limit reached" if unit.active_member_count == 1 else
                       f"Combined physical limit reached: {escape(unit.decision_unit_name)}")
    if assigned < physical - 1e-6 and not reasons:
        reasons.append("No linked downstream allocation is at its limit.")
    if unit.active_member_count > 1:
        reasons.append(f"Shares a budget with {escape(unit.decision_unit_name)} "
                       f"({project.project_split_fraction:.1%} of the combined allocation).")
    peak_note = f" · {used / assigned:.1%} used on {peak.date:%b %d}" if assigned > 0 else ""
    if assigned - used > 1e-6:
        reasons.append(f"Curve peaks {assigned - used:,.2f} KAF below its allocation.")
    return (
        f'<dl class="budget">{cards}</dl>'
        '<div class="gauge" aria-hidden="true">'
        f'<span class="used" style="width:{used / scale:.5%}"></span>'
        f'<span class="assigned" style="left:{assigned / scale:.5%}"></span></div>'
        f'<p class="note">Bar: peak use. Marker: final allocation. Full scale: physical limit{peak_note}.</p>'
        f'<p class="note">{" · ".join(reasons)}</p>'
    )


def control_point_breakdown(point, peak, upstream, on_peak_day, individual_peaks):
    """Separate unused reservoir shares from peaks that occur on different dates."""
    rows = []
    assigned = upstream.redistributed_project_firo_space_kaf
    individual = individual_peaks.loc[upstream.index, "combined_offset_kaf"]
    concurrent = on_peak_day.loc[upstream.index, "combined_offset_kaf"]
    if not np.isclose(concurrent.sum(), peak.unrouted_control_point_loading_kaf, rtol=0, atol=1e-6):
        raise ValueError(f"Reservoir contributions do not match {point.control_point_name} daily loading")
    if not np.isclose(assigned.sum(), point.allocated_firo_space_kaf, rtol=0, atol=1e-6):
        raise ValueError(f"Reservoir allocations do not match the allocation at {point.control_point_name}")

    for project_id in upstream.sort_values("project_name").index:
        project = upstream.loc[project_id]
        own_peak = individual_peaks.loc[project_id]
        share = assigned.loc[project_id]
        used = concurrent.loc[project_id]
        rows.append(
            f'<tr><th scope="row">{escape(project.project_name)}</th>'
            f'<td>{share:,.2f}</td><td>{own_peak.combined_offset_kaf:,.2f} ({own_peak.date:%b %d})</td>'
            f'<td>{used:,.2f}</td><td>{max(0, share - used):,.2f}</td></tr>'
        )
    unused = max(0, assigned.sum() - individual.sum())
    timing = max(0, individual.sum() - concurrent.sum())
    available = max(0, point.space_limit_kaf - assigned.sum())
    return (
        '<details><summary>What accounts for the gap?</summary>'
        f'<p>On <strong>{peak.date:%b %d}</strong>, the combined curve use peaked at '
        f'<strong>{concurrent.sum():,.2f} KAF</strong> of this point’s '
        f'<strong>{point.space_limit_kaf:,.2f} KAF</strong> limit.</p>'
        '<ul>'
        f'<li>Space never assigned: <strong>{available:,.2f} KAF</strong>.</li>'
        f'<li>Assigned space the individual reservoir curves never reach: <strong>{unused:,.2f} KAF</strong>.</li>'
        f'<li>Space lost when individual peaks do not coincide: <strong>{timing:,.2f} KAF</strong>.</li>'
        '</ul><div class="table-scroll"><table><thead><tr><th>Upstream reservoir</th>'
        '<th>Assigned (KAF)</th><th>Own peak (KAF and date)</th>'
        f'<th>Use on {peak.date:%b %d} (KAF)</th><th>Unused share that day (KAF)</th>'
        '</tr></thead><tbody>' + "".join(rows) + '</tbody></table></div></details>'
    )


def write_elevation_review(review, projects, rule_curves, exports, ratings):
    """Overlay the actual WAT elevation targets on the model's rule curves."""
    import plotly.graph_objects as go
    from plotly.offline import get_plotlyjs

    directory = review / "elevation_overlays"
    directory.mkdir(parents=True, exist_ok=True)
    days = pd.date_range("2001-01-01", "2001-12-31")
    calendar = pd.MultiIndex.from_arrays([days.month, days.day], names=["Month", "Day"])
    project_names = projects.set_index("project_id")["project_name"]
    min_con = projects.set_index("project_id")["min_con_elev_ft"]
    elevations = {}
    for project_id, name in project_names.items():
        rule = rule_curves[project_id].copy()
        rule.index = pd.MultiIndex.from_arrays(
            [rule.index.month, rule.index.day], names=calendar.names
        )
        elevations[name] = rule.reindex(calendar)
        if not np.isfinite(elevations[name]).all():
            raise ValueError(f"Missing rule-curve elevations for {name}")

    (directory / "plotly.min.js").write_text(get_plotlyjs(), encoding="utf-8")
    model = review.parent / "scenarios/model"
    after = review.parent / "scenarios/after/capacity_status"
    projects_by_case = pd.read_csv(model / "43_redistributed_physical_project_allocations.csv").groupby("alternative_id")
    units_by_case = pd.read_csv(model / "41_redistributed_decision_unit_allocations.csv").groupby("alternative_id")
    points_by_case = pd.read_csv(model / "46_control_point_utilization_redistributed.csv").groupby("alternative_id")
    relationships = pd.read_csv(model / "21_static_control_point_relationships.csv")
    upstream_units = relationships.groupby("control_point_id")["decision_unit_id"].agg(set)
    reservoir_daily = pd.read_csv(after / "01_reservoir_daily_capacity_status.csv", parse_dates=["date"])
    reservoir_dates = reservoir_daily.set_index(["alternative_id", "date", "project_id"]).sort_index()
    point_daily = pd.read_csv(after / "02_control_point_daily_capacity_status.csv", parse_dates=["date"])
    reservoir_peak = reservoir_daily.loc[
        reservoir_daily.groupby(["alternative_id", "project_id"])["combined_offset_kaf"].idxmax()
    ].set_index(["alternative_id", "project_id"])
    point_peak = point_daily.loc[
        point_daily.groupby(["alternative_id", "control_point_id"])["unrouted_control_point_loading_kaf"].idxmax()
    ].set_index(["alternative_id", "control_point_id"])
    links = []
    for alternative_id, (code, targets) in enumerate(exports.items(), start=1):
        allocations = projects_by_case.get_group(alternative_id).set_index("project_id")
        units = units_by_case.get_group(alternative_id).set_index("decision_unit_id")
        points = points_by_case.get_group(alternative_id)
        point_ids = {row.control_point_name: f"point-{row.control_point_id}" for row in points.itertuples()}
        point_rows = []
        for point in points.itertuples():
            peak = point_peak.loc[alternative_id, point.control_point_id]
            at_limit = "Fully assigned" if point.unused_control_point_space_kaf <= 1e-6 else ""
            upstream = allocations.loc[allocations.decision_unit_id.isin(upstream_units.loc[point.control_point_id])]
            breakdown = control_point_breakdown(
                point, peak, upstream, reservoir_dates.loc[(alternative_id, peak.date)],
                reservoir_peak.loc[alternative_id],
            )
            point_rows.append(
                f'<tr id="{point_ids[point.control_point_name]}"><th scope="row">{escape(point.control_point_name)}</th>'
                f'<td>{point.space_limit_kaf:,.2f}</td><td>{point.allocated_firo_space_kaf:,.2f}</td>'
                f'<td>{point.utilization_fraction:.1%}</td>'
                f'<td>{peak.unrouted_control_point_loading_kaf:,.2f} ({peak.control_point_utilization_percent:.1f}%)</td>'
                f'<td>{peak.date:%b %d}</td><td>{at_limit}</td></tr>'
                f'<tr class="breakdown"><td colspan="7">{breakdown}</td></tr>'
            )
        panels = []
        for project_id, name in project_names.items():
            rule = elevations[name]
            target = targets[name]
            lower, upper = min(rule.min(), target.min()), max(rule.max(), target.max())
            spacing = max((upper - lower) / 5, 1)
            magnitude = 10 ** np.floor(np.log10(spacing))
            interval = next(step * magnitude for step in (1, 2, 5, 10) if step * magnitude >= spacing)
            first = np.floor(lower / interval) * interval
            last = max(first + interval, np.ceil(upper / interval) * interval)
            ticks = np.arange(first, last + interval / 2, interval)
            rating = ratings[project_id]
            min_con_storage = np.interp(min_con.loc[project_id], rating.elevation_ft, rating.storage_kaf)
            mapped = np.interp(ticks, rating.elevation_ft, rating.storage_kaf) - min_con_storage
            storage_labels = [
                f"{value:,.1f}" if rating.elevation_ft.min() <= tick <= rating.elevation_ft.max() else ""
                for tick, value in zip(ticks, mapped)
            ]
            # Plot both curves in elevation coordinates. Mount the left axis
            # with an invisible point and relabel it with the rating values.
            figure = go.Figure()
            figure.add_trace(go.Scatter(
                x=[days[0]], y=[first], yaxis="y", mode="markers", opacity=0,
                showlegend=False, hoverinfo="skip",
            ))
            figure.add_trace(go.Scatter(
                x=days, y=rule, yaxis="y2", name="Rule curve", mode="lines",
                line={"color": "#303b4a"},
                hovertemplate="Rule curve %{y:.2f} ft<extra></extra>",
            ))
            has_target = target.notna().any()
            if has_target:
                figure.add_trace(go.Scatter(
                    x=days, y=target, yaxis="y2", name="WAT FIRO target", mode="lines",
                    line={"color": "#087f8c", "width": 3}, connectgaps=False,
                    hovertemplate="WAT FIRO target %{y:.2f} ft<extra></extra>",
                ))
            axis_scale = {"range": [first, last], "tickmode": "array", "tickvals": ticks, "fixedrange": True}
            figure.update_layout(
                template="plotly_white", height=320, autosize=True,
                xaxis={"dtick": "M3", "tickformat": "%b", "hoverformat": "%b %d"},
                yaxis={**axis_scale, "side": "left", "title": "Storage above MinCon (KAF)",
                       "ticktext": storage_labels, "showgrid": False},
                yaxis2={**axis_scale, "side": "right", "title": "Elevation (ft)", "overlaying": "y", "anchor": "x"},
                legend={"orientation": "h", "y": 1.03, "yanchor": "bottom", "font": {"size": 11}},
                margin={"l": 77, "r": 77, "t": 58, "b": 45},
            )
            chart = figure.to_html(full_html=False, include_plotlyjs=False, config={"responsive": True})
            budget = '<p class="note">No FIRO allocation for this component</p>'
            if project_id in allocations.index:
                project = allocations.loc[project_id]
                budget = reservoir_allocation_summary(
                    project, units.loc[project.decision_unit_id],
                    reservoir_peak.loc[alternative_id, project_id], point_ids,
                )
            panels.append(f'<section><h2>{escape(name)}</h2>{budget}{chart}</section>')

        filename = f"component_{code}.html"
        initial = allocations.baseline_project_firo_space_kaf.sum()
        final = allocations.redistributed_project_firo_space_kaf.sum()
        solver = escape(str(units.optimization_solver.iloc[0]))
        (directory / filename).write_text(
            '<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>Component {code} rule curves</title><script src="plotly.min.js"></script>'
            '<style>body{margin:24px;font:16px system-ui;color:#243142}'
            'main{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,490px),1fr));gap:20px}'
            'section{min-width:0;border:1px solid #dce2e8;border-radius:8px}'
            'section h2{margin:12px 16px 0;font-size:18px}.note{margin:6px 16px;color:#536477;font-size:13px}'
            '.budget{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin:12px 16px;font-size:12px}'
            '.budget dd{margin:2px 0 0;font-size:17px;font-weight:600}'
            '.gauge{margin:8px 16px;position:relative;height:10px;background:#e6edf1;border-radius:4px}'
            '.used{display:block;height:100%;background:#087f8c;border-radius:4px}'
            '.assigned{position:absolute;top:-3px;bottom:-3px;border-left:2px solid #674399}'
            'table{border-collapse:collapse;width:100%;margin-bottom:20px}'
            'th,td{padding:6px 12px;border-bottom:1px solid #dce2e8;text-align:left}'
            'tr:target{background:#fff1c8}.table-scroll{overflow-x:auto}'
            '.breakdown>td{padding:6px 12px 12px 24px}.breakdown table{margin-bottom:0}'
            'summary{cursor:pointer}'
            '</style></head><body><p><a href="index.html">All components</a></p>'
            f'<h1>Component {code} rule curves and WAT FIRO targets</h1>'
            f'<p>System allocation: {initial:,.2f} → {final:,.2f} KAF '
            f'(+{final - initial:,.2f} KAF). Reservoir card values are in KAF.</p>'
            '<details><summary>How the allocation is calculated</summary>'
            '<p>The model starts with proportional shares, then maximizes total assigned space within '
            'reservoir and downstream limits. A second pass tries to distribute the gains proportionally.</p>'
            f'<p>{solver}</p></details><p><a href="#downstream">Downstream control-point limits</a></p>'
            '<main>' + "".join(panels) + '</main>'
            '<h2 id="downstream">Downstream control-point limits</h2>'
            '<p>Static allocation is the sum of the assigned shares. Daily peak use is the maximum '
            'combined unrouted storage offset on a single day.</p>'
            '<div class="table-scroll"><table><thead><tr><th>Control point</th><th>Limit (KAF)</th>'
            '<th>Assigned (KAF)</th><th>Assigned %</th><th>Daily peak (KAF and %)</th>'
            '<th>Peak date</th><th>Allocation status</th></tr></thead><tbody>'
            + "".join(point_rows) + '</tbody></table></div>'
            '<script>function openPoint(){'
            'const row=document.getElementById(location.hash.slice(1));'
            'if(row && row.matches("tr[id^=point-]")) row.nextElementSibling.querySelector("details").open=true;'
            '}window.addEventListener("hashchange",openPoint);'
            'window.addEventListener("load", () => {openPoint();'
            'document.querySelectorAll(".js-plotly-plot").forEach(plot => Plotly.Plots.resize(plot));'
            '});</script></body></html>',
            encoding="utf-8",
        )
        utilization = f"../utilization_ribbon_overview/alternative_{alternative_id:02d}_utilization_ribbon_overview.html"
        links.append(
            f'<li>Component {code} · <a href="{filename}">Rule curves and FIRO targets</a>'
            f' · <a href="{utilization}">Reservoir draft and downstream space use</a></li>'
        )

    (directory / "index.html").write_text(
        '<!doctype html><meta charset="utf-8"><title>FIRO rule-curve overlays</title>'
        '<h1>Rule curves and WAT FIRO targets</h1>'
        '<p>The dark line is the model rule curve. The teal line is the target '
        'from the exported WAT CSV after reallocation. Gaps indicate days '
        'without a WAT FIRO target. Right ticks are evenly spaced elevations in feet. '
        'Left labels give storage above MinCon in thousand acre-feet at those same elevations.</p>'
        '<ul>' + "".join(links) + '</ul><p><a href="../index.html">Back to review</a></p>',
        encoding="utf-8",
    )
    landing = review / "index.html"
    html = landing.read_text(encoding="utf-8")
    index = '<h2>Review Files</h2>'
    html = html.replace(index, index + '\n<p><a href="elevation_overlays/index.html">'
                        'Rule curves with WAT FIRO target elevations</a></p>', 1)
    landing.write_text(html, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/wat_components")
    parser.add_argument(
        "--review", action="store_true",
        help="Keep the interactive component, reservoir and control-point diagnostics",
    )
    args = parser.parse_args()

    # Use the normal model in a temporary tree so the system-alternative inputs
    # and outputs remain available alongside these single-component cases.
    with TemporaryDirectory(prefix="firo-wat-") as temporary:
        workspace = Path(temporary)
        model = workspace / ROOT.name
        for directory in ("data", "src"):
            shutil.copytree(ROOT / directory, model / directory, ignore=shutil.ignore_patterns("__pycache__"))
        for filename in ("run.py", "output_layout.py"):
            shutil.copy2(ROOT / filename, model / filename)
        for relative in (
            "shared/common_data/ElevStor.csv",
            "MAX_FIRO_SPACE/out/ControlPointsSpace.csv",
            "MAX_FIRO_SPACE/out/ReservoirEvacLimits.csv",
        ):
            target = workspace / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT.parent / relative, target)

        spec = spec_from_file_location("firo_cases", model / "src/15_build_reallocation_comparison.py")
        cases = module_from_spec(spec)
        spec.loader.exec_module(cases)
        allocator = cases.load_script("01_allocate_static_firo_space.py")
        builder = cases.load_script("02_build_component_curves.py")
        codes = sorted(allocator.ACTIVE_COMPONENT_CODES)
        projects = pd.read_csv(allocator.PHYSICAL_PROJECTS_FILE)
        selections = [
            {
                "alternative_id": alternative_id,
                "alternative_name": f"WAT Component {code}",
                "project_id": project,
                "component_code": code,
                "active_for_current_phase": True,
            }
            for alternative_id, code in enumerate(codes, start=1)
            for project in projects["project_id"]
            if code != "H" or project in H_PROJECTS
        ]
        pd.DataFrame(selections).to_csv(allocator.ALTERNATIVE_SELECTIONS_FILE, index=False)
        stage = "all" if args.review else "model"
        subprocess.run([sys.executable, str(model / "run.py"), stage], check=True)
        builder.PHYSICAL_ALLOCATIONS_FILE = (
            model / "outputs/diagnostics/scenarios/model/25_alternative_physical_project_allocations.csv"
        )
        _, raw_rules, raw_ratings, _, _ = builder.load_inputs()
        issues = []
        ratings = builder.build_rating_lookup(raw_ratings, issues)
        rule_curves = builder.build_rule_curve_lookup(raw_rules, issues) if args.review else None
        if issues:
            raise ValueError(f"Invalid curve inputs: {issues}")
        exports = export_curves(model, args.output, codes, projects, builder, ratings)
        if args.review:
            write_elevation_review(model / "outputs/diagnostics/review", projects, rule_curves, exports, ratings)
            # Keep the relative links between the review and its curve tables.
            for directory in ("diagnostics", "final"):
                shutil.copytree(model / "outputs" / directory, args.output / directory, dirs_exist_ok=True)
            print(f"WAT component review: {args.output / 'diagnostics/review/index.html'}")


if __name__ == "__main__":
    main()
