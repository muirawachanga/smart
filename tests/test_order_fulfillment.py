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


if __name__ == "__main__":
    unittest.main()
