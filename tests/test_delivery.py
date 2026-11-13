import unittest

from intelligent_ordering.utils.delivery import (
    DELIVERY_TRANSITIONS,
    delivery_quote_token,
    validate_delivery_fee,
    validate_delivery_text,
    validate_delivery_transition,
)


class TestDeliveryValidation(unittest.TestCase):
    def test_delivery_route_and_failure_retry(self):
        route = [
            "Awaiting Assignment", "Assigned", "Preparing", "Ready for Dispatch",
            "Dispatched", "In Transit", "Failed", "Assigned", "Preparing",
            "Ready for Dispatch", "Dispatched", "In Transit", "Delivered",
        ]
        for before, after in zip(route, route[1:]):
            self.assertEqual(validate_delivery_transition(before, after), after)

    def test_invalid_transitions_and_terminal_states(self):
        for before, after in (
            ("Awaiting Assignment", "Delivered"), ("Assigned", "In Transit"),
            ("Dispatched", "Cancelled"), ("Delivered", "Assigned"),
            ("Cancelled", "Assigned"), ("In Transit", "Assigned"),
            ("Failed", "Delivered"), ("Unknown", "Assigned"), ("Assigned", []),
        ):
            with self.subTest(before=before, after=after), self.assertRaises(ValueError):
                validate_delivery_transition(before, after)
        for status in DELIVERY_TRANSITIONS:
            self.assertEqual(validate_delivery_transition(status, status), status)

    def test_personnel_cannot_assign_cancel_or_restart_deliveries(self):
        for before, after in (
            ("Awaiting Assignment", "Assigned"), ("Assigned", "Cancelled"),
            ("Failed", "Assigned"), ("Failed", "Cancelled"),
        ):
            with self.assertRaises(ValueError):
                validate_delivery_transition(before, after, personnel=True)
        self.assertEqual(
            validate_delivery_transition("In Transit", "Delivered", personnel=True), "Delivered"
        )

    def test_delivery_fees_allow_free_delivery_and_reject_invalid_money(self):
        self.assertEqual(validate_delivery_fee("0"), 0)
        self.assertEqual(validate_delivery_fee("125.50"), 125.5)
        for value in ("nan", "Infinity", -1, True, None, "1.001", 250001):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_delivery_fee(value)

    def test_review_token_changes_when_area_fee_or_currency_changes(self):
        token = delivery_quote_token("Central", 100, "KES")
        self.assertEqual(token, delivery_quote_token("Central", "100.00", "KES"))
        for area, fee, currency in (
            ("West", 100, "KES"), ("Central", 0, "KES"), ("Central", 100, "USD"),
        ):
            self.assertNotEqual(token, delivery_quote_token(area, fee, currency))

    def test_notes_are_bounded_and_required_reasons_cannot_be_blank(self):
        self.assertEqual(validate_delivery_text("  Customer unavailable  ", "Notes"), "Customer unavailable")
        for value in (None, {}, "x" * 1001):
            with self.assertRaises(ValueError):
                validate_delivery_text(value, "Notes")
        with self.assertRaises(ValueError):
            validate_delivery_text(" ", "Reason", required=True)
