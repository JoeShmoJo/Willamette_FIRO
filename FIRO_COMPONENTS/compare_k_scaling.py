"""Compare fixed-shape Component K scaling with day and hour refill advances."""

import argparse
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import linprog

from run import ROOT


TOLERANCE = 1e-6
HOURS_PER_DAY = 24


def load_module(filename):
    spec = spec_from_file_location(Path(filename).stem, ROOT / "src" / filename)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def local_curve(builder, project, rule, rating, hours, increment):
    daily_storage = rule.map(lambda elevation: builder.elevation_to_storage_kaf(elevation, rating))
    start, merge, minimum, maximum = builder.component_k_vertices(project, rule, daily_storage, rating)
    start *= HOURS_PER_DAY
    merge *= HOURS_PER_DAY
    daily_hours = np.arange(len(rule)) * HOURS_PER_DAY
    baseline = np.interp(hours, daily_hours, daily_storage)
    # Interpolate between the existing daily rule-limb vertices after
    # applying the same MinCon and MaxCon endpoints as the daily builder.
    rising_daily = daily_storage.copy()
    rising_daily.iloc[start // HOURS_PER_DAY] = minimum
    rising_daily.iloc[merge // HOURS_PER_DAY:] = maximum
    rising = np.interp(hours, daily_hours, rising_daily)
    best_area = 0.0
    best_shift = 0
    best = np.zeros_like(baseline)
    for shift in range(increment, min(start, merge - start) + 1, increment):
        active_hours = hours[start - shift:merge + 1]
        offsets = rising[np.minimum(active_hours + shift, merge)] - baseline[active_hours]
        if offsets.min() < -TOLERANCE or offsets.max() > project.physical_cap_kaf + TOLERANCE:
            continue
        candidate = np.zeros_like(baseline)
        candidate[active_hours] = np.maximum(offsets, 0)
        area = np.trapz(candidate, dx=1 / HOURS_PER_DAY)
        if area > best_area + TOLERANCE:
            best, best_area, best_shift = candidate, area, shift
    if best_shift == 0:
        raise ValueError(f"No positive K curve fits the local limit for {project.project_name}")
    return best, best_shift, best_area


def shared_limits(projects, units, relationships):
    links = relationships.groupby(["control_point_id", "control_point_name", "space_limit_kaf"])
    constraints = [
        (point_id, name, limit, projects.allocation_unit_id.isin(group.decision_unit_id).to_numpy())
        for (point_id, name, limit), group in links
    ]
    constraints.extend(
        (unit.decision_unit_id, unit.decision_unit_name, unit.physical_cap_kaf, members.to_numpy())
        for unit in units.itertuples()
        if (members := projects.allocation_unit_id.eq(unit.decision_unit_id)).sum() > 1
    )
    return constraints


def optimize(projects, units, relationships, builder, rules, ratings, increment, destination):
    # Evaluate both alternatives on the same hourly grid so the comparison
    # isolates permissible advance increments rather than sampling frequency.
    hours = np.arange(len(builder.DATES) * HOURS_PER_DAY)
    curves, shifts, areas = zip(*[
        local_curve(builder, project, rules[project_id], ratings[project_id], hours, increment)
        for project_id, project in projects.iterrows()
    ])
    offsets = np.column_stack(curves)
    groups = shared_limits(projects, units, relationships)
    coefficients = np.concatenate([offsets * members for _, _, _, members in groups])
    budgets = np.repeat([limit for _, _, limit, _ in groups], len(hours))
    unscaled = coefficients.sum(axis=1)
    relevant = unscaled > 0
    ratios = budgets[relevant] / unscaled[relevant]
    floor = min(1.0, float(ratios.min()))
    row = np.flatnonzero(relevant)[ratios.argmin()]
    location, moment = divmod(row, len(hours))
    time = builder.DATES[0] + pd.to_timedelta(hours, unit="h")
    result = linprog(
        -np.asarray(areas), A_ub=coefficients[relevant], b_ub=budgets[relevant],
        bounds=[(floor, 1.0)] * len(projects), method="highs",
    )
    if not result.success:
        raise RuntimeError(result.message)
    scaled = offsets * result.x
    if (coefficients @ result.x > budgets + TOLERANCE).any():
        raise RuntimeError("Optimized curves exceed a shared limit")
    if (scaled.max(axis=0) > projects.physical_cap_kaf.to_numpy() + TOLERANCE).any():
        raise RuntimeError("Optimized curves exceed a reservoir limit")

    report = projects[["project_name", "physical_cap_kaf"]].copy()
    report["local_advance_hours"] = shifts
    report["local_kaf_days"] = areas
    report["retained_fraction"] = result.x
    report["scaled_kaf_days"] = np.asarray(areas) * result.x
    report["scaled_peak_kaf"] = scaled.max(axis=0)
    report.to_csv(destination / f"k_{increment}h_reservoirs.csv")
    limit_rows = []
    for key, name, limit, members in groups:
        loading = scaled[:, members].sum(axis=1)
        peak = int(loading.argmax())
        limit_rows.append((key, name, limit, loading[peak], time[peak]))
    pd.DataFrame(limit_rows, columns=[
        "limit_id", "location", "limit_kaf", "peak_kaf", "peak_time",
    ]).to_csv(destination / f"k_{increment}h_limits.csv", index=False)

    return {
        "advance_increment_hours": increment,
        "highest_common_floor": floor,
        "floor_constraint": groups[location][1] if floor < 1 else "None",
        "floor_constraint_time": time[moment] if floor < 1 else "",
        "local_total_kaf_days": sum(areas),
        "common_scale_only_kaf_days": floor * sum(areas),
        "optimized_kaf_days": -result.fun,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/diagnostics/k_scaling_comparison")
    args = parser.parse_args()
    allocator = load_module("01_allocate_static_firo_space.py")
    builder = load_module("02_build_component_curves.py")
    projects, units, control_points, _, network = allocator.load_inputs()
    projects = projects.set_index("project_id")
    issues = []
    _, relationships = allocator.build_control_point_relationships(network, control_points, issues)
    rule_table = pd.read_csv(builder.RULE_CURVES_FILE, encoding="utf-8-sig")
    rating_table = pd.read_csv(builder.STORAGE_ELEVATION_FILE).rename(columns={"Elev": "elevation_ft"})
    rating_table["project_id"] = rating_table.Reservoir.map(builder.canonical_id)
    rating_table["storage_kaf"] = rating_table.Stor / 1000
    rules = builder.build_rule_curve_lookup(rule_table, issues)
    ratings = builder.build_rating_lookup(rating_table, issues)
    if any(issue["severity"] == "ERROR" for issue in issues):
        raise ValueError(f"Invalid model inputs: {issues}")
    args.output.mkdir(parents=True, exist_ok=True)
    summary = pd.DataFrame([
        optimize(projects, units, relationships, builder, rules, ratings, increment, args.output)
        for increment in (HOURS_PER_DAY, 1)
    ])
    summary.to_csv(args.output / "summary.csv", index=False)
    print(summary.to_string(index=False, float_format=lambda value: f"{value:,.4f}"))
    print(f"Reports: {args.output.resolve()}")


if __name__ == "__main__":
    main()
