import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

from annual_overlays import CALENDAR, CALENDAR_DAYS, firo_overlays, water_year_overlay


class AnnualOverlayTests(unittest.TestCase):
    def test_water_years_align_by_month_and_day_and_have_separate_lines(self):
        dates = pd.date_range('1999-03-01', '2000-03-01')
        x, values, years = water_year_overlay(pd.Series(1., index=dates))
        march = CALENDAR_DAYS[3, 1]
        self.assertEqual(years[x == march].tolist(), [1999, 2000])
        self.assertEqual(years[x == CALENDAR_DAYS[2, 29]].tolist(), [2000])
        breaks = np.flatnonzero(np.isnan(x))
        self.assertEqual(len(breaks), 1)
        self.assertTrue(np.isnan(values[breaks[0]]))

    @patch('annual_overlays.firo_schedule')
    def test_disabled_case_has_no_target_line(self, schedule):
        target = pd.Series(100., index=CALENDAR)
        schedule.return_value = target, target.isna()
        path = Path('case.csv')
        curves, notes = firo_overlays('Detroit', ['Baseline', 'Alternative'], Path('reference.csv'),
                                     {'Baseline': (None, {}), 'Alternative': (path, {'detroit': True})})
        self.assertEqual([curve[0] for curve in curves], ['Alternative FIRO target'])
        self.assertEqual(notes, ['Baseline FIRO off'])
        schedule.assert_called_once_with(path, 'Detroit', CALENDAR)


if __name__ == '__main__':
    unittest.main()
