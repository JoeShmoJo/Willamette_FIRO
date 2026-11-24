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
        if code in {"E", "J", "K"}:
            # Include the zero-offset contact with the rule curve in the WAT target.
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
                if code == "E":
                    storage = contact.component_storage_kaf
                    elevation = builder.storage_kaf_to_elevation(storage, ratings[contact.project_id])
                else:
                    elevation = min_con.loc[contact.project_id]
                    storage = builder.elevation_to_storage_kaf(elevation, ratings[contact.project_id])
                if abs(storage - contact.rule_storage_kaf) <= 1e-6:
                    curves.loc[at_contact, "target"] = elevation

        wide = curves.pivot(index=["Month", "Day"], columns="project_id", values="target")
        if not wide.index.equals(calendar):
            raise ValueError(f"Component {code} lacks the expected non-leap calendar")
        missing = expected - set(wide.columns[wide.notna().any()])
        if missing:
            if code != "I":
                raise ValueError(f"Component {code} lacks active targets for its applicable projects")
            names = ", ".join(project_names.loc[sorted(missing)])
            print(f"Component I has no feasible shape under the fixed allocation at: {names}")
        exports[code] = wide.reindex(columns=project_names.index).rename(columns=project_names)

    destination.mkdir(parents=True, exist_ok=True)
    for code, wide in exports.items():
        path = destination / f"FIRO_SPACEConfig_Component_{code}.csv"
        wide.to_csv(path)
        print(f"{path}: {len(wide)} days, {len(wide.columns)} reservoirs, "
              f"{wide.notna().sum().sum()} populated targets")

    return exports


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/wat_components")
    parser.add_argument(
        "--review", action="store_true",
        help="Write one plot and constraint review page per alternative",
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
        subprocess.run([sys.executable, str(model / "run.py"), "model"], check=True)
        builder.PHYSICAL_ALLOCATIONS_FILE = (
            model / "outputs/diagnostics/scenarios/model/25_alternative_physical_project_allocations.csv"
        )
        _, raw_rules, raw_ratings, _, _ = builder.load_inputs()
        issues = []
        ratings = builder.build_rating_lookup(raw_ratings, issues)
        rule_curves = builder.build_rule_curve_lookup(raw_rules, ratings, issues) if args.review else None
        if issues:
            raise ValueError(f"Invalid curve inputs: {issues}")
        exports = export_curves(model, args.output, codes, projects, builder, ratings)
        if args.review:
            from plot_lookout_point import write_alternative_review

            review = args.output / "diagnostics/review/index.html"
            review.parent.mkdir(parents=True, exist_ok=True)
            colors = cases.load_script("03_cap_validate_and_plot_curves.py").COMPONENT_COLORS
            write_alternative_review(review, projects.set_index("project_id"), rule_curves, ratings,
                                     colors, exports, {}, prefix="FIRO")
            print(f"WAT component review: {review.resolve()}")


if __name__ == "__main__":
    main()
