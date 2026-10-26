# Willamette FIRO

```text
FIRO_COMPONENTS/                 Component allocation, curves and review packages
DELAYED_DRAWDOWN_SCREENING/      Component J screening with ResSim output
ROUTING_RAMP_EVACUATION/         Travel times, release ramps and evacuation times
RULE_CURVE_WORKSHOP/            Workshop diagrams and exploratory plots
shared/                        Shared source datasets, pending reconciliation
    common_data/               Existing common datasets, retained separately
    modules/                   Shared Python utilities
Archive/2026-10-26_pre_FIRO_COMPONENTS/
    original_repository/       Tracked snapshot immediately before the FIRO upload
    retired_root_folders/      Former root config, docs and out folders
```

Each active workflow has its own source and output folders. See its README for execution and required external inputs. The three separated workflows resolve their paths from the script location; moving utilities into shared/modules does not require a special working directory or PYTHONPATH. FIRO_COMPONENTS retains its own derived data and generated review packages; its scripts resolve their project directory from __file__.

The previous root data folder was renamed to shared, with dataset contents preserved. Legacy files and common_data remain separate pending authoritative-source review. No storage-rating or rule-curve datasets have been reconciled or removed.

The pre-upload archive is a historical reference, not an active workflow. Its original names and paths are intentionally preserved. See its README and snapshot manifest for provenance. It does not include unpushed or ignored files from anyone's PC.

Generated outputs and caches of the three separated workflows are ignored. External ResSim, SharePoint and temporary data under shared remain ignored. Dependency setup is unchanged; use the prepared Python environment for development.
