import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from uuid import uuid4

from intelligent_ordering.utils.checkout import checkout_cart_revision


class AccessError(Exception):
    pass


def raise_error(message, *args):
    raise AccessError(message)


def load_modules():
    frappe = types.ModuleType("frappe")
    frappe.whitelist = lambda **kwargs: lambda function: function
    frappe.ValidationError = frappe.PermissionError = AccessError
    frappe.throw = Mock(side_effect=raise_error)
    frappe.db = Mock()
    frappe.session = types.SimpleNamespace(user="owner@example.test")
    frappe.get_roles = Mock(return_value=["Customer", "Order Manager"])
    frappe.get_doc = Mock()
    cart = types.ModuleType("intelligent_ordering.api.cart")
    cart.get_cart = Mock()
    rates = types.ModuleType("intelligent_ordering.utils.delivery_rates")
    rates.get_area_quote = Mock()
    rates.list_checkout_areas = Mock()
    inventory = types.ModuleType("intelligent_ordering.utils.inventory")
    inventory.validate_checkout_stock = Mock()

    def load(name, file):
        spec = importlib.util.spec_from_file_location(name, file)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    root = Path(__file__).parents[1] / "intelligent_ordering/api"
    with patch.dict(sys.modules, {
        "frappe": frappe,
        "intelligent_ordering.api.cart": cart,
        "intelligent_ordering.utils.delivery_rates": rates,
        "intelligent_ordering.utils.inventory": inventory,
    }):
        checkout = load("checkout_under_test", root / "checkout.py")
        with patch.dict(sys.modules, {"intelligent_ordering.api.checkout": checkout}):
            orders = load("orders_under_test", root / "orders.py")
    return frappe, checkout, orders


class TestCheckoutPageEndpoints(unittest.TestCase):
    def setUp(self):
        self.frappe, self.checkout, self.orders = load_modules()

    def test_support_can_list_orders_but_cannot_change_status(self):
        self.frappe.get_roles.return_value = ["Customer Support"]
        self.frappe.get_list = Mock(return_value=[])
        self.assertEqual(self.orders.list_orders()["orders"], [])
        with self.assertRaises(AccessError):
            self.orders.update_order_status("SO-1", "Confirmed")
        self.frappe.get_doc.assert_not_called()

    def test_recovery_requires_valid_token_and_owned_order(self):
        token = str(uuid4())
        self.frappe.db.get_value.side_effect = [
            types.SimpleNamespace(name="SO-1", customer="PROFILE-1"),
            "owner@example.test",
        ]
        self.assertEqual(self.checkout.get_checkout_attempt(token), {"order_name": "SO-1"})
        self.assertEqual(self.frappe.db.get_value.call_args.args[1], "PROFILE-1")
        self.frappe.db.get_value.side_effect = [
            types.SimpleNamespace(name="SO-1", customer="PROFILE-1"),
            "someone-else@example.test",
        ]
        with self.assertRaises(AccessError):
            self.checkout.get_checkout_attempt(token)
        with self.assertRaises(AccessError):
            self.checkout.get_checkout_attempt("not-a-uuid")

    def test_recovery_reports_no_prior_attempt(self):
        self.frappe.db.get_value.return_value = None
        self.assertEqual(self.checkout.get_checkout_attempt(str(uuid4())), {"order_name": None})

    def test_confirmation_does_not_grant_staff_access_to_other_customer_order(self):
        self.frappe.db.get_value.side_effect = [
            types.SimpleNamespace(name="SO-1", customer="PROFILE-1"),
            "other@example.test",
        ]
        with self.assertRaises(AccessError):
            self.orders.get_my_order("SO-1")
        self.frappe.db.get_value.side_effect = [
            types.SimpleNamespace(name="SO-1", customer="PROFILE-1"),
            "owner@example.test",
        ]
        self.frappe.get_doc.return_value = types.SimpleNamespace(name="SO-1")
        with patch.object(self.orders, "_serialize_order", return_value={"name": "SO-1"}):
            self.assertEqual(self.orders.get_my_order("SO-1"), {"name": "SO-1"})
        self.frappe.db.get_value.side_effect = [None]
        with self.assertRaisesRegex(AccessError, "unavailable"):
            self.orders.get_my_order("missing")
        self.frappe.get_doc.assert_called_once()

    def test_guest_confirmation_requires_login(self):
        self.frappe.session.user = "Guest"
        self.assertEqual(self.orders.get_my_order("SO-1"), {"requires_login": True})
        self.frappe.get_doc.assert_not_called()
        self.assertEqual(self.checkout.get_checkout_attempt(str(uuid4())), {"requires_login": True})
        self.frappe.db.get_value.assert_not_called()

    def test_order_rejects_changed_locked_product_price(self):
        item = {"product": "SKU-1", "quantity": 2, "unit_price": 50, "currency": "KES"}
        self.checkout.get_cart.return_value = {"items": [item], "currency": "KES"}
        self.frappe.db.get_value.return_value = None
        self.frappe.db.sql.return_value = [types.SimpleNamespace(
            price=60, currency="KES", category=None, enabled=1,
        )]
        with self.assertRaisesRegex(AccessError, "prices changed"):
            self.checkout.create_order(
                customer_name="Customer", phone="+254700000000",
                address_line_1="1 Main Road", city="Nairobi", request_token=str(uuid4()),
                cart_revision=checkout_cart_revision([item]),
            )
        self.checkout.validate_checkout_stock.assert_called_once_with([item])
        self.frappe.get_doc.assert_not_called()

    def test_order_rejects_unavailable_stock_before_creating_records(self):
        item = {"product": "SKU-1", "quantity": 2, "unit_price": 50, "currency": "KES"}
        self.checkout.get_cart.return_value = {"items": [item], "currency": "KES"}
        self.frappe.db.get_value.return_value = None
        self.checkout.validate_checkout_stock.side_effect = AccessError("Insufficient stock")
        with self.assertRaisesRegex(AccessError, "Insufficient stock"):
            self.checkout.create_order(
                customer_name="Customer", phone="+254700000000",
                address_line_1="1 Main Road", city="Nairobi", request_token=str(uuid4()),
                cart_revision=checkout_cart_revision([item]),
            )
        self.frappe.get_doc.assert_not_called()


if __name__ == "__main__":
    unittest.main()
