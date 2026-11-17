import unittest

from intelligent_ordering.utils.checkout import (
    checkout_cart_revision,
    validate_payment_method,
    validate_address,
    validate_customer_name,
    validate_order_status_transition,
    validate_phone,
    validate_request_token,
)


class TestCheckoutValidation(unittest.TestCase):
    def test_customer_name_is_trimmed_and_required(self):
        self.assertEqual(validate_customer_name("  Alex Doe "), "Alex Doe")
        with self.assertRaises(ValueError):
            validate_customer_name(" ")

    def test_phone_is_normalized_and_validated(self):
        self.assertEqual(validate_phone("+254 712-345-678"), "+254712345678")
        for value in ("", "call me", "123", "1" * 21):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_phone(value)

    def test_address_requires_line_and_city(self):
        self.assertEqual(
            validate_address("  1 Main Road ", " Nairobi "),
            {
                "address_line_1": "1 Main Road",
                "address_line_2": "",
                "city": "Nairobi",
                "region": "",
                "postal_code": "",
            },
        )
        with self.assertRaises(ValueError):
            validate_address("", "Nairobi")
        with self.assertRaises(ValueError):
            validate_address("1 Main Road", "")

    def test_request_token_must_be_a_uuid(self):
        token = "4ec2b6b5-31a2-4c7f-a301-86a87f1fb87f"
        self.assertEqual(validate_request_token(token), token)
        with self.assertRaises(ValueError):
            validate_request_token("not-a-token")

    def test_payment_method_accepts_only_supported_choices(self):
        self.assertEqual(validate_payment_method("M-Pesa"), "M-Pesa")
        self.assertEqual(validate_payment_method("Cash on Delivery"), "Cash on Delivery")
        for value in ("", "cash", "Paid", None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_payment_method(value)

    def test_order_status_transitions_are_sequential_and_terminal(self):
        self.assertEqual(
            validate_order_status_transition("Pending", "Confirmed"), "Confirmed"
        )
        self.assertEqual(
            validate_order_status_transition("Processing", "Cancelled"),
            "Cancelled",
        )
        for current, requested in (
            ("Pending", "Completed"),
            ("Completed", "Pending"),
            ("Cancelled", "Confirmed"),
            ("Pending", "Unknown"),
            ("Pending", ["Confirmed"]),
        ):
            with self.subTest(current=current, requested=requested):
                with self.assertRaises(ValueError):
                    validate_order_status_transition(current, requested)

    def test_cart_revision_changes_when_price_or_quantity_changes(self):
        base = [{"product": "SKU-1", "quantity": 2, "unit_price": 5, "currency": "KES"}]
        self.assertEqual(checkout_cart_revision(base), checkout_cart_revision(base))
        changed = [{**base[0], "unit_price": 6}]
        self.assertNotEqual(checkout_cart_revision(base), checkout_cart_revision(changed))


if __name__ == "__main__":
    unittest.main()
