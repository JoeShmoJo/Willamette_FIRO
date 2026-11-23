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


def export_curves(model, destination, codes, projects, builder, ratings):
    exports = {}
    days = pd.date_range("2001-01-01", "2001-12-31")
    calendar = pd.MultiIndex.from_arrays([days.month, days.day], names=["Month", "Day"])
    project_names = projects.set_index("project_id")["project_name"]
    for alternative_id, code in enumerate(codes, start=1):
        source = model / f"outputs/final/alternative_{alternative_id:02d}_combined_curves.csv"
        curves = pd.read_csv(source, parse_dates=["date"])
        curves["Month"] = curves["date"].dt.month
        curves["Day"] = curves["date"].dt.day
        coverage = curves.groupby("project_id").size()
        expected = set(project_names.index)
        if code == "H":
            # H needs a spillway crest. Keep the unavailable projects as blank columns.
            expected -= set(projects.loc[projects["spillway_crest_elev_ft"].isna(), "project_id"])
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
        wide = curves.pivot(index=["Month", "Day"], columns="project_id", values="target")
        if not wide.index.equals(calendar):
            raise ValueError(f"Component {code} lacks the expected non-leap calendar")
        exports[code] = wide.reindex(columns=project_names.index).rename(columns=project_names)

    destination.mkdir(parents=True, exist_ok=True)
    for code, wide in exports.items():
        path = destination / f"FIRO_SPACEConfig_Component_{code}.csv"
        wide.to_csv(path)
        print(f"{path}: {len(wide)} days, {len(wide.columns)} reservoirs, "
              f"{wide.notna().sum().sum()} populated targets")

    return exports


def write_elevation_review(review, projects, rule_curves, exports):
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
    for code, targets in exports.items():
        titles = [name if targets[name].notna().any() else f"{name} (no FIRO target)"
                  for name in project_names]
        rows = (len(titles) + 2) // 3
        figure = make_subplots(rows=rows, cols=3, subplot_titles=titles)
        target_legend = True
        for index, name in enumerate(project_names):
            row, col = divmod(index, 3)
            panel = {"row": row + 1, "col": col + 1}
            rule = elevations[name]
            target = targets[name]
            figure.add_trace(go.Scatter(
                x=days, y=rule, name="Rule curve", mode="lines",
                line={"color": "#303b4a"}, legendgroup="rule", showlegend=index == 0,
                hovertemplate="Rule curve %{y:.2f} ft<extra></extra>",
            ), **panel)
            if target.notna().any():
                figure.add_trace(go.Scatter(
                    x=days, y=target, name="WAT FIRO target", mode="lines",
                    line={"color": "#087f8c", "width": 3}, connectgaps=False,
                    legendgroup="target", showlegend=target_legend,
                    hovertemplate="WAT FIRO target %{y:.2f} ft<extra></extra>",
                ), **panel)
                target_legend = False
            figure.update_xaxes(dtick="M3", tickformat="%b", hoverformat="%b %d", **panel)
            figure.update_yaxes(ticksuffix=" ft", **panel)
        figure.update_layout(
            title=f"Component {code} · rule curves and WAT FIRO targets",
            template="plotly_white", height=260 * rows + 80,
            legend={"orientation": "h", "y": 1.04},
        )
        filename = f"component_{code}.html"
        figure.write_html(directory / filename, include_plotlyjs="directory")
        links.append(f'<li><a href="{filename}">Component {code}</a></li>')

    (directory / "index.html").write_text(
        '<!doctype html><meta charset="utf-8"><title>FIRO rule-curve overlays</title>'
        '<h1>Rule curves and WAT FIRO targets</h1>'
        '<p>The dark line is the model rule curve. The teal line is the target '
        'from the exported WAT CSV after reallocation. Gaps indicate days '
        'without a WAT FIRO target. Elevations are in feet.</p>'
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
            write_elevation_review(model / "outputs/diagnostics/review", projects, rule_curves, exports)
            # Keep the relative links between the review and its curve tables.
            for directory in ("diagnostics", "final"):
                shutil.copytree(model / "outputs" / directory, args.output / directory, dirs_exist_ok=True)
            print(f"WAT component review: {args.output / 'diagnostics/review/index.html'}")


if __name__ == "__main__":
    main()
