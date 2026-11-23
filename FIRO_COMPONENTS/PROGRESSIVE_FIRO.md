# Progressive FIRO scaling

Each WAT alternative uses one component. A, C, E, I, J, and K use the
11 modeled reservoirs. H uses Green Peter, Detroit, and Lookout Point.
Dexter and Big Cliff are pass-through reservoirs.

## The math

1. Build a locally feasible curve for each eligible reservoir. Keep the
   candidate with the most KAF-days. Each curve is represented as the
   daily storage above the ordinary rule curve.
2. For every control point and time, sum the unscaled space at the
   contributing reservoirs. Divide the point's limit by that total.
   Ignore times with zero loading. The smallest ratio, capped at 100%,
   is the highest starting factor that works everywhere. Also check the
   combined Lookout Point–Hills Creek cap.
3. Give every reservoir that starting factor. At the first binding point
   and time, hold the factors of the reservoirs that contribute positive
   space there. Increase the other factors together until a new limit
   binds or the factors reach 100%. Keep checking every limit as factors
   increase, including the limits that bound earlier.
4. A reservoir gets one factor for its entire curve. Multiply every daily
   storage offset by that factor, add it to rule-curve storage, and convert
   the result back to elevation using that reservoir's rating.

## A two-day example

A and B count against Jefferson and Salem. C counts against Salem only.
These starting curves already fit their individual reservoir limits.

| Reservoir | Day 1 space | Day 2 space |
| --- | ---: | ---: |
| A | 40 KAF | 10 KAF |
| B | 60 KAF | 30 KAF |
| C | 60 KAF | 80 KAF |

Jefferson's limit is 60 KAF. Salem's limit is 108 KAF.

| Check | Limit divided by unscaled space |
| --- | ---: |
| Jefferson, Day 1 | 60 ÷ (40 + 60) = **60%** |
| Jefferson, Day 2 | 60 ÷ (10 + 30) = 150% |
| Salem, Day 1 | 108 ÷ (40 + 60 + 60) = 67.5% |
| Salem, Day 2 | 108 ÷ (10 + 30 + 80) = 90% |

Jefferson on Day 1 binds first, at **60%**. Hold A and B there.
Their Day 1 loading at Salem is now 60 KAF, leaving 48 KAF for C.
C has 60 KAF on Day 1 before scaling, so Salem lets C rise to
**48 ÷ 60 = 80%**. Day 2 still fits.

| Check | Day 1 after scaling | Day 2 after scaling |
| --- | ---: | ---: |
| Jefferson | 60 KAF | 24 KAF |
| Salem | 108 KAF | 88 KAF |

**Final factors: A = 60%, B = 60%, C = 80%.** For two one-day periods,
C keeps 112 of its original 140 KAF-days. With only the common factor,
C would keep 84 KAF-days. Progressive filling adds 28 KAF-days at C
while A and B keep their full common-factor shares.

## WAT cases

From the Willamette_FIRO repository root, pass a destination directory to
`python FIRO_COMPONENTS/compare_k_scaling.py --wat-csvs DIRECTORY`. This runs
all components and writes seven progressive elevation CSVs. Whole-day K is used
for WAT. The comparison report also includes the whole-hour K experiment.

With WAT closed, run
`python FIRO_COMPONENTS/install_progressive_wat.py WATERSHED DIRECTORY`
from the same repository root. The installer uses the study's existing
`FIRO_Test_FIROSpace` case as a template, checks its analysis period and
ResSim selection, and backs up the study before registering
`PGFIRO_A`, `PGFIRO_C`, `PGFIRO_E`, `PGFIRO_H`, `PGFIRO_I`,
`PGFIRO_J`, and `PGFIRO_K`. It refuses to overwrite a differing case file.

Open the watershed in WAT and select a `PGFIRO_*-POR_1935-2019` simulation.
Check that it uses `ALL_D` and that the initialization log names the matching
`FIRO_SPACEConfig_Progressive_*.csv`. The sizing constraints use unrouted
storage offsets. Flood performance is evaluated in the routed compute.
Scaling the storage offsets can change the exact shifted shape of J or K.

## Constant-offset benchmark

The `PGFIRO_M` benchmark adds a constant storage offset to each reservoir's
ordinary rule curve, with the target capped at MaxCon. This makes a flat
MaxCon segment that joins the ordinary rule curve. The offset is constant in
storage units; its elevation difference can vary with the reservoir rating.

Progressive filling adjusts the constant offset for each reservoir before
the MaxCon cap is applied. When a control point binds at a time when a
reservoir is already at MaxCon, a larger offset cannot increase that
reservoir's contribution there. The reservoir can continue growing where
all constraints permit. The solve checks individual reservoir limits,
downstream points, and the combined Lookout Point–Hills Creek cap.

Run `compare_k_scaling.py --max-offset --wat-csvs DIRECTORY`, then
`install_progressive_wat.py WATERSHED DIRECTORY --max-offset` to add only
`PGFIRO_M-POR_1935-2019`. The benchmark uses all 11 modeled reservoirs.

## Lookout Point illustration

Run `python FIRO_COMPONENTS/plot_lookout_point.py --curves DIRECTORY` after
generating A, C, E, H, I, J, K, and M. Open the resulting
`lookout_point_firo_components.html`. Click a legend entry to toggle it or
double-click to isolate it. The left axis shows storage above MinCon using
the rating at the same evenly spaced right-axis elevation ticks. The dashed
line marks the 887.5 ft spillway crest.

## Early spillway geometry for H

H tests crest dates in order. A date is feasible when the storage difference
from the rule curve at the crest fits the project limit and both straight
elevation legs fit on every day. The upper leg goes from the crest to the
first normal MaxCon refill day. For the earliest feasible crest, the lower
leg starts as early as possible while the ordinary curve is at MinCon.
The builder checks storage using the reservoir rating and reports when no
two-leg curve fits. It does not use a winter-pool fallback.

The H export uses the project physical limit when choosing dates. It checks
the shared limits before export, since scaling below full size would move
the crest vertex. Run `compare_k_scaling.py --only-h --wat-csvs DIRECTORY`
to regenerate only H. For a new H case, add `--only-h` to the installer.
For an existing case, back up and replace only its progressive H CSV.
