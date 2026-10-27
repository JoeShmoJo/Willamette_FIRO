"""Shared-source contracts and retained MAX capacity calculations."""
from pathlib import Path
import importlib.util
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('max_space_limits', ROOT / 'space_limits.py')
max_space = importlib.util.module_from_spec(spec)
spec.loader.exec_module(max_space)


class SharedSourceTests(unittest.TestCase):
    def test_shared_ratings_cover_all_active_conservation_ranges(self):
        projects = max_space.load_project_parameters()
        ratings = max_space.load_storage_ratings()
        self.assertGreater(len(projects), 0)
        self.assertNotIn('ConStorageKAF', projects.columns)
        self.assertNotIn('SevenDayEvacuationVolumeKAF', projects.columns)
        for project in projects.itertuples():
            if project.Project == 'Lookout Point+Hills Creek':
                continue
            rating = ratings.loc[ratings.Project == project.Project]
            self.assertGreaterEqual(len(rating), 2)
            self.assertLessEqual(rating['Elevation (ft)'].min(), project.MinCon)
            self.assertGreaterEqual(rating['Elevation (ft)'].max(), project.MaxCon)
            self.assertTrue((rating['Storage (ac-ft)'].diff().dropna() >= 0).all())

    def test_capacity_uses_selected_rating_not_the_cached_volume(self):
        projects = max_space.find_conservation_storage(
            max_space.load_project_parameters(), max_space.load_storage_ratings())
        projects = max_space.calculate_7_day_evacuation_volume(projects).set_index('Project')
        # These known selected-source values differ from the uploaded snapshot.
        self.assertAlmostEqual(projects.loc['Green Peter', 'ConStorageKAF'], 249.9, places=6)
        self.assertAlmostEqual(projects.loc['Green Peter', 'SevenDayEvacuationVolumeKAF'], 85.721058, places=5)
        self.assertAlmostEqual(projects.loc['Lookout Point+Hills Creek', 'ConStorageKAF'],
                               projects.loc['Lookout Point', 'ConStorageKAF'] +
                               projects.loc['Hills Creek', 'ConStorageKAF'])
        self.assertTrue(np.isfinite(projects['SevenDayEvacuationVolumeKAF']).all())


if __name__ == '__main__':
    unittest.main()
