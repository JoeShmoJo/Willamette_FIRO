# MAX FIRO Space — current source wiring

MAX calculates storage/evacuation capacities and statistical downstream limits.
FIRO_COMPONENTS performs alternative allocation, redistribution and component
geometry. The earlier overlapping code remains commented in Sam's scripts.

## Active input sources

| Information | Source now used |
| --- | --- |
| Elevation-storage ratings | shared/common_data/ElevStor.csv |
| Minimum/maximum conservation elevations | shared/common_data/Reservoirs.xlsx, Reservoirs sheet, header row 6 |
| Evacuation times and remaining project settings | MAX_FIRO_SPACE/data/project_data.csv (uploaded snapshot) |
| Event-volume samples for statistical control-point limits | MAX_FIRO_SPACE/data/available_volume.pkl — still missing |

Paths are resolved from space_limits.py, so the working directory does not
matter. The shared CSV is adapted to the column names used by the original
capacity functions; storage stays in acre-feet until the existing KAF conversion.
The functions themselves have not been rewritten.

The old config.xlsx/control_points read and weighted-lag-file read are commented
because their loaded results were unused by the remaining calculations. Their
original lines and the weighted-lag helper remain available for review. A missing
config.xlsx or lag CSV no longer blocks this capacity script solely for unused
reads. Shared reservoir metadata supplies the conservation elevations; the local
project snapshot still supplies DaysToEvac, defined as the time to evacuate 20%
of conservation storage. No new evacuation-time calculation is implied.

## Source change versus saved results

The uploaded files in data/ are historical snapshots. They have not been
recomputed or overwritten by the source-path update. In particular:

- Existing project/control-point limits and legacy summaries are not certified
  as results of the selected shared rating source.
- Cached ConStorageKAF and SevenDayEvacuationVolumeKAF columns are ignored on
  input and recomputed in memory from selected ratings and supplied DaysToEvac.
- The unused local storage_elevation.xlsx is the earlier rating source, not the
  active one. Local DSS/pickle rule curves are not read by active capacity work.
- This change does not yet reconnect FIRO to new MAX output tables. FIRO still
  uses its supplied capacity parameters and existing shared control-point limits.

The source difference is measurable. Holding the supplied DaysToEvac fixed,
Green Peter calculates to 249.900 KAF conservation storage and about 85.721 KAF
seven-day evacuation volume, versus 258.774 and 88.765 KAF in the uploaded
snapshot. Treat source selection as a real data change, not just a file rename.

## Current execution status

```sh
python MAX_FIRO_SPACE/space_limits.py
```

The script stops with a named missing-input error until data/available_volume.pkl
is supplied. It expects a dictionary keyed by control point, with each table
containing available_volume_kaf samples. The upstream sampling process and its
settings still need to be identified. No source data, snapshots or FIRO results
are overwritten by the current script; the old export statements remain disabled.

One unresolved calculation detail remains: the original 90% exceedance setting
is selected by positional indexing of a table indexed 1–99, which currently
selects its 91% row. That code was preserved in this source-only change and
needs resolution before publishing newly calculated control-point limits.

Next steps are to establish explicit output tables/provenance and reconnect the
FIRO consumers, then remove redundant source/result copies from the wider tree.
The src/data/outputs folder reorganization is also deferred here so Sam's script
locations and original calculation structure remain recognizable.
