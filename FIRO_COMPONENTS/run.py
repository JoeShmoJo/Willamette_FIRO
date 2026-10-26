"""Run the model calculations, the retained reviews, or both."""

import argparse
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parent
MODEL = [
    "01_allocate_static_firo_space.py",
    "02_build_component_curves.py",
    "03_cap_validate_and_plot_curves.py",
    "05_optimize_static_redistribution.py",
]
REVIEW = [
    "11_build_capacity_constraint_review.py",
    "14_build_utilization_ribbon_overview.py",
    "13_build_constraint_controller_overview.py",
    "04_build_plotly_component_review.py",
    "07_add_plotly_review_navigation.py",
    "06_build_review_package.py",
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["model", "review", "all"])
    args = parser.parse_args()
    steps = MODEL if args.stage == "model" else REVIEW
    if args.stage == "all":
        steps = MODEL + REVIEW
    for script in steps:
        print(f"Running {script}", flush=True)
        subprocess.run([sys.executable, str(ROOT / "src" / script)],
                       cwd=ROOT, check=True)


if __name__ == "__main__":
    main()
