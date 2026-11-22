import importlib.util
import sys
import types
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch


ROOT = Path(__file__).parents[1]


class FulfillmentError(Exception):
    pass


def load_service():
    frappe = types.ModuleType("frappe")
    frappe.conf = {}
    frappe.flags = types.SimpleNamespace()
    frappe.ValidationError = FulfillmentError
    frappe.throw = Mock(side_effect=lambda message, *args: (_ for _ in ()).throw(FulfillmentError(message)))
    frappe.get_all = Mock(return_value=[types.SimpleNamespace(name="SO-1")])
    frappe.get_doc = Mock()
    frappe.db = Mock()
    frappe.log_error = Mock()
    frappe.get_traceback = Mock(return_value="Stock validation failed")
    utils = types.ModuleType("frappe.utils")
    utils.now_datetime = lambda: datetime(2026, 11, 18, 12)
    path = ROOT / "intelligent_ordering/utils/order_fulfillment.py"
    spec = importlib.util.spec_from_file_location("order_fulfillment_under_test", path)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"frappe": frappe, "frappe.utils": utils}):
        spec.loader.exec_module(module)
    return module, frappe


class TestOrderFulfillment(unittest.TestCase):
    def setUp(self):
        self.service, self.frappe = load_service()
        self.confirmed_at = datetime(2026, 11, 18, 11)
        self.order = types.SimpleNamespace(
            name="SO-1", status="Confirmed", confirmed_at=self.confirmed_at,
            preparation_minutes=20, payment_method="Cash on Delivery",
            payment_status="Unpaid", save=Mock(),
        )
        self.frappe.get_doc.side_effect = lambda *args, **kwargs: self.order

    def test_preparation_time_uses_validated_site_configuration(self):
        self.assertEqual(self.service.preparation_minutes(), 20)
        self.frappe.conf = {"order_fulfillment": {"preparation_minutes": 45}}
        self.assertEqual(self.service.preparation_minutes(), 45)
        for value in (True, 0, -1, 1441, "20"):
            self.frappe.conf = {"order_fulfillment": {"preparation_minutes": value}}
            with self.subTest(value=value), self.assertRaises(FulfillmentError):
                self.service.preparation_minutes()

    def test_confirmation_advances_to_processing_then_ready_after_prep_time(self):
        self.frappe.db.exists.return_value = "PAY-COD"
        self.assertEqual(self.service.advance_confirmed_orders(), 1)
        self.assertEqual(self.order.status, "Processing")
        self.assertTrue(self.frappe.flags.processing_order_fulfillment is False)

        with patch.object(
            self.service, "now_datetime",
            return_value=self.confirmed_at + timedelta(minutes=19),
            create=True,
        ):
            self.assertEqual(self.service.advance_confirmed_orders(), 0)
        self.assertEqual(self.order.status, "Processing")

        with patch.object(
            self.service, "now_datetime",
            return_value=self.confirmed_at + timedelta(minutes=20),
            create=True,
        ):
            self.assertEqual(self.service.advance_confirmed_orders(), 1)
        self.assertEqual(self.order.status, "Ready for Delivery")
        self.assertEqual(self.order.save.call_count, 2)

    def test_m_pesa_waits_for_verified_payment_before_ready_for_delivery(self):
        self.order.status = "Processing"
        self.order.payment_method = "M-Pesa"
        self.order.payment_status = "Unpaid"
        self.frappe.db.exists.return_value = False
        with patch.object(
            self.service, "now_datetime",
            return_value=self.confirmed_at + timedelta(minutes=21),
            create=True,
        ):
            self.assertEqual(self.service.advance_confirmed_orders(), 0)
        self.assertEqual(self.order.status, "Processing")
        self.order.payment_status = "Paid"
        with patch.object(
            self.service, "now_datetime",
            return_value=self.confirmed_at + timedelta(minutes=21),
            create=True,
        ):
            self.assertEqual(self.service.advance_confirmed_orders(), 1)
        self.assertEqual(self.order.status, "Ready for Delivery")

    def test_paid_mpesa_pending_confirms_only_with_successful_payment(self):
        self.order.status = "Pending"
        self.order.payment_method = "M-Pesa"
        self.order.payment_status = "Paid"
        self.frappe.db.exists.return_value = None
        self.assertEqual(self.service.advance_confirmed_orders(), 0)
        self.assertEqual(self.order.status, "Pending")
        self.frappe.db.exists.return_value = "PAY-1"
        self.assertEqual(self.service.advance_confirmed_orders(), 1)
        self.assertEqual(self.order.status, "Confirmed")
        self.order.save.assert_called_once_with(ignore_permissions=True)
        self.frappe.db.exists.assert_called_with(
            "Payment Transaction", {"order": "SO-1", "payment_method": "M-Pesa", "status": "Successful"},
        )

    def test_blocked_order_rolls_back_and_does_not_stop_later_orders(self):
        blocked = types.SimpleNamespace(
            name="SO-1", status="Pending", payment_method="M-Pesa", payment_status="Paid",
            save=Mock(side_effect=FulfillmentError("Insufficient stock")),
        )
        self.order.name = "SO-2"
        self.frappe.get_all.return_value = [
            types.SimpleNamespace(name="SO-1"), types.SimpleNamespace(name="SO-2"),
        ]
        self.frappe.get_doc.side_effect = lambda doctype, name, **kwargs: (
            blocked if name == "SO-1" else self.order
        )
        self.frappe.db.exists.return_value = "PAY-1"
        self.assertEqual(self.service.advance_confirmed_orders(), 1)
        self.frappe.db.rollback.assert_called_once_with(save_point="fulfillment_order")
        self.assertIn("SO-1", self.frappe.log_error.call_args.kwargs["message"])
        self.assertEqual(self.order.status, "Processing")

    def test_skipped_first_page_does_not_block_later_ready_order(self):
        skipped = [types.SimpleNamespace(name=f"SO-{number:03}") for number in range(100)]
        self.frappe.get_all.side_effect = [skipped, [types.SimpleNamespace(name="SO-100")]]
        waiting = types.SimpleNamespace(
            name="waiting", status="Processing", confirmed_at=self.confirmed_at,
            preparation_minutes=20, payment_method="M-Pesa", payment_status="Unpaid",
        )
        self.frappe.get_doc.side_effect = lambda doctype, name, **kwargs: (
            self.order if name == "SO-100" else waiting
        )
        self.assertEqual(self.service.advance_confirmed_orders(), 1)
        self.assertEqual(self.order.status, "Processing")
        self.assertEqual(self.frappe.get_all.call_args_list[1].kwargs["filters"]["name"], [">", "SO-099"])

    def test_completion_requires_paid_order_and_customer_confirmed_delivery(self):
            delivery = types.SimpleNamespace(order="SO-1", status="Delivered", customer_receipt_confirmed=1)
            self.order.status = "Ready for Delivery"
            self.order.payment_status = "Unpaid"
            self.assertFalse(self.service.complete_order_after_customer_receipt(self.order, delivery))
            self.assertEqual(self.order.save.call_count, 0)
            self.order.payment_status = "Paid"
            self.assertTrue(self.service.complete_order_after_customer_receipt(self.order, delivery))
            self.assertEqual(self.order.status, "Completed")
            self.order.save.assert_called_once_with(ignore_permissions=True)
            self.assertFalse(self.frappe.flags.processing_delivery)


if __name__ == "__main__":
    unittest.main()
