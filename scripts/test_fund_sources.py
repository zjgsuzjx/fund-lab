"""Offline regression tests for unsafe or inconsistent upstream data."""
import json
import unittest

from verify_fund_sources import parse_directory, parse_history, positive_decimal, compare_nav, parse_official


class SourceValidationTests(unittest.TestCase):
    def test_directory_rejects_executable_suffix(self):
        with self.assertRaises(ValueError):
            parse_directory('var r = []; alert("unexpected");')

    def test_duplicate_code_rejected(self):
        row = ['000147', 'x', 'name', 'bond', 'x']
        with self.assertRaises(ValueError):
            parse_directory('var r = ' + json.dumps([row, row]) + ';')

    def test_invalid_nav_rejected(self):
        for value in ['NaN', 'Infinity', '0', '-1']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                positive_decimal(value)

    def test_duplicate_or_ascending_dates_rejected(self):
        for dates in [('2026-01-01', '2026-01-01'), ('2026-01-01', '2026-01-02')]:
            payload = {'TotalCount': 2, 'Data': {'LSJZList': [
                {'FSRQ': day, 'DWJZ': '1.0000'} for day in dates]}}
            with self.subTest(dates=dates), self.assertRaises(ValueError):
                parse_history(json.dumps(payload))

    def test_no_overlap_is_not_success(self):
        self.assertFalse(compare_nav([], [])['passed'])

    def test_nav_comparison_uses_decimal_values(self):
        official = [{'date': '2026-01-01', 'unit_nav': '1.00', 'cumulative_nav': '1.20'}]
        other = [{'date': '2026-01-01', 'unit_nav': '1.0000', 'cumulative_nav': '1.2000'}]
        self.assertTrue(compare_nav(official, other)['passed'])
        other[0]['unit_nav'] = '1.0001'
        self.assertFalse(compare_nav(official, other)['passed'])

    def test_unrelated_zero_fee_text_does_not_set_fee(self):
        self.assertEqual(parse_official('<footer>本基金不收取申购费</footer>')['subscription_fees'], [])


if __name__ == '__main__':
    unittest.main()
