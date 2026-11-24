"""Fit component parameters jointly without changing the component geometry."""

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import csc_matrix, hstack, vstack


TOLERANCE = 1e-6


@dataclass
class Candidate:
    parameter: str
    elevation: np.ndarray
    offset: np.ndarray
    area: float


def local_candidates(builder, project, rule, rating, code, samples):
    days = rule.index
    baseline = rule.to_numpy()
    rate_elevation = rating.elevation_ft.to_numpy()
    rate_storage = rating.storage_kaf.to_numpy()
    rule_storage = np.interp(baseline, rate_elevation, rate_storage)
    low, high = project.min_con_elev_ft, project.max_con_elev_ft
    min_storage, max_storage = np.interp([low, high], rate_elevation, rate_storage)
    cap = project.physical_cap_kaf

    def index(field):
        return int(days.get_loc(builder.mmdd_to_model_date(project[field])))

    drawdown = index("drawdown_begins_mmdd")
    winter = index("drawdown_ends_mmdd")
    refill = index("start_refill_mmdd")
    end = index("hit_refill_mmdd")
    minima = np.flatnonzero(np.isclose(baseline[winter:refill + 1], low, rtol=0, atol=TOLERANCE)) + winter
    maxima = np.flatnonzero(np.isclose(baseline[refill:end + 1], high, rtol=0, atol=TOLERANCE)) + refill
    merge = int(maxima[0]) if maxima.size else end
    candidates = [Candidate("Rule curve", np.full(len(days), np.nan), np.zeros(len(days)), 0.0)]

    def record(first, values, parameter):
        last = first + len(values)
        base = rule_storage[first:last]
        planned = np.interp(values, rate_elevation, rate_storage)
        excess = planned - base
        if excess.max() > cap + TOLERANCE or np.max(values) > high + TOLERANCE:
            return
        # The ordinary rule curve applies on days when this component adds no space.
        active = excess > 1e-8
        if not active.any():
            return
        offset = np.zeros(len(days))
        offset[first:last] = np.where(active, excess, 0)
        target = np.full(len(days), np.nan)
        contact = np.abs(excess) <= 1e-8
        adjacent = np.r_[active[1:], False] | np.r_[False, active[:-1]]
        target[first:last] = np.where(active | (contact & adjacent), values, np.nan)
        candidates.append(Candidate(parameter, target, offset, np.trapz(offset)))

    if code == "A":
        local_maximum = min(cap, max_storage - min_storage)
        for room in np.linspace(local_maximum / samples, local_maximum, samples):
            pool = np.interp(min_storage + room, rate_storage, rate_elevation)
            record(drawdown, np.full(merge - drawdown + 1, pool), f"{pool:.3f} ft winter pool")
    elif code == "C":
        change = builder.mmdd_to_model_date(project.refill_slope_change_mmdd) or builder.mmdd_to_model_date("03-01")
        stop = int(days.get_loc(change))
        for start in minima[minima < stop]:
            values = np.linspace(min_storage, rule_storage[stop], stop - start + 1)
            record(start, np.interp(values, rate_storage, rate_elevation), f"refill starts {days[start]:%b %d}")
    elif code == "E":
        for start, top, values, _ in builder.component_e_candidates(
            project, rule, pd.Series(rule_storage, index=days), rating,
        ):
            record(start, np.interp(values, rate_storage, rate_elevation), f"MaxCon on {days[top]:%b %d}")
    elif code == "H":
        series, parameters = builder.build_component_h(
            project, cap, rule, pd.Series(rule_storage, index=days), rating,
        )
        valid = series.dropna()
        if not valid.empty:
            start = int(days.get_loc(valid.first_valid_index()))
            record(start, np.interp(valid, rate_storage, rate_elevation),
                   f"crest on {parameters['parameter_2_value']}")
    elif code == "I":
        storage = pd.Series(rule_storage, index=days)
        for advance, first, values, _, apex in builder.component_i_candidates(
            project, cap, rule, storage, rating,
        ):
            record(first, values, f"{advance} day advance; {apex:.3f} ft Apr 1")
    elif code == "J":
        minimum = int(np.flatnonzero(np.isclose(baseline[drawdown:merge], low, rtol=0, atol=TOLERANCE))[0] + drawdown)
        for delay in range(1, min(minimum - drawdown, refill - minimum) + 1):
            source = np.clip(np.arange(drawdown, minimum + delay + 1) - delay, 0, minimum)
            record(drawdown, baseline[source], f"{delay} day delay")
    elif code == "K":
        start, merge, _, _ = builder.component_k_vertices(
            project, rule, pd.Series(rule_storage, index=days), rating,
        )
        for advance in range(1, min(start, merge - start) + 1):
            source = np.minimum(np.arange(start - advance, merge + 1) + advance, merge)
            values = baseline[source].copy()
            values[0] = low
            values[source == merge] = high
            record(start - advance, values, f"{advance} day advance")

    if len(candidates) == 1:
        raise ValueError(f"No positive shape-preserving {code} candidate for {project.project_name}")
    return candidates


def choose_curves(candidates, groups):
    """Maximize the minimum retained area, then total area at that floor."""
    counts = np.array([len(pool) for pool in candidates])
    reservoir = np.repeat(np.arange(len(counts)), counts)
    choices = [choice for pool in candidates for choice in pool]
    areas = np.array([choice.area for choice in choices])
    local_best = np.array([max(choice.area for choice in pool) for pool in candidates])
    fractions = areas / local_best[reservoir]
    offsets = np.column_stack([choice.offset for choice in choices])
    one_per_reservoir = np.equal.outer(np.arange(len(counts)), reservoir)
    shared_rows, shared_limits = [], []
    for _, _, limit, members in groups:
        columns = members[reservoir]
        loads = offsets * columns
        largest = sum((offsets[:, reservoir == i].max(axis=1) for i in np.flatnonzero(members)),
                      start=np.zeros(len(offsets)))
        relevant = largest > limit
        shared_rows.append(csc_matrix(loads[relevant]))
        shared_limits.extend(np.full(int(relevant.sum()), limit))
    width = len(choices)
    constraints = [
        LinearConstraint(csc_matrix(one_per_reservoir), 1, 1),
        LinearConstraint(vstack(shared_rows, format="csc"), -np.inf, shared_limits),
    ]
    with_floor = [
        LinearConstraint(hstack([constraint.A, csc_matrix((constraint.A.shape[0], 1))], format="csc"),
                         constraint.lb, constraint.ub)
        for constraint in constraints
    ]
    retention = -(one_per_reservoir * fractions)
    with_floor.append(LinearConstraint(
        hstack([csc_matrix(retention), csc_matrix(np.ones((len(counts), 1)))], format="csc"), -np.inf, 0,
    ))
    first = milp(np.r_[np.zeros(width), -1.0], integrality=np.r_[np.ones(width), 0],
                 bounds=Bounds(0, 1), constraints=with_floor, options={"mip_rel_gap": 0})
    if not first.success:
        raise RuntimeError(f"Could not solve the common retention floor: {first.message}")
    floor = first.x[-1]
    if floor <= TOLERANCE:
        raise ValueError("Shared limits do not leave a positive component at every reservoir")
    allowable = (fractions >= floor - 1e-8).astype(float)
    final = milp(-areas, integrality=np.ones(width), bounds=Bounds(0, allowable),
                 constraints=constraints, options={"mip_rel_gap": 0})
    if not final.success:
        raise RuntimeError(f"Could not maximize area at the common floor: {final.message}")
    selected = np.flatnonzero(final.x > .5)
    if not np.array_equal(reservoir[selected], np.arange(len(candidates))):
        raise RuntimeError("Did not select exactly one curve per reservoir")
    return [choices[i] for i in selected], local_best, floor


def export_component(code, projects, names, groups, builder, rules, ratings, samples, curves):
    candidates = [
        local_candidates(builder, row, rules[key], ratings[key], code, samples)
        for key, row in projects.iterrows()
    ]
    chosen, local_best, floor = choose_curves(candidates, groups)
    offsets = np.column_stack([choice.offset for choice in chosen])
    if (offsets.max(axis=0) > projects.physical_cap_kaf.to_numpy() + TOLERANCE).any():
        raise ValueError(f"Component {code} exceeds a physical reservoir limit")
    for _, name, limit, members in groups:
        loading = offsets[:, members].sum(axis=1)
        peak = int(loading.argmax())
        if loading[peak] > limit + TOLERANCE:
            raise ValueError(f"Component {code} exceeds {name} on {builder.DATES[peak]}")
    totals = np.array([choice.area for choice in chosen])
    retained = totals / local_best
    if (retained < floor - 1e-8).any():
        raise ValueError(f"Component {code} failed to protect the common retention floor")
    dates = builder.DATES
    targets = pd.DataFrame(
        {row.project_name: choice.elevation for row, choice in zip(projects.itertuples(), chosen)},
        index=pd.MultiIndex.from_arrays([dates.month, dates.day], names=["Month", "Day"]),
    ).reindex(columns=names)
    targets.sort_index().to_csv(curves / f"FIRO_SPACEConfig_Progressive_{code}.csv")
    return {"component": code, "common_floor": floor, "system_kaf_days": totals.sum()}
