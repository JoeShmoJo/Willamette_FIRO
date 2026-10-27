"""Keep review rebuild inputs; make expendable calculation exports opt-in."""
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parent
DIAGNOSTICS = ROOT / 'outputs/diagnostics'
MODEL = DIAGNOSTICS / 'scenarios/model'
MODEL_EXPORTS = {
    '20_direct_control_point_assignments.csv',
    '21_static_control_point_relationships.csv',
    '22_alternative_active_decision_units.csv',
    '23_alternative_control_point_shares.csv',
    '24_alternative_decision_unit_allocations.csv',
    '25_alternative_physical_project_allocations.csv',
    '26_alternative_control_point_utilization.csv',
    '27_static_allocation_quality_report.csv',
    '30_component_parameters.csv',
    '31_component_daily_curves.csv',
    '32_project_combined_daily_curves.csv',
    '33_alternative_daily_storage_summary.csv',
    '34_component_curve_quality_report.csv',
    '35_component_daily_curves_capped.csv',
    '36_project_combined_daily_curves_capped.csv',
    '37_alternative_daily_storage_summary_capped.csv',
    '38_curve_cap_validation.csv',
    '39_curve_cap_quality_report.csv',
    '40_baseline_decision_unit_allocations.csv',
    '41_redistributed_decision_unit_allocations.csv',
    '42_baseline_physical_project_allocations.csv',
    '43_redistributed_physical_project_allocations.csv',
    '44_allocation_qaqc_summary.csv',
    '45_control_point_utilization_baseline.csv',
    '46_control_point_utilization_redistributed.csv',
    '47_redistribution_optimization_summary.csv',
}
MODEL_INPUTS = {
    '21_static_control_point_relationships.csv',
    '24_alternative_decision_unit_allocations.csv',
    '25_alternative_physical_project_allocations.csv',
    '27_static_allocation_quality_report.csv',
    '34_component_curve_quality_report.csv',
    '39_curve_cap_quality_report.csv',
    '41_redistributed_decision_unit_allocations.csv',
    '43_redistributed_physical_project_allocations.csv',
    '44_allocation_qaqc_summary.csv',
    '45_control_point_utilization_baseline.csv',
    '46_control_point_utilization_redistributed.csv',
    '47_redistribution_optimization_summary.csv',
}
CASE_INPUTS = {
    '24_alternative_decision_unit_allocations.csv',
    '25_alternative_physical_project_allocations.csv',
    '35_component_daily_curves_capped.csv',
    'capacity_status/01_reservoir_daily_capacity_status.csv',
    'capacity_status/02_control_point_daily_capacity_status.csv',
}


def restore_model_inputs():
    """Stage saved inputs where the original calculation scripts expect them."""
    for name in MODEL_INPUTS:
        source = MODEL / name
        if source.exists() and not (DIAGNOSTICS / name).exists():
            shutil.copy2(source, DIAGNOSTICS / name)


def finish_outputs(extra_diagnostics=False):
    """Only discard known generated intermediates, after successful publication."""
    MODEL.mkdir(parents=True, exist_ok=True)
    extra = DIAGNOSTICS / 'extra'

    def optional(path, relative):
        if extra_diagnostics:
            destination = extra / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(path), str(destination))
        else:
            path.unlink()

    for name in sorted(MODEL_EXPORTS):
        path = DIAGNOSTICS / name
        if not path.exists():
            continue
        if path.name in MODEL_INPUTS:
            shutil.move(str(path), str(MODEL / path.name))
        else:
            optional(path, Path('model') / path.name)
    for case in ['before', 'after']:
        directory = DIAGNOSTICS / 'scenarios' / case
        for path in list(directory.rglob('*.csv')):
            relative = path.relative_to(directory)
            if relative.as_posix() not in CASE_INPUTS:
                optional(path, Path('scenarios') / case / relative)
    # The paired scenario tables supersede the old standalone baseline status set.
    legacy_status = DIAGNOSTICS / 'review/capacity_constraint_review'
    for path in list(legacy_status.glob('*.csv')):
        optional(path, Path('legacy_capacity_status') / path.name)
    if legacy_status.exists() and not any(legacy_status.iterdir()):
        legacy_status.rmdir()
    for path in list((DIAGNOSTICS / 'plots').glob('*')):
        if path.is_file():
            optional(path, Path('plots') / path.name)
    plots = DIAGNOSTICS / 'plots'
    if plots.exists() and not any(plots.iterdir()):
        plots.rmdir()
    # Remove prior optional exports when returning to the default compact mode.
    if not extra_diagnostics and extra.exists():
        shutil.rmtree(extra)
