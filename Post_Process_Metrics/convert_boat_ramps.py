"""Convert the supplied two-column ramp workbook without inferring pool limits."""
import argparse
import csv
import json
import re
from collections import Counter
from pathlib import Path

from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parent
RESERVOIRS = {
    'Hills Creek', 'Lookout Point', 'Dexter', 'Fall Creek', 'Fern Ridge',
    'Cougar', 'Blue River', 'Dorena', 'Cottage Grove', 'Green Peter', 'Foster', 'Detroit',
}


def convert(source, output):
    workbook = load_workbook(source, read_only=True, data_only=True)
    ramps, pools, issues = [], [], []
    try:
        for sheet in workbook:
            basin = reservoir = None
            for number, row in enumerate(sheet.iter_rows(values_only=True), 1):
                cells = list(row) + [None, None]
                first, second = cells[:2]
                if any(value is not None for value in cells[2:]):
                    raise ValueError(f'Unexpected extra columns: {sheet.title}:{number}')
                if first is None and second is None:
                    continue
                text = str(first).strip() if first is not None else ''
                if second is None:
                    if text == 'Boat Ramp Elevations':
                        continue
                    if text.endswith('River Basin'):
                        basin, reservoir = text, None
                    else:
                        reservoir = 'Fall Creek' if text == 'Fall Ck' else text
                        if reservoir not in RESERVOIRS:
                            raise ValueError(f'Unknown reservoir: {text!r}')
                    continue
                if not reservoir or not basin:
                    raise ValueError(f'No basin/reservoir for {sheet.title}:{number}')
                match = re.fullmatch(r'([0-9]+(?:\.[0-9]+)?)\s*(?:ft)?', text)
                if not match:
                    raise ValueError(f'Invalid elevation: {sheet.title}:{number}: {text!r}')
                name = str(second).strip()
                record = dict(basin=basin, reservoir=reservoir, elevation_ft=float(match[1]),
                              source_sheet=sheet.title, source_row=number)
                if name in {'Maximum Conservation Pool', 'Minimum Conservation Pool'}:
                    pools.append(dict(record, pool_label=name))
                else:
                    ramps.append(dict(record, ramp_name=name))
    finally:
        workbook.close()
    if not ramps:
        raise ValueError('No ramps found')
    identities = [(r['reservoir'], r['ramp_name']) for r in ramps]
    if len(set(identities)) != len(identities):
        raise ValueError('Duplicate reservoir/ramp names')
    counts = Counter((r['reservoir'], r['pool_label']) for r in pools)
    for reservoir in sorted({r['reservoir'] for r in ramps}):
        for label in ['Maximum Conservation Pool', 'Minimum Conservation Pool']:
            count = counts[reservoir, label]
            if count != 1:
                issues.append(dict(reservoir=reservoir, label=label, count=count,
                                   message='Retained as supplied; confirm workbook label.'))
    output.mkdir(parents=True, exist_ok=True)
    for filename, records, fields in [
        ('boat_ramp_elevations.csv', ramps, ['basin', 'reservoir', 'ramp_name', 'elevation_ft', 'source_sheet', 'source_row']),
        ('boat_ramp_pool_references.csv', pools, ['basin', 'reservoir', 'pool_label', 'elevation_ft', 'source_sheet', 'source_row']),
    ]:
        with (output/filename).open('w', newline='', encoding='utf-8') as stream:
            writer = csv.DictWriter(stream, fieldnames=fields, lineterminator='\n')
            writer.writeheader()
            writer.writerows(records)
    (output/'boat_ramp_conversion_issues.json').write_text(json.dumps(issues, indent=2)+'\n', encoding='utf-8')
    print(f'{len(ramps)} ramps at {len(set(r["reservoir"] for r in ramps))} reservoirs; '
          f'{len(pools)} separate pool references; {len(issues)} issues.')
    for issue in issues:
        print(issue)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=ROOT/'data/Boat_Ramp_Elevations.xlsx')
    parser.add_argument('--output', type=Path, default=ROOT/'data')
    args = parser.parse_args()
    convert(args.input, args.output)
