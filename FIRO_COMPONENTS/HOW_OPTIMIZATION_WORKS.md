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
and seven-day evacuation limits come from MAX_FIRO_SPACE/out/ControlPointsSpace.csv
and MAX_FIRO_SPACE/out/ReservoirEvacLimits.csv, respectively.

The budget limits additional storage above the ordinary rule curve. It is not
a separate budget assigned to every component and then added together.

### Component definitions

| Component | How its parameters are chosen |
| --- | --- |
| A: flat winter pool | Set the pool from minimum conservation storage plus the allocation; find its intersections with the falling and rising rule curve. This is a calculated shape, not a general optimizer. |
| C: straight refill | Calculate a start date using the allocation and prescribed refill geometry; connect minimum conservation elevation to the rule curve at the slope-change date. |
| E: rise to maximum conservation | From the refill slope change (March 1 if none is configured), test straight elevation legs to MaxCon and select the largest feasible peak, with KAF-days as the tie-breaker. When the straight leg yields no positive feasible curve, use the MaxCon target clipped to the daily storage cap over the same refill window. |
| H: refill through spillway crest | Choose the earliest feasible spillway-crest day, then the earliest MinCon start that fits the storage limit along the lower leg. Both legs are straight in elevation and the second rejoins the ordinary curve at MaxCon. Applies only to Green Peter, Detroit, and Lookout Point. |
| I: refill through April 1 | Set an April 1 target from rule-curve storage plus the allocation, capped at MaxCon. Use the earliest feasible straight storage leg from MinCon. If that leg is infeasible, ramp up the additional storage from the last winter MinCon day to April 1. |
| J: delayed drawdown | Shift the falling rule limb later. Use the largest feasible delay up to the nominal delay and end the limb at MinCon. |
| K: advanced refill limb | Shift the rising rule limb earlier, including its MinCon start. Choose the candidate with the largest feasible peak offset and hold at MaxCon until the ordinary rule curve catches up. Equal peaks retain the first encountered candidate. |

For H and I, the start-date search requires the lower leg to stay on/above the
rule curve without exceeding the inflection-point offset. Prescribed fallback
behavior is used if the intended geometry cannot be constructed. Parameter
tables and quality outputs record geometry assumptions and exceptions. F and G have no
approved geometry in the current model. The single-component WAT exports cover
the 11 modeled reservoirs. Dexter and Big Cliff are pass-through reservoirs.

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

The saved redistribution summary reports the before and after static
allocations under the current limits. Alternative 5 has no component selection
rows and is absent from the daily/model results. These allocations are separate
from simulated operating results and the sum of daily curve offsets.

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
- `outputs/diagnostics/24_alternative_decision_unit_allocations.csv` and
  `25_alternative_physical_project_allocations.csv`: baseline budgets.
- `outputs/diagnostics/30_component_parameters.csv`: selected component dates/parameters.
- `outputs/diagnostics/36_project_combined_daily_curves_capped.csv`: capped combinations.
- `outputs/diagnostics/41_redistributed_decision_unit_allocations.csv` and
  `43_redistributed_physical_project_allocations.csv`: optimized allocations.
- `outputs/diagnostics/47_redistribution_optimization_summary.csv`: totals and solver status.

Implementation: scripts 01 (baseline), 02 (geometry), 03 (capping), and
05 (redistribution). This explanation describes their current code and saved
results; it does not represent a new model run.
