import unittest

import numpy as np
import pandas as pd

from compare_purposes import add_system_metrics, annual_rows, special_release


class PurposeComparisonTests(unittest.TestCase):
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
