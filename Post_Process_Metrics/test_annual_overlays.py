import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

from annual_overlays import (CALENDAR, CALENDAR_DAYS, CALENDAR_MS, firo_overlays,
                             reservoir_figure, water_year_overlay)


class AnnualOverlayTests(unittest.TestCase):
    def test_all_overlay_lines_use_svg_and_numeric_dates(self):
        pool = pd.Series(100., index=CALENDAR)
        ramps = pd.DataFrame({'elevation_ft': [99.], 'ramp_name': ['Test ramp']})
        fig, _ = reservoir_figure({'Baseline': {'elev': pool}}, ramps, 105.,
                                  [('FIRO target', pool + 1., '#17638a')])
        self.assertEqual(len(fig.data), 4)
        for axis in (fig.layout.xaxis, fig.layout.xaxis2):
            self.assertEqual(list(axis.range), CALENDAR_MS[[0, -1]].tolist())
            self.assertEqual((axis.ticktext[0], axis.ticktext[-1]), ('Oct', 'Sep'))
        for trace in fig.data:
            self.assertEqual(trace.type, 'scatter')
            self.assertEqual(trace.x[0], CALENDAR_MS[0])
            self.assertEqual(trace.x[-1], CALENDAR_MS[-1])

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
