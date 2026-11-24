"""Register progressive FIRO cases in a closed WAT study."""

import argparse
import csv
from datetime import date, timedelta
from pathlib import Path
import re
import shutil
import tempfile
import xml.etree.ElementTree as ET

from export_wat_components import H_PROJECTS
from run import ROOT

TEMPLATE = "FIRO_Test_FIROSpace"
PERIOD = "POR_1935-2019"
COMPONENTS = "ACEHIJK"
MANAGER = re.compile(rb"(?ms)^ManagerBegin\r?\n.*?^ManagerEnd(?=\r?$)")
FILES = (
    f"wat/alts/{TEMPLATE}.walt",
    f"wat/sims/{TEMPLATE}-{PERIOD}.container",
    f"wat/sims/{TEMPLATE}-{PERIOD}.simulation",
    f"wat/modelLinking/{TEMPLATE}-{PERIOD}.linkages",
)


def field(block, key):
    match = re.search(rb"(?m)^" + key.encode() + rb"=([^\r\n]*)", block)
    return match[1] if match else b""


def read_curve(source, expected, names):
    with source.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        rows = list(reader)
    if reader.fieldnames != ["Month", "Day", *names]:
        raise ValueError(f"Unexpected reservoir columns in {source}")
    dates = [date(2001, 1, 1) + timedelta(days=offset) for offset in range(365)]
    if [(int(row["Month"]), int(row["Day"])) for row in rows] != [(day.month, day.day) for day in dates]:
        raise ValueError(f"Expected the complete non-leap calendar in {source}")
    active = {name for name in names if any(row[name] for row in rows)}
    if active != expected:
        raise ValueError(f"Unexpected active reservoirs in {source}: {sorted(active)}")
    return source.read_bytes()


def prepare(root, study, curves, components):
    original = study.read_bytes()
    newline = b"\r\n" if b"\r\n" in original else b"\n"
    managers = [match[0] for match in MANAGER.finditer(original)]
    templates = {}
    for relative in FILES[:-1]:
        matches = [
            block for block in managers
            if field(block, "File").replace(b"\\", b"/") == relative.encode()
        ]
        if len(matches) != 1:
            raise ValueError(f"Expected one study registration for {relative}")
        templates[relative] = matches[0]

    period = (root / f"wat/aps/{PERIOD}.wap").read_bytes()
    for required in (b"StartDate=01OCT1935", b"StartTime=00:00", b"EndDate=30SEP2019", b"EndTime=24:00"):
        if required not in period.splitlines():
            raise ValueError(f"The study period differs from {PERIOD}: {required.decode()}")
    if not (root / "rss/ALL_D.ralt").is_file():
        raise FileNotFoundError("The study is missing rss/ALL_D.ralt.")
    with (ROOT / "data/01_projects_physical.csv").open(encoding="utf-8-sig") as stream:
        projects = list(csv.DictReader(stream))
    names = [row["project_name"] for row in projects]
    h_names = {row["project_name"] for row in projects if row["project_id"] in H_PROJECTS}
    template_files = {relative: (root / relative).read_bytes() for relative in FILES}
    pending = {}
    new_study = original
    for code in components:
        name = f"PGFIRO_{code}"
        simulation = f"{name}-{PERIOD}"
        curve = f"FIRO_SPACEConfig_Progressive_{code}.csv"
        pending[root / "scripts/externalRules" / curve] = read_curve(
            curves / curve, h_names if code == "H" else set(names), names,
        )
        pending[root / "scripts/alt_config/WAT" / f"{name}.txt"] = (
            f'firoActive: true\nfiroSpaceConfigCSV: "scripts/externalRules/{curve}"\n'.encode()
        )

        for relative, data in template_files.items():
            target = relative.replace(TEMPLATE, name)
            content = data.replace(TEMPLATE.encode(), name.encode())
            if relative.endswith(".simulation"):
                content, count = re.subn(rb'FPart="[^":]+:', f'FPart="{name}:'.encode(), content)
                if count != 1:
                    raise ValueError("Template simulation is missing the expected WAT DSS F-part.")
                content = content.replace(b'HasComputed="true"', b'HasComputed="false"')
                content = content.replace(b'ComputeError="true"', b'ComputeError="false"')
                content = re.sub(rb' LastComputed(?:By|Date)="[^"]*"', b"", content)
                content = re.sub(rb'(?m)^[ \t]*<LastComputeTime\b[^>]*/>\r?\n', b"", content)
                node = ET.fromstring(content)
                model = node.findall("./ModelAlternatives/*")
                if (node.get("SimulationName") != simulation or len(model) != 1 or
                    model[0].get("Program") != "ResSim" or model[0].get("File") != "rss/ALL_D.ralt"):
                    raise ValueError("The WAT template must use ALL_D as its sole ResSim alternative.")
            elif relative.endswith(".container"):
                node = ET.fromstring(content)
                if node.get("Alternative") != name or node.get("AnalysisPeriod") != PERIOD:
                    raise ValueError("The WAT template container uses a different alternative or period.")
            elif relative.endswith(".linkages"):
                node = ET.fromstring(content)
                linked = node.find("Name")
                if linked is None or not linked.text or linked.text.strip() != simulation:
                    raise ValueError("The WAT template linkage has an unexpected simulation name.")
            elif field(content, "Name") != name.encode():
                raise ValueError("The WAT template has an unexpected alternative name.")
            pending[root / target] = content

            if relative in templates:
                template = templates[relative]
                new_block = template.replace(TEMPLATE.encode(), name.encode())
                new_block = re.sub(rb"(?m)^File=[^\r\n]*", b"File=" + target.encode(), new_block)
                matching = [
                    block for block in managers
                    if field(block, "Name") == field(new_block, "Name")
                    and field(block, "Class") == field(new_block, "Class")
                ]
                if matching:
                    if len(matching) != 1 or field(matching[0], "File").replace(b"\\", b"/") != target.encode():
                        raise ValueError(f"Conflicting study registration for {target}")
                else:
                    new_study = new_study.replace(template, template + newline * 2 + new_block, 1)
    return original, new_study, pending


def install(root, curves, components=COMPONENTS):
    study = root / f"{root.name}.sty"
    original, registration, pending = prepare(root, study, curves, components)
    additions = {}
    for path, content in pending.items():
        if not path.parent.is_dir():
            raise FileNotFoundError(path.parent)
        if path.exists():
            if path.read_bytes() != content:
                raise FileExistsError(f"Preserving existing file with different contents: {path}")
        else:
            additions[path] = content
    if study.read_bytes() != original:
        raise RuntimeError("The study changed during preparation. Close WAT before installing.")

    backup = None
    if registration != original:
        with tempfile.NamedTemporaryFile(prefix=f"{study.stem}-", suffix=".sty.bak", delete=False) as stream:
            stream.write(original)
            backup = Path(stream.name)
    created = []
    temporary = None
    try:
        for path, content in additions.items():
            with path.open("xb") as stream:
                created.append(path)
                stream.write(content)
        if backup:
            with tempfile.NamedTemporaryFile(dir=root, suffix=".tmp", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(registration)
            shutil.copymode(study, temporary)
            temporary.replace(study)
    except OSError:
        for path in created:
            path.unlink()
        raise
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    print(f"Study: {study}")
    if backup:
        print(f"Study backup: {backup}")
    print(f"Companion files created: {len(created)}")
    for code in components:
        print(f"WAT simulation: PGFIRO_{code}-{PERIOD} (ALL_D)")


def refresh_curves(root, curves, components=COMPONENTS):
    """Replace only the selected installed CSVs and keep a recoverable backup."""
    with (ROOT / "data/01_projects_physical.csv").open(encoding="utf-8-sig") as stream:
        projects = list(csv.DictReader(stream))
    names = [row["project_name"] for row in projects]
    h_names = {row["project_name"] for row in projects if row["project_id"] in H_PROJECTS}
    pending = {}
    for code in components:
        alternative = f"PGFIRO_{code}"
        if not (root / "wat/alts" / f"{alternative}.walt").is_file():
            raise FileNotFoundError(f"{alternative} is not installed; install the WAT cases first")
        filename = f"FIRO_SPACEConfig_Progressive_{code}.csv"
        target = root / "scripts/externalRules" / filename
        override = root / "scripts/alt_config/WAT" / f"{alternative}.txt"
        expected_path = f"scripts/externalRules/{filename}"
        references = re.findall(r'(?m)^\s*firoSpaceConfigCSV\s*:\s*"([^"]+)"',
                                override.read_text(encoding="utf-8-sig"))
        if references != [expected_path] or not target.is_file():
            raise ValueError(f"Unexpected installed curve reference in {override}")
        expected = h_names if code == "H" else set(names)
        content = read_curve(curves / filename, expected, names)
        if content != target.read_bytes():
            pending[target] = content
    if not pending:
        print("The installed WAT curves already match.")
        return
    backup = Path(tempfile.mkdtemp(prefix="firo-wat-curves-"))
    for target in pending:
        shutil.copy2(target, backup / target.name)
    replaced = []
    try:
        for target, content in pending.items():
            with tempfile.NamedTemporaryFile(dir=target.parent, suffix=".tmp", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(content)
            try:
                temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)
            replaced.append(target)
    except OSError:
        for target in replaced:
            shutil.copy2(backup / target.name, target)
        raise
    print(f"Previous WAT curves backed up to: {backup}")
    for target in replaced:
        print(f"Updated: {target}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("watershed", type=Path)
    parser.add_argument("curves", type=Path)
    single_case = parser.add_mutually_exclusive_group()
    single_case.add_argument("--max-offset", dest="components", action="store_const", const="M",
                             help="Install only the PGFIRO_M benchmark")
    single_case.add_argument("--only-h", dest="components", action="store_const", const="H",
                             help="Install only PGFIRO_H")
    single_case.add_argument("--refresh-curves", action="store_true",
                             help="Back up and replace only the installed A–K component CSVs")
    single_case.add_argument("--refresh-all-curves", action="store_true",
                             help="Back up and replace the installed A–K and M component CSVs")
    single_case.add_argument("--refresh-i", action="store_true",
                             help="Back up and replace only the installed I curve")
    parser.set_defaults(components=COMPONENTS)
    args = parser.parse_args()
    if args.refresh_all_curves:
        refresh_curves(args.watershed.resolve(), args.curves.resolve(), COMPONENTS + "M")
    elif args.refresh_curves or args.refresh_i:
        refresh_curves(args.watershed.resolve(), args.curves.resolve(), "I" if args.refresh_i else COMPONENTS)
    else:
        install(args.watershed.resolve(), args.curves.resolve(), args.components)


if __name__ == "__main__":
    main()
