"""Compare common-factor, progressive, and total-area FIRO scaling."""

import argparse
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import linprog

from export_wat_components import H_PROJECTS
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


def progressive_filling(coefficients, budgets, floor):
    """Raise unfrozen fractions together until the next shared limit binds."""
    factors = np.full(coefficients.shape[1], floor, dtype=float)
    active = factors < 1
    while active.any():
        rates = coefficients[:, active].sum(axis=1)
        relevant = rates > 0
        step = 1 - factors[active].max()
        if relevant.any():
            slack = budgets[relevant] - coefficients[relevant] @ factors
            step = min(step, max(0, float((slack / rates[relevant]).min())))
        factors[active] += step
        binding = (budgets - coefficients @ factors <= TOLERANCE) & relevant
        frozen = (coefficients[binding] > 0).any(axis=0) | (factors >= 1 - 1e-10)
        if not (active & frozen).any():
            raise RuntimeError("Progressive filling did not reach a limit")
        active &= ~frozen
    return factors


def select_local_curve(builder, project, rule, rating, hours, code, samples):
    """Search allocation inputs to the existing component builder."""
    storage = rule.map(lambda elevation: builder.elevation_to_storage_kaf(elevation, rating))
    maximum = builder.elevation_to_storage_kaf(project.max_con_elev_ft, rating)
    best = None
    best_area = 0.0
    best_budget = 0.0
    daily_hours = np.arange(len(rule)) * HOURS_PER_DAY
    for budget in np.linspace(project.physical_cap_kaf / samples, project.physical_cap_kaf, samples):
        curve, _ = builder.build_component(code, project, budget, rule, storage, rating)
        if curve is None:
            continue
        # Apply the same daily allocation cap as the production curve review.
        offset = (curve - storage).fillna(0).clip(lower=0, upper=budget)
        offset = np.minimum(offset, (maximum - storage).clip(lower=0))
        hourly = np.interp(hours, daily_hours, offset)
        area = np.trapz(hourly, dx=1 / HOURS_PER_DAY)
        if area > best_area + TOLERANCE:
            best, best_budget, best_area = hourly, budget, area
    if best is None:
        raise ValueError(f"No positive {code} curve fits the local limit for {project.project_name}")
    return best, best_budget, best_area


def export_wat_curve(destination, code, projects, all_names, dates, offsets, builder, rules, ratings):
    """Convert the solved midnight offsets to the WAT generic-year elevation CSV."""
    targets = pd.DataFrame(index=dates, columns=all_names, dtype=float)
    for index, (project_id, project) in enumerate(projects.iterrows()):
        rating = ratings[project_id]
        rule = rules[project_id]
        base = rule.map(lambda elevation: builder.elevation_to_storage_kaf(elevation, rating))
        offset = offsets[::HOURS_PER_DAY, index]
        active = offset > 1e-8
        if not active.any():
            raise ValueError(f"No daily WAT targets for {code}, {project.project_name}")
        total = base.to_numpy() + offset
        values = np.full(len(dates), np.nan)
        values[active] = np.interp(total[active], rating.storage_kaf, rating.elevation_ft)
        if code == "M":
            max_storage = builder.elevation_to_storage_kaf(project.max_con_elev_ft, rating)
            flat = active & np.isclose(total, max_storage, rtol=0, atol=1e-8)
            values[flat] = project.max_con_elev_ft
            next_to_target = np.r_[active[1:], False] | np.r_[False, active[:-1]]
            contact = ~active & next_to_target & np.isclose(
                rule, project.max_con_elev_ft, rtol=0, atol=1e-8,
            )
            values[contact] = project.max_con_elev_ft
        if not np.allclose(
            np.interp(values[active], rating.elevation_ft, rating.storage_kaf),
            total[active], rtol=0, atol=TOLERANCE,
        ):
            raise ValueError(f"Rating round trip changed the scaled {code} curve at {project.project_name}")
        if code in {"J", "K"}:
            indices = np.flatnonzero(active)
            contact = indices[-1] + 1 if code == "J" else indices[0] - 1
            if 0 <= contact < len(dates) and np.isclose(
                rule.iloc[contact], project.min_con_elev_ft, rtol=0, atol=TOLERANCE
            ):
                values[contact] = project.min_con_elev_ft
        targets[project.project_name] = values
    targets.index = pd.MultiIndex.from_arrays([dates.month, dates.day], names=["Month", "Day"])
    destination.mkdir(parents=True, exist_ok=True)
    targets.sort_index().to_csv(destination / f"FIRO_SPACEConfig_Progressive_{code}.csv")


def optimize(projects, units, relationships, builder, rules, ratings, code, increment, samples, destination,
             wat_csvs=None):
    all_names = projects.project_name
    if code == "H":
        projects = projects.loc[projects.index.isin(H_PROJECTS)]
    # Evaluate both alternatives on the same hourly grid so the comparison
    # isolates permissible advance increments rather than sampling frequency.
    hours = np.arange(len(builder.DATES) * HOURS_PER_DAY)
    if code == "K":
        candidates = [
            local_curve(builder, project, rules[project_id], ratings[project_id], hours, increment)
            for project_id, project in projects.iterrows()
        ]
        parameter = "local_advance_hours"
        case = f"k_{increment}h"
    else:
        candidates = [
            select_local_curve(builder, project, rules[project_id], ratings[project_id], hours, code, samples)
            for project_id, project in projects.iterrows()
        ]
        parameter = "local_builder_budget_kaf"
        case = code.lower()
    curves, local_parameters, areas = zip(*candidates)
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
    progressive = progressive_filling(coefficients[relevant], budgets[relevant], floor)
    scaled = offsets * progressive
    if (progressive < floor - 1e-10).any() or (progressive > 1 + 1e-10).any():
        raise RuntimeError("Progressive scaling violates the common floor or full-size bound")
    for factors in (result.x, progressive):
        if (coefficients @ factors > budgets + TOLERANCE).any():
            raise RuntimeError("Optimized curves exceed a shared limit")
        if ((offsets * factors).max(axis=0) > projects.physical_cap_kaf.to_numpy() + TOLERANCE).any():
            raise RuntimeError("Optimized curves exceed a reservoir limit")

    report = projects[["project_name", "physical_cap_kaf"]].copy()
    report[parameter] = local_parameters
    report["local_kaf_days"] = areas
    report["retained_fraction"] = result.x
    report["scaled_kaf_days"] = np.asarray(areas) * result.x
    report["scaled_peak_kaf"] = (offsets * result.x).max(axis=0)
    report["common_fraction"] = floor
    report["common_kaf_days"] = np.asarray(areas) * floor
    report["progressive_fraction"] = progressive
    report["progressive_kaf_days"] = np.asarray(areas) * progressive
    report["progressive_peak_kaf"] = scaled.max(axis=0)
    report.to_csv(destination / f"{case}_reservoirs.csv")
    limit_rows = []
    for key, name, limit, members in groups:
        loading = scaled[:, members].sum(axis=1)
        peak = int(loading.argmax())
        common = offsets[:, members].sum(axis=1) * floor
        optimized = (offsets * result.x)[:, members].sum(axis=1)
        limit_rows.append((key, name, limit, optimized.max(), time[optimized.argmax()],
                           common.max(), loading[peak], time[peak]))
    pd.DataFrame(limit_rows, columns=[
        "limit_id", "location", "limit_kaf", "peak_kaf", "peak_time",
        "common_peak_kaf", "progressive_peak_kaf", "progressive_peak_time",
    ]).to_csv(destination / f"{case}_limits.csv", index=False)

    if wat_csvs is not None and (code != "K" or increment == HOURS_PER_DAY):
        export_wat_curve(wat_csvs, code, projects, all_names, builder.DATES, scaled, builder, rules, ratings)

    return {
        "component": code,
        "advance_increment_hours": increment if code == "K" else "",
        "highest_common_floor": floor,
        "floor_constraint": groups[location][1] if floor < 1 else "None",
        "floor_constraint_time": time[moment] if floor < 1 else "",
        "local_total_kaf_days": sum(areas),
        "common_scale_only_kaf_days": floor * sum(areas),
        "optimized_kaf_days": -result.fun,
        "progressive_kaf_days": report.progressive_kaf_days.sum(),
        "reservoirs_above_floor": int((progressive > floor + 1e-8).sum()),
    }


def fill_constant_offsets(headroom, physical_caps, members, limits):
    """Raise constant offsets together and stop contributors at binding times."""
    factors = np.zeros_like(physical_caps, dtype=float)
    active = physical_caps > 0

    def loads(trial):
        return np.minimum(headroom, physical_caps * trial) @ members.T

    while active.any():
        low = factors[active][0]
        high = 1.0
        trial = factors.copy()
        trial[active] = high
        if (loads(trial) <= limits + 1e-9).all():
            factors = trial
            break

        # Clipping at MaxCon makes the shared loads piecewise linear and
        # nondecreasing as the unfrozen reservoir factors rise together.
        for _ in range(50):
            middle = (low + high) / 2
            trial[active] = middle
            if (loads(trial) <= limits + 1e-9).all():
                low = middle
            else:
                high = middle
        factors[active] = low
        binding = limits - loads(factors) <= TOLERANCE
        # A pool already at MaxCon at the binding time cannot increase
        # loading there, so that pool can keep growing at other times.
        growing = (headroom > physical_caps * factors + 1e-8) & active
        frozen = ((binding.T.astype(int) @ growing.astype(int) > 0) & members).any(axis=0)
        if not frozen.any():
            raise RuntimeError("Constant-offset filling did not identify the next binding reservoir")
        active &= ~frozen

    offsets = np.minimum(headroom, physical_caps * factors)
    if (loads(factors) > limits + TOLERANCE).any():
        raise RuntimeError("Constant-offset curves exceed a shared limit")
    return factors, offsets


def run_max_offset(projects, units, relationships, builder, rules, ratings, destination, wat_csvs):
    hours = np.arange(len(builder.DATES) * HOURS_PER_DAY)
    daily_hours = hours[::HOURS_PER_DAY]
    daily_headroom = []
    for key, project in projects.iterrows():
        rating = ratings[key]
        rule_storage = np.interp(rules[key], rating.elevation_ft, rating.storage_kaf)
        max_storage = builder.elevation_to_storage_kaf(project.max_con_elev_ft, rating)
        daily_headroom.append(np.maximum(max_storage - rule_storage, 0))

    headroom = np.column_stack([np.interp(hours, daily_hours, room) for room in daily_headroom])
    groups = shared_limits(projects, units, relationships)
    limits = np.array([limit for _, _, limit, _ in groups])
    membership = np.stack([members for _, _, _, members in groups])
    caps = projects.physical_cap_kaf.to_numpy()
    factors, offsets = fill_constant_offsets(headroom, caps, membership, limits)
    report = projects[["project_name", "physical_cap_kaf"]].copy()
    report["retained_offset_fraction"] = factors
    report["constant_offset_kaf"] = caps * factors
    report["peak_kaf"] = offsets.max(axis=0)
    report["kaf_days"] = np.trapz(offsets, dx=1 / HOURS_PER_DAY, axis=0)
    report.to_csv(destination / "max_offset_reservoirs.csv")
    time = builder.DATES[0] + pd.to_timedelta(hours, unit="h")
    loads = offsets @ membership.T
    rows = []
    for i, (key, name, limit, _) in enumerate(groups):
        peak = int(loads[:, i].argmax())
        rows.append((key, name, limit, loads[peak, i], time[peak]))
    pd.DataFrame(rows, columns=[
        "limit_id", "location", "limit_kaf", "peak_kaf", "peak_time",
    ]).to_csv(destination / "max_offset_limits.csv", index=False)
    export_wat_curve(wat_csvs, "M", projects, projects.project_name, builder.DATES,
                     offsets, builder, rules, ratings)
    print(report[["project_name", "constant_offset_kaf", "kaf_days"]].to_string(
        index=False, float_format=lambda value: f"{value:,.2f}",
    ))
    print(f"Total: {report.kaf_days.sum():,.2f} KAF-days")
    print(f"Reports: {destination.resolve()}")
    print(f"Progressive WAT CSV: {(wat_csvs / 'FIRO_SPACEConfig_Progressive_M.csv').resolve()}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/diagnostics/k_scaling_comparison")
    parser.add_argument("--all-components", action="store_true", help="Also run A, C, E, H, I and J")
    parser.add_argument("--samples", type=int, default=24, help="Local budget samples for components other than K")
    parser.add_argument("--wat-csvs", type=Path, help="Export seven progressive WAT curves using whole-day K")
    parser.add_argument("--max-offset", action="store_true", help="Run only the constant-offset benchmark")
    args = parser.parse_args()
    if args.max_offset and args.wat_csvs is None:
        parser.error("--max-offset requires --wat-csvs")
    if args.samples < 1:
        parser.error("--samples must be positive")
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
    if args.max_offset:
        run_max_offset(projects, units, relationships, builder, rules, ratings, args.output, args.wat_csvs)
        return
    cases = [("K", HOURS_PER_DAY), ("K", 1)]
    if args.all_components or args.wat_csvs is not None:
        cases = [(code, HOURS_PER_DAY) for code in "ACEHIJ"] + cases
    summary = pd.DataFrame([
        optimize(projects, units, relationships, builder, rules, ratings, code, increment, args.samples,
                 args.output, args.wat_csvs)
        for code, increment in cases
    ])
    summary.to_csv(args.output / "summary.csv", index=False)
    print(summary.to_string(index=False, float_format=lambda value: f"{value:,.4f}"))
    print(f"Reports: {args.output.resolve()}")
    if args.wat_csvs is not None:
        print(f"Progressive WAT CSVs: {args.wat_csvs.resolve()}")


if __name__ == "__main__":
    main()
