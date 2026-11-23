"""Build one WAT FIRO-space CSV per implemented component across all projects."""

import argparse
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


def write_elevation_review(review, projects, rule_curves, exports, ratings):
    """Overlay the actual WAT elevation targets on the model's rule curves."""
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    directory = review / "elevation_overlays"
    directory.mkdir(parents=True, exist_ok=True)
    days = pd.date_range("2001-01-01", "2001-12-31")
    calendar = pd.MultiIndex.from_arrays([days.month, days.day], names=["Month", "Day"])
    project_names = projects.set_index("project_id")["project_name"]
    elevations = {}
    for project_id, name in project_names.items():
        rule = rule_curves[project_id].copy()
        rule.index = pd.MultiIndex.from_arrays(
            [rule.index.month, rule.index.day], names=calendar.names
        )
        elevations[name] = rule.reindex(calendar)
        if not np.isfinite(elevations[name]).all():
            raise ValueError(f"Missing rule-curve elevations for {name}")

    links = []
    for alternative_id, (code, targets) in enumerate(exports.items(), start=1):
        titles = [name if targets[name].notna().any() else f"{name} (no FIRO target)"
                  for name in project_names]
        rows = (len(titles) + 2) // 3
        figure = make_subplots(
            rows=rows, cols=3, subplot_titles=titles, horizontal_spacing=0.13,
            specs=[[{"secondary_y": True} for _ in range(3)] for _ in range(rows)],
        )
        target_legend = True
        for index, (project_id, name) in enumerate(project_names.items()):
            row, col = divmod(index, 3)
            panel = {"row": row + 1, "col": col + 1}
            rule = elevations[name]
            target = targets[name]
            figure.add_trace(go.Scatter(
                x=days, y=rule, name="Rule curve", mode="lines",
                line={"color": "#303b4a"}, legendgroup="rule", showlegend=index == 0,
                hovertemplate="Rule curve %{y:.2f} ft<extra></extra>",
            ), secondary_y=True, **panel)
            if target.notna().any():
                figure.add_trace(go.Scatter(
                    x=days, y=target, name="WAT FIRO target", mode="lines",
                    line={"color": "#087f8c", "width": 3}, connectgaps=False,
                    legendgroup="target", showlegend=target_legend,
                    hovertemplate="WAT FIRO target %{y:.2f} ft<extra></extra>",
                ), secondary_y=True, **panel)
                target_legend = False
            figure.update_xaxes(dtick="M3", tickformat="%b", hoverformat="%b %d", **panel)
            lower, upper = min(rule.min(), target.min()), max(rule.max(), target.max())
            spacing = max((upper - lower) / 5, 1)
            magnitude = 10 ** np.floor(np.log10(spacing))
            interval = next(step * magnitude for step in (1, 2, 5, 10) if step * magnitude >= spacing)
            first = np.floor(lower / interval) * interval
            last = max(first + interval, np.ceil(upper / interval) * interval)
            ticks = np.arange(first, last + interval / 2, interval)
            rating = ratings[project_id]
            mapped = np.interp(ticks, rating.elevation_ft, rating.storage_kaf)
            storage_labels = [
                f"{value:,.1f}" if rating.elevation_ft.min() <= tick <= rating.elevation_ft.max() else ""
                for tick, value in zip(ticks, mapped)
            ]
            limits = [first, last]
            figure.update_yaxes(range=limits, tickvals=ticks, ticksuffix=" ft", secondary_y=True, **panel)
            elevation_axis = figure.get_subplot(row + 1, col + 1, secondary_y=True).yaxis.plotly_name
            figure.update_yaxes(range=limits, matches=elevation_axis.replace("axis", ""),
                                tickvals=ticks, ticktext=storage_labels, ticksuffix=" KAF",
                                showgrid=False, secondary_y=False, **panel)
        figure.update_layout(
            title=f"Component {code} · rule curves and WAT FIRO targets",
            template="plotly_white", height=260 * rows + 80,
            legend={"orientation": "h", "y": 1.09},
            margin={"l": 90, "r": 75, "t": 115, "b": 65},
        )
        filename = f"component_{code}.html"
        figure.write_html(directory / filename, include_plotlyjs="directory")
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
        'Left labels give the rated storage in thousand acre-feet at those same elevations.</p>'
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
