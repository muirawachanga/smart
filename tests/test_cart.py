import unittest

from intelligent_ordering.utils.cart import (
    MAX_CART_QUANTITY,
    merge_cart_items,
    parse_cart_items,
    round_money,
    validate_cart_quantity,
)


class TestCartInputValidation(unittest.TestCase):
    def test_add_and_merge_products_without_duplicate_lines(self):
        items = parse_cart_items(
            '[{"product":"SKU-1","quantity":2,"unit_price":0},'
            '{"product":"SKU-1","quantity":1},{"product":"SKU-2","quantity":3}]'
        )
        self.assertEqual(
            items,
            [
                {"product": "SKU-1", "quantity": 3},
                {"product": "SKU-2", "quantity": 3},
            ],
        )

    def test_merging_adds_quantities_for_existing_products(self):
        self.assertEqual(
            merge_cart_items(
                [{"product": "SKU-1", "quantity": 2}],
                [{"product": "SKU-1", "quantity": 1}],
            ),
            [{"product": "SKU-1", "quantity": 3}],
        )

    def test_rejects_empty_zero_negative_and_fractional_quantities(self):
        for quantity in (None, 0, -1, 1.5, True, "0", "-2", "1.5"):
            with self.subTest(quantity=quantity), self.assertRaises(ValueError):
                validate_cart_quantity(quantity)

    def test_rejects_quantities_above_limit(self):
        with self.assertRaises(ValueError):
            validate_cart_quantity(MAX_CART_QUANTITY + 1)

    def test_rejects_malformed_or_oversized_cart_payloads(self):
        for value in ("not json", "{}", '[{"product":"SKU-1"}]'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_cart_items(value)

    def test_rejects_product_identifiers_that_are_not_text(self):
        with self.assertRaises(ValueError):
            parse_cart_items([{"product": 42, "quantity": 1}])

    def test_rounds_totals_to_currency_precision(self):
        self.assertEqual(round_money("12.345"), 12.35)
        self.assertEqual(round_money("9.995"), 10.0)
        with self.assertRaises(ValueError):
            round_money("not-a-price")


if __name__ == "__main__":
    unittest.main()
