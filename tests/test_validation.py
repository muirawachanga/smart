import unittest

from intelligent_ordering.utils.validation import (
    MAX_SEARCH_LENGTH,
    escape_like,
    validate_catalog_filters,
    validate_pagination,
)


class TestPaginationValidation(unittest.TestCase):
    def test_accepts_valid_page_and_size(self):
        self.assertEqual(validate_pagination("2", "20"), (2, 20))

    def test_rejects_non_positive_values(self):
        for values in ((0, 20), (1, 0), (-1, 5)):
            with self.subTest(values=values), self.assertRaises(ValueError):
                validate_pagination(*values)

    def test_rejects_page_sizes_above_limit(self):
        with self.assertRaises(ValueError):
            validate_pagination(1, 101)

    def test_rejects_non_integer_and_boolean_values(self):
        for values in (("1.5", 20), (True, 20), (1, False)):
            with self.subTest(values=values), self.assertRaises(ValueError):
                validate_pagination(*values)

    def test_catalog_filters_are_trimmed_and_validated(self):
        self.assertEqual(
            validate_catalog_filters("  soda  ", "  Drinks ", "2", "15"),
            ("soda", "Drinks", 2, 15),
        )

    def test_catalog_search_length_is_bounded(self):
        with self.assertRaises(ValueError):
            validate_catalog_filters("x" * (MAX_SEARCH_LENGTH + 1))

    def test_catalog_filter_length_is_bounded(self):
        with self.assertRaises(ValueError):
            validate_catalog_filters(category="x" * 141)

    def test_catalog_filters_must_be_text(self):
        for values in ((123, ""), ("", ["category"])):
            with self.subTest(values=values), self.assertRaises(ValueError):
                validate_catalog_filters(*values)

    def test_like_metacharacters_are_escaped(self):
        self.assertEqual(escape_like("50%_off!"), "50!%!_off!!")
