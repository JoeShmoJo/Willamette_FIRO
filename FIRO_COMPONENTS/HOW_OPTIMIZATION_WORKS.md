# How the FIRO component combinations are optimized

The program evaluates combinations that are specified in the input tables.
It chooses some component parameters automatically and separately optimizes
how much static FIRO space to allocate across participating reservoirs.
It does not search all possible combinations to choose the best alternative.

There are three steps to understand: the space budget, the component shapes,
and the combined curve.

## 1. Give each participating reservoir a space budget

The alternative/component-selection table says which reservoirs and components
participate. The current active component codes are A, C, E, H, I, J and K;
F and G are deferred.

Script 01 calculates an initial allocation:

1. At each applicable downstream control point, divide the available space
   among participating upstream allocation units in proportion to their
   conservation storage.
2. Give each unit the smallest of its applicable downstream shares and its
   physical/evacuation-space cap.
3. Where Hills Creek and Lookout Point participate as a combined allocation
   unit, divide its allocation among active physical members using the
   existing conservation-storage-based split.

This initial allocation is a proportional allocation rule. It is the baseline
space budget used to construct the current daily curves.

### Separately optimize unused allocation capacity

Script 05 asks: **Can more total space be allocated while keeping all existing
baseline allocations and satisfying the static limits?**

It uses two passes:

- **Pass 1: maximize total allocated space.** Each allocation unit can increase
  from its baseline allocation up to its physical cap. At each applicable
  control point, the sum of upstream allocations must fit within that point's
  space limit. A linear-programming solver, HiGHS, finds the maximum total for
  this mathematical problem, subject to numerical tolerances.
- **Pass 2: distribute the additions.** Keep that maximum total and favor
  additions proportional to conservation storage. The code minimizes squared
  differences from those target allocations, scaling differences by available
  headroom with a minimum scale of 1 KAF. SLSQP performs this refinement. If it
  fails, the maximum-total solution from Pass 1 is retained and flagged.

No unit is allowed to lose its baseline allocation. Hills Creek/Lookout Point
physical member allocations retain their existing split fractions; the solver
does not separately optimize that split.

KAF means thousand acre-feet. Each participating upstream unit's allocation
counts once at each applicable downstream control point. This calculation
uses static volumes, not daily routed releases or component timing.

## 2. Fit component shapes to the baseline space budget

Script 02 constructs each selected component separately, using the project's
rule curve, elevation/storage rating, seasonal dates and allocation. Storage
ratings are loaded from shared/common_data/ElevStor.csv; static control-point
limits come from shared/control_points_space.csv.

The budget limits additional storage above the ordinary rule curve. It is not
a separate budget assigned to every component and then added together.

| Component | How its parameters are chosen |
| --- | --- |
| A: flat winter pool | Set the pool from minimum conservation storage plus the allocation; find its intersections with the falling and rising rule curve. This is a calculated shape, not a general optimizer. |
| C: straight refill | Calculate a start date using the allocation and prescribed refill geometry; connect minimum conservation elevation to the rule curve at the slope-change date. |
| E: rise to maximum conservation | Test candidate daily arrival dates at maximum conservation. Reject curves below the rule curve, above maximum conservation, or above the allocation cap. Choose the largest feasible peak additional space; use total KAF-days as the tie-breaker. |
| H: refill through spillway crest | Calculate an inflection around spillway crest and the allocation; search for the earliest permissible minimum-conservation start for the prescribed lower leg. |
| I: refill through April 1 | Set an April 1 target from rule-curve storage plus the allocation, capped at maximum conservation; search for the earliest permissible minimum-conservation start. |
| J: delayed rule curve | Calculate a nominal delay, then test whole-day delays from that value downward. Keep the first delay whose peak positive offset fits the allocation. This is the largest feasible delay within that search window. |
| K: advanced refill limb | Test positive whole-day advances of the rising rule curve and keep the candidate with the largest feasible peak offset. Equal peaks retain the first encountered candidate. |

For H and I, the start-date search requires the lower leg to stay on/above the
rule curve without exceeding the inflection-point offset. Prescribed fallback
behavior is used if the intended geometry cannot be constructed. Parameter
tables and quality outputs record geometry assumptions and exceptions.

KAF-days measures how much additional space exists and how long it lasts:
10 KAF for 20 days is 200 KAF-days. E uses that measure only to break ties in
peak space; it is not the system-wide objective.

These searches choose parameters within the specified shape families and
date windows on the daily grid. They do not vary every component parameter
freely or jointly optimize all reservoir curves.

## 3. Combine the selected components using the highest curve each day

For each reservoir and day, the combined curve is the highest of the ordinary
rule curve and the selected component curves.

For example, if A permits 40 KAF above the rule curve and E permits 60 KAF on
the same day, their combination permits 60 KAF, not 100 KAF. If A is higher in
winter and E is higher in spring, each can control a different part of the year.

There is no additional combination optimizer at this step. The component
selection is already specified, and the program takes the daily upper envelope.
Script 03 caps individual component storage at the rule curve plus the project
allocation and recomputes capped combined curves and validation outputs.

## What the current results show

The saved redistribution summary reports:

| Case | Baseline total | Redistributed total | Meaning |
| --- | ---: | ---: | --- |
| Alternative 1 | 202.044 KAF | 219.193 KAF | About 17.149 KAF of additional static allocation |
| Other modeled alternatives | About 219.193 KAF | About 219.193 KAF | Essentially no additional allocation; differences near 0.000001 KAF are numerical tolerance |

These are saved allocation results, not sums of daily space or simulated
operational benefits. All eight modeled alternatives report successful
optimization passes in the saved summary. Alternative 5 has no component
selection rows and is absent from the daily/model results.

The standalone curve builder reads baseline physical allocations from output 25.
The review runner now uses script 15 to invoke the same geometry/capping code
separately with output 25 (before) and output 43 (after). The retained charts let
you toggle between these rebuilt cases; allocation limits, dates and controllers
follow the selected case. This reconnects the existing allocation optimization
to the plotted curves without changing the optimization objective or introducing
a joint component-combination optimizer.

## Scope of the word optimized

- Individual components: some are calculated from rules; others use targeted
  daily parameter searches with component-specific selection criteria.
- Combined reservoir curves: daily upper envelopes of the input-selected
  components, followed by allocation capping.
- Redistributed allocations: maximum total static space within the stated
  bounds and downstream-volume constraints, with a proportional refinement.
- Alternative/component selection and operational performance: specified or
  evaluated separately, rather than selected by these optimization routines.

The routines do not optimize routed flood outcomes, water-supply reliability,
temperature, habitat performance or operational release schedules. The daily
review products are unrouted storage-space screening products.

## Where to look

- `data/12_alternative_component_selections.csv`: specified combinations.
- `outputs/24_alternative_decision_unit_allocations.csv` and
  `25_alternative_physical_project_allocations.csv`: baseline budgets.
- `outputs/30_component_parameters.csv`: selected component dates/parameters.
- `outputs/36_project_combined_daily_curves_capped.csv`: capped combinations.
- `outputs/41_redistributed_decision_unit_allocations.csv` and
  `43_redistributed_physical_project_allocations.csv`: optimized allocations.
- `outputs/47_redistribution_optimization_summary.csv`: totals and solver status.

Implementation: scripts 01 (baseline), 02 (geometry), 03 (capping), and
05 (redistribution). This explanation describes their current code and saved
results; it does not represent a new model run.
