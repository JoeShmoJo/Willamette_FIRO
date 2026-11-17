"""Study-rule and coverage regression tests; run with unittest discovery."""
import unittest
import hashlib
import json
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

from recreation import ramp_available, season_dates, seasonal_rollups, zone_membership
from run_evidence import verified_digest, read_run_evidence


class RecreationTests(unittest.TestCase):
    def test_receipts_control_activation_and_conflicts_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root/'sets/test'
            receipts = folder/'initialization-receipts'
            receipts.mkdir(parents=True)
            target = folder/'firo.csv'
            target.write_bytes(b'Month,Day,R\n1,1,100\n')
            resolved = dict(schema_version=1, rules={'firo_space': {'settings': {'active': None}}},
                            table_paths={'firoSpaceConfigCSV': 'firo.csv'},
                            table_sha256={'firo.csv': hashlib.sha256(target.read_bytes()).hexdigest()})
            (folder/'resolved.json').write_text(json.dumps(resolved))
            digest = hashlib.sha256((folder/'resolved.json').read_bytes()).hexdigest()
            marker = root/'active.json'
            marker.write_text(json.dumps(dict(id='test', directory='sets/test', resolved_sha256=digest)))
            receipt = dict(module='FIRO_SPACE', output_fpart='RESULT', member=None,
                           reservoir='R', active=False, configuration_id='test', resolved_sha256=digest)
            (receipts/'a.json').write_text(json.dumps(receipt))
            path, active, evidence = read_run_evidence(marker, 'RESULT')
            self.assertEqual(path, target)
            self.assertEqual(active, {'R': False})
            with self.assertRaises(ValueError):
                read_run_evidence(marker, 'OTHER')
            receipt['active'] = True
            (receipts/'b.json').write_text(json.dumps(receipt))
            with self.assertRaises(ValueError):
                read_run_evidence(marker, 'RESULT')

    def test_zone_without_firo_disables_target_and_missing_pool_is_unknown(self):
        zones = [{'zone_name': 'Low', 'rules': []},
                 {'zone_name': 'RC', 'rules': ['FIRO_SPACE']},
                 {'zone_name': 'High', 'rules': ['FIRO_SPACE']}]
        pool = pd.Series([90., 95., 101., np.nan])
        selected, attached = zone_membership(pool, zones,
            {'Low': pd.Series([90.]*4), 'RC': pd.Series([100.]*4)})
        self.assertEqual(selected.iloc[:3].tolist(), ['Low', 'RC', 'High'])
        self.assertEqual(attached.iloc[:3].tolist(), [False, True, True])
        self.assertTrue(pd.isna(attached.iloc[3]))

    def test_checksum_requires_exact_original_bytes(self):
        expected = hashlib.sha256(b'a\r\nb\r\n').hexdigest()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'table.csv'
            path.write_bytes(b'a\nb\n')
            self.assertEqual(verified_digest(path, expected), 'exact-after-CRLF-reconstruction')
            path.write_bytes(b'a\nc\n')
            with self.assertRaises(ValueError):
                verified_digest(path, expected)

    def test_requires_actual_and_ceiling_strictly_above_ramp(self):
        pool = pd.Series([101., 100., 99., 110., 101., 101.])
        rc = pd.Series([101., 101., 101., 99., 100., 99.])
        firo = pd.Series([99., 101., 101., 99., 100., 102.])
        # Flood-zone filling, exact equality, and a dry ramp earn no credit.
        self.assertEqual(ramp_available(pool, rc, firo, 100, pd.Series(True, index=pool.index)).tolist(), [1, 0, 0, 0, 0, 1])

    def test_missing_required_values_are_unknown(self):
        pool = pd.Series([np.nan, 101., 101., 101.])
        rc = pd.Series([101., np.nan, 101., 101.])
        firo = pd.Series([101., 101., np.nan, np.nan])
        inactive = pd.Series([False, False, False, True])
        result = ramp_available(pool, rc, firo, 100, pd.Series(True, index=pool.index), inactive)
        self.assertTrue(result.iloc[:3].isna().all())
        self.assertEqual(result.iloc[3], 1)

    def test_disabled_firo_does_not_raise_recreation_ceiling(self):
        pool = pd.Series([110., 110., 110., 110.])
        rc = pd.Series([99., 99., 101., 99.])
        firo = pd.Series([105., 105., np.nan, 105.])
        enabled = pd.Series([False, True, False, pd.NA], dtype='boolean')
        result = ramp_available(pool, rc, firo, 100, enabled)
        self.assertEqual(result.iloc[:3].tolist(), [0, 1, 1])
        self.assertTrue(pd.isna(result.iloc[3]))

    def test_holiday_season_inclusive(self):
        dates = season_dates(2000, {'type': 'memorial_to_labor'})
        self.assertEqual(dates[0], pd.Timestamp('2000-05-29'))
        self.assertEqual(dates[-1], pd.Timestamp('2000-09-04'))
        self.assertEqual(len(dates), 99)

    def test_fixed_season_retains_leap_day(self):
        dates = season_dates(2000, {'type': 'fixed', 'start': '02-28', 'end': '03-01'})
        self.assertEqual(len(dates), 3)

    def test_two_ramps_for_seven_days_is_fourteen(self):
        rows = [dict(case='Baseline', year=2000, reservoir='R', ramp_name=ramp, available=1.)
                for ramp in ['A', 'B'] for _ in range(7)]
        ramps, totals = seasonal_rollups(pd.DataFrame(rows))
        self.assertEqual(ramps.boat_ramp_days.tolist(), [7., 7.])
        self.assertEqual(totals.boat_ramp_days.tolist(), [14., 14.])
        rows[0]['available'] = np.nan
        ramps, totals = seasonal_rollups(pd.DataFrame(rows))
        self.assertTrue(totals.boat_ramp_days.isna().all())
        self.assertEqual(totals.observed_boat_ramp_days.tolist(), [13., 13.])


if __name__ == '__main__':
    unittest.main()
