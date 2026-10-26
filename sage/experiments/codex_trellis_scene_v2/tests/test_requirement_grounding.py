import unittest
from copy import deepcopy

from ..brief import build_baseline_brief
from ..dimensions import resolve_dimension_adaptation, dimension_policy_for_category
from ..furnishing_groups import ground_groups
from ..policies import detect_explicit_category_counts
from ..scene_physics import extend_brief


class RequirementGroundingTests(unittest.TestCase):
    def test_walkway_starts_at_actual_door_wall(self):
        from ..validator import walkway_exists
        plan={'room':{'width':4.,'length':4.}, 'architecture':{'doors':[{'wall':'north','center':2.}]}}
        barrier={'x':2.,'y':1.,'yaw':0.,'dimensions':dict(width=4.,length=.4,height=1.)}
        self.assertTrue(walkway_exists(plan,[barrier]))
        plan['architecture']['doors'][0]['wall']='south'
        self.assertFalse(walkway_exists(plan,[barrier]))

    def test_complete_study_does_not_require_unrequested_optional_cabinet(self):
        prompt='A study with a desk, office chair, bookshelf, floor lamp, laptop and plant.'
        brief=build_baseline_brief(prompt)
        self.assertFalse(any(o['category']=='cabinet' for o in brief['objects']))
        explicit=build_baseline_brief(prompt+' Add a cabinet.')
        self.assertTrue(next(o for o in explicit['objects'] if o['category']=='cabinet')['required'])

    def test_main_window_uses_architecture_and_seating_faces_requested_target(self):
        brief=build_baseline_brief('A living room with a sofa, two lounge chairs and a coffee table. Place the main window on the east wall. Face the seating toward the coffee table and the artwork into the room.')
        self.assertEqual(brief['architectural_object_mentions'], {'window':1})
        self.assertFalse(any(o['category']=='window' for o in brief['objects']))
        self.assertEqual(len(brief['rule_facing_grounding']), 3)
        self.assertTrue(all(r['relation']['target']=='coffee_table' for r in brief['rule_facing_grounding']))

    def test_plural_lounge_chairs_and_laptop_retained(self):
        brief = build_baseline_brief('A study with two lounge chairs, a laptop and a desk.')
        self.assertEqual(brief['explicit_category_counts']['accent_chair'], 2)
        laptop = next(o for o in brief['objects'] if o['category'] == 'laptop')
        self.assertEqual(laptop['support_id'], 'desk')

    def test_specific_compound_does_not_create_phantom_cabinet(self):
        counts = detect_explicit_category_counts('A television on two TV cabinets and a cabinet.')
        self.assertEqual(counts['tv_stand'], 2)
        self.assertEqual(counts['cabinet'], 1)
        self.assertEqual(counts['tv'], 1)
        self.assertNotIn('cabinet', detect_explicit_category_counts('A television on a TV cabinet.'))

    def test_count_does_not_cross_conjunction(self):
        counts = detect_explicit_category_counts('Two chairs and a cabinet with three framed wall artworks.')
        self.assertEqual(counts['cabinet'], 1)

    def test_inferred_size_preserves_source_but_keeps_runtime_guard(self):
        brief = build_baseline_brief('A study with a floor lamp.')
        obj = next(o for o in brief['objects'] if o['category'] == 'floor_lamp')
        source = dict(width=.29, length=.57, height=1.50)
        result = resolve_dimension_adaptation(source, obj['requested_dimensions'], obj['dimension_policy'])
        self.assertTrue(result['accepted'])
        self.assertEqual(result['effective_dimensions'], source)
        self.assertTrue(result['requires_runtime_bounds_check'])
        strict = deepcopy(obj['dimension_policy']); strict.pop('request_origin')
        self.assertFalse(resolve_dimension_adaptation(source, obj['requested_dimensions'], strict)['accepted'])

    def test_explicit_size_expression_and_opening_stay_strict(self):
        for prompt in ['A study with a 1.8 m floor lamp.', '书房配180厘米落地灯', 'A 40x40x150 floor lamp.']:
            brief = build_baseline_brief(prompt, 'study')
            self.assertTrue(all('request_origin' not in o['dimension_policy'] for o in brief['objects']))
        brief = build_baseline_brief('A study with a window.')
        window = next(o for o in brief['objects'] if o['category'] == 'window')
        self.assertNotIn('request_origin', window['dimension_policy'])

    def test_explicit_furnishing_size_clears_inferred_policy(self):
        brief = build_baseline_brief('A study with a laptop.')
        ground_groups(brief, {}, {'object_overrides': {'desk': {'dimensions': dict(width=2., length=.8, height=.9)}}})
        obj = next(o for o in brief['objects'] if o['id'] == 'desk')
        self.assertEqual(obj['requested_dimensions'], obj['dimensions'])
        self.assertNotIn('request_origin', obj['dimension_policy'])

    def test_explicit_physics_size_clears_inferred_policy(self):
        brief = build_baseline_brief('A study with a bookcase.')
        extend_brief(brief, dict(bookcase_dimensions=[.9,.32,1.6], book_dimensions=[.03,.16,.24], book_count=2))
        shelf = next(o for o in brief['objects'] if o['category'] == 'bookcase')
        self.assertNotIn('request_origin', shelf['dimension_policy'])

    def test_nonfinite_requested_size_is_rejected(self):
        for value in (float('nan'), float('inf'), 0., -1.):
            with self.assertRaises(ValueError):
                resolve_dimension_adaptation(None, dict(width=value, length=1., height=1.), dimension_policy_for_category('desk'))
