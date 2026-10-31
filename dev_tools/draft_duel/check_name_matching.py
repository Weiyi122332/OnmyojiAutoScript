import unittest
from tasks.DraftDuel.strategy import normalize_name, _levenshtein_distance


class NameMatchingTests(unittest.TestCase):
    def test_edit_distance_insertion_deletion_and_substitution(self):
        self.assertEqual(_levenshtein_distance('青行灯', '青灯'), 1)
        self.assertEqual(_levenshtein_distance('青行灯', '青行明灯'), 1)
        self.assertEqual(_levenshtein_distance('青行灯', '青行登'), 1)

    def test_short_names_require_exact_match(self):
        catalog = dict.fromkeys(['季', '椒图', '般若', '青行灯'])
        self.assertEqual(normalize_name('椒图', catalog), '椒图')
        self.assertEqual(normalize_name('季', catalog), '季')
        for text in ['般右', '椒困', '青灯', '季风神']:
            self.assertIsNone(normalize_name(text, catalog), text)

    def test_long_names_use_unique_levenshtein_result(self):
        catalog = dict.fromkeys(['青行灯'])
        self.assertEqual(normalize_name('青行登', catalog), '青行灯')
        self.assertEqual(normalize_name('青行明灯', catalog), '青行灯')
        self.assertIsNone(normalize_name('青行天', dict.fromkeys(['青行灯', '青行海'])))

    def test_middle_dot_is_part_of_the_whole_name(self):
        for text in ['妖刀姬·绯夜猎刃', '妖刀姬绯夜猎刃', '天刀姬·绯夜猎']:
            self.assertEqual(normalize_name(text), '妖刀姬·绯夜猎刃')
        self.assertIsNone(normalize_name('妖刀姬·完全未知后缀'))
