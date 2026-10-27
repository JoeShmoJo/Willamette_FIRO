"""Regression checks for the built before/after comparison artifacts."""
from pathlib import Path
import hashlib
import importlib.util
import json
import unittest

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = ROOT / 'outputs' / 'diagnostics'


def load_final(case):
    directory = ROOT / 'outputs/final'
    if case == 'before':
        directory = directory / 'baseline'
    actual = pd.concat([pd.read_csv(p) for p in sorted(directory.glob('alternative_*_combined_curves.csv'))], ignore_index=True)
    if set(actual.pop('allocation_case')) != {case}:
        raise AssertionError('Incorrect allocation case in final exports')
    return actual


class ReallocationComparisonTests(unittest.TestCase):
    def test_final_exports_match_review_data(self):
        for case in ['before', 'after']:
            actual = load_final(case)
            status = pd.read_csv(OUTPUTS / 'scenarios' / case / 'capacity_status/01_reservoir_daily_capacity_status.csv')
            keys = ['alternative_id', 'project_id', 'date']
            self.assertFalse(actual.duplicated(keys).any())
            matched = actual.merge(status, on=keys, validate='one_to_one', suffixes=('_final', '_review'))
            self.assertEqual(len(actual), len(matched))
            self.assertEqual(len(status), len(matched))
            np.testing.assert_allclose(matched.combined_offset_kaf_final, matched.combined_offset_kaf_review)
            np.testing.assert_allclose(actual.combined_storage_kaf - actual.rule_storage_kaf,
                                       actual.combined_offset_kaf, atol=1e-8)

    def test_compact_output_layout(self):
        self.assertFalse(list(OUTPUTS.glob('*.csv')))
        self.assertFalse((OUTPUTS / 'review/capacity_constraint_review').exists())
        for case in ['before', 'after']:
            self.assertFalse((OUTPUTS / 'scenarios' / case / '36_project_combined_daily_curves_capped.csv').exists())
        self.assertTrue((OUTPUTS / 'scenarios/model/43_redistributed_physical_project_allocations.csv').exists())

    def test_shared_ratings_cover_active_project_elevations(self):
        path = ROOT / 'src/02_build_component_curves.py'
        spec = importlib.util.spec_from_file_location('rating_source_test', path)
        builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(builder)
        self.assertEqual(builder.STORAGE_ELEVATION_FILE.resolve(),
                         (ROOT.parent / 'shared/common_data/ElevStor.csv').resolve())
        builder.PHYSICAL_ALLOCATIONS_FILE = OUTPUTS / 'scenarios/model/25_alternative_physical_project_allocations.csv'
        projects, _, ratings, _, _ = builder.load_inputs()
        issues = []
        lookup = builder.build_rating_lookup(ratings, issues)
        self.assertFalse(issues)
        self.assertGreater(len(projects), 0)
        for project in projects.itertuples():
            rating = lookup[project.project_id]
            self.assertTrue(np.isfinite(rating.to_numpy()).all())
            self.assertTrue((rating.storage_kaf.diff().dropna() >= 0).all())
            self.assertLessEqual(rating.elevation_ft.min(), project.min_con_elev_ft)
            self.assertGreaterEqual(rating.elevation_ft.max(), project.max_con_elev_ft)

    def test_scenarios_use_the_matching_allocations(self):
        source = pd.read_csv(OUTPUTS / 'scenarios/model/43_redistributed_physical_project_allocations.csv')
        self.assertGreater(len(source), 0)
        for case, field in [('before', 'baseline_project_firo_space_kaf'),
                            ('after', 'redistributed_project_firo_space_kaf')]:
            case_dir = OUTPUTS / 'scenarios' / case
            actual = pd.read_csv(case_dir / '25_alternative_physical_project_allocations.csv')
            matched = actual.merge(source[['alternative_id', 'project_id', field]],
                                   on=['alternative_id', 'project_id'], validate='one_to_one')
            self.assertEqual(len(matched), len(source))
            np.testing.assert_allclose(matched.project_firo_space_kaf, matched[field], atol=1e-8)
            daily = load_final(case)
            limits = actual[['alternative_id','project_id','project_firo_space_kaf']]
            checked = daily.merge(limits, on=['alternative_id','project_id'], validate='many_to_one')
            self.assertEqual(len(checked), len(daily))
            self.assertTrue(np.isfinite(checked.combined_offset_kaf).all())
            self.assertTrue((checked.combined_offset_kaf <= checked.project_firo_space_kaf + 1e-6).all())

    def test_reallocated_curves_are_rebuilt_not_just_relabeled(self):
        before = load_final('before')
        after = load_final('after')
        merged = before.merge(after, on=['alternative_id','project_id','date'],
                              suffixes=('_before','_after'), validate='one_to_one')
        self.assertEqual(len(merged), len(before))
        delta = abs(merged.combined_offset_kaf_after - merged.combined_offset_kaf_before)
        changed = merged.loc[delta > 1e-5, ['alternative_id','project_id']].drop_duplicates()
        self.assertEqual(set(map(tuple, changed.to_numpy())), {(1, 'DETROIT'), (1, 'GREEN_PETER')})

    def test_saved_case_hashes_and_page_pairs(self):
        manifest = json.loads((OUTPUTS / 'scenarios/manifest.json').read_text())
        for relative, expected in manifest['inputs_and_calculations'].items():
            self.assertEqual(hashlib.sha256((ROOT / relative).read_bytes()).hexdigest(), expected, relative)
        files = [p for p in OUTPUTS.rglob('alternative_*.html')]
        self.assertEqual(len(files), manifest['overview_pages'] + manifest['component_pages'])
        for p in files:
            text = p.read_text()
            self.assertIn('id="allocation-case"', text)
            payload = text.split('<script id="firo-scenarios" type="application/json">', 1)[1].split('</script>', 1)[0]
            figures = json.loads(payload)
            self.assertEqual(set(figures), {'before', 'after'})
            self.assertTrue(figures['before']['data'])
            self.assertTrue(figures['after']['data'])


if __name__ == '__main__':
    unittest.main()
