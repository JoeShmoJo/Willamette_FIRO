import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from compare_purposes import (FLOOD_LEVELS, MAX_RELATIVE_STORAGE, SYSTEM_STORAGE, add_system_metrics,
                              annual_rows, days_above, relative_system_storage, release_shortfall,
                              special_release)
from inspect_por import copy_snapshot


class PurposeComparisonTests(unittest.TestCase):
    def test_system_flood_counts_overlapping_exceedances_once_and_requires_all_sites(self):
        metric = FLOOD_LEVELS['flood_cfs']
        first = ('Flood Control', 'First', metric, 'days', 'daily routed flow threshold', 'sum')
        second = ('Flood Control', 'Second', metric, 'days', 'daily routed flow threshold', 'sum')
        case = {first: pd.Series([1., 1., 0., 1.]), second: pd.Series([1., 0., 0., np.nan])}
        add_system_metrics([case, case.copy()], pd.Series(np.nan, index=range(4)))
        system = ('Flood Control', 'SYSTEM', f'{metric} at any control point', 'days',
                  'daily routed flow threshold', 'sum')
        np.testing.assert_equal(case[system].to_numpy(), [1., 1., 0., np.nan])

    def test_release_screen_uses_tolerance_without_inventing_missing_or_disabled_targets(self):
        target = pd.Series([100., 100., 500., 500., 0., np.nan, 100.])
        out = pd.Series([95., 94., 490., 489., 0., 0., np.nan])
        np.testing.assert_equal(release_shortfall(out, target).to_numpy(),
                                [0., 1., 0., 1., 0., np.nan, np.nan])

    def test_days_above_uses_strict_flow_threshold_and_preserves_missing_days(self):
        result = days_above(pd.Series([11999., 12100., 12101., np.nan]), 12100)
        np.testing.assert_equal(result.to_numpy(), [0., 0., 1., np.nan])

    @patch('inspect_por.sys.stderr')
    @patch('inspect_por.time.sleep')
    @patch('inspect_por.shutil.copyfile')
    def test_dss_copy_retries_temporary_access_denial(self, copy, sleep, stderr):
        copy.side_effect = [PermissionError('busy'), None]
        copy_snapshot('simulation.dss', 'temporary.dss')
        self.assertEqual(copy.call_count, 2)
        sleep.assert_called_once_with(2)

        copy.reset_mock(side_effect=True)
        copy.side_effect = PermissionError('busy')
        with self.assertRaisesRegex(PermissionError, 'after 3 attempts.*simulation.dss'):
            copy_snapshot('simulation.dss', 'temporary.dss')
        self.assertEqual(copy.call_count, 3)

    def test_relative_storage_uses_one_reference_and_excludes_partial_seasons_from_zero(self):
        dates = pd.date_range('1991-02-01', periods=5)
        cases = [{SYSTEM_STORAGE: pd.Series(values, index=dates)}
                 for values in ([20, 30, 5, 50, 3], [10, 40, np.nan, 35, 2])]
        storage, zero = relative_system_storage(cases, [dates[:2], dates[2:4]], dates)
        self.assertEqual(zero, dict(zero_acre_ft=20, baseline_date='1991-02-01',
                                    complete_paired_seasons=1))
        self.assertEqual(storage.alternative.iloc[0], -10)
        self.assertEqual(storage.baseline.iloc[-1], -17)
        row = next(annual_rows(MAX_RELATIVE_STORAGE, storage.baseline, storage.alternative,
                               pd.Series([True, True, False, True, True], index=dates)))
        self.assertEqual((row['baseline'], row['alternative'], row['change']), (30, 20, -10))

    def test_system_storage_sums_daily_before_taking_minimum_and_requires_all_members(self):
        dates = pd.date_range('1991-10-01', periods=2)
        expected = pd.Series(True, index=dates)
        missing = pd.Series(np.nan, index=dates)
        keys = [('Water Supply', site, 'Minimum total pool storage', 'acre-ft', 'proxy', 'min')
                for site in ('First', 'Second')]
        base = {keys[0]: pd.Series([1., 10.], index=dates), keys[1]: pd.Series([10., 1.], index=dates)}
        alt = base.copy()
        members = add_system_metrics([base, alt], missing)
        self.assertEqual(members, {'Minimum combined pool storage': ['First', 'Second']})
        system = ('Water Supply', 'SYSTEM', 'Minimum combined pool storage', 'acre-ft', 'proxy', 'min')
        self.assertEqual(next(annual_rows(system, base[system], alt[system], expected))['baseline'], 11)

        alt.pop(keys[1])
        add_system_metrics([base, alt], missing)
        self.assertTrue(alt[system].isna().all())

    def test_special_release_requires_applicable_rule_and_strict_exceedance(self):
        zones = pd.Series(['Rule Curve', 'Rule Curve', 'Inactive', 'Rule Curve', pd.NA, 'Rule Curve'])
        rules = pd.Series(['Max Evacuation Release'] * 2 + [pd.NA]
                          + ['Max Evacuation Release', pd.NA, 'Max Evacuation Release'])
        outflow = pd.Series([10., 11., 50., 12., 12., np.nan])
        limit = pd.Series([10., 10., np.nan, np.nan, 10., 10.])
        np.testing.assert_equal(special_release(outflow, limit, zones, rules).to_numpy(),
                                [0., 1., 0., np.nan, np.nan, np.nan])

    def test_water_years_exclude_ineligible_days_and_require_paired_coverage(self):
        dates = pd.date_range('1991-09-29', periods=4)
        expected = pd.Series([False, True, True, True], index=dates)
        baseline = pd.Series([np.nan, 0., 1., 1.], index=dates)
        alternative = pd.Series([np.nan, 1., 0., np.nan], index=dates)
        key = ('ESA', 'Salem', 'Days below', 'days', 'proxy', 'sum')
        complete, incomplete = annual_rows(key, baseline, alternative, expected)
        self.assertEqual((complete['year'], complete['expected'], complete['paired'], complete['change']),
                         (1991, 1, 1, 1))
        self.assertEqual((incomplete['year'], incomplete['expected'], incomplete['paired']),
                         (1992, 2, 1))
        self.assertTrue(np.isnan(incomplete['baseline']))
        self.assertTrue(np.isnan(incomplete['alternative']))


if __name__ == '__main__':
    unittest.main()
