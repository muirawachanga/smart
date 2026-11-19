import importlib.util
import sqlite3
from html import escape
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


class AccessError(Exception):
    pass


def load_customers():
    frappe = types.ModuleType("frappe")
    frappe.whitelist = lambda **kwargs: lambda function: function
    frappe.ValidationError = frappe.PermissionError = AccessError
    frappe.throw = Mock(side_effect=lambda message, *args: (_ for _ in ()).throw(AccessError(message)))
    frappe.session = types.SimpleNamespace(user="customer@example.test")
    frappe.flags = types.SimpleNamespace()
    frappe.db = Mock()
    frappe.get_doc = Mock()
    frappe.get_all = Mock(return_value=[])
    utils = types.ModuleType("frappe.utils")
    utils.now_datetime = lambda: "2026-11-14 23:00:00"
    utils.escape_html = escape
    utils.validate_email_address = lambda value, throw: value
    limiter = types.ModuleType("frappe.rate_limiter")
    limiter.rate_limit = lambda **kwargs: lambda function: function
    checkout = types.ModuleType("intelligent_ordering.api.checkout")
    checkout._require_customer = Mock(return_value=frappe.session.user)
    checkout._save_customer_profile = Mock()
    checkout._serialize_order = Mock(return_value={"status": "Cancelled"})
    orders = types.ModuleType("intelligent_ordering.api.orders")
    orders._require_order_staff = Mock()
    orders._validate_order_name = lambda value: value
    audit = types.ModuleType("intelligent_ordering.utils.audit")
    audit.record_admin_event = Mock()
    user = types.ModuleType("frappe.core.doctype.user.user")
    user.is_signup_disabled = Mock(return_value=False)
    policy = types.ModuleType("intelligent_ordering.api.policies")
    policy.require_acceptance = Mock()
    authentication = types.ModuleType("intelligent_ordering.utils.authentication")
    authentication.validate_new_password = Mock()
    modules = {
        "frappe": frappe, "frappe.utils": utils, "frappe.rate_limiter": limiter,
        "intelligent_ordering.api.checkout": checkout, "intelligent_ordering.api.orders": orders,
        "intelligent_ordering.utils.audit": audit, "frappe.core.doctype.user.user": user,
        "intelligent_ordering.api.policies": policy,
        "intelligent_ordering.utils.authentication": authentication,
    }
    path = Path(__file__).parents[1] / "intelligent_ordering/api/customers.py"
    spec = importlib.util.spec_from_file_location("customers_under_test", path)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, modules):
        spec.loader.exec_module(module)
    return module, frappe, modules


class TestCustomerPortal(unittest.TestCase):
    def setUp(self):
        self.api, self.frappe, self.modules = load_customers()

    def test_registration_creates_website_customer_without_portal_default_roles(self):
        self.frappe.session.user = "Guest"
        self.frappe.db.exists.return_value = False
        self.frappe.get_doc.return_value.flags.email_sent = True
        with patch.dict(sys.modules, self.modules):
            result = self.api.register(
                "Customer@Example.test", " Test Customer ", "+254700000000",
                "a strong unique passphrase", "a strong unique passphrase",
                "TERMS-1", "PRIVACY-1", "1", "1",
            )
        doc = self.frappe.get_doc.call_args_list[0].args[0]
        self.assertEqual(doc["roles"], [{"role": "Customer"}])
        self.assertEqual(doc["user_type"], "Website User")
        self.assertEqual(doc["email"], "customer@example.test")
        self.assertEqual(doc["first_name"], "Test Customer")
        self.assertIn("Account created", result["message"])
        consent = self.frappe.get_doc.call_args_list[1].args[0]
        self.assertEqual(consent["terms_version"], "TERMS-1")
        self.assertEqual(consent["privacy_version"], "PRIVACY-1")
        self.assertEqual(consent["marketing_consent"], 0)
        self.assertNotIn(doc["new_password"], repr(result))

    def test_disabled_registration_and_existing_accounts_do_not_mutate_users(self):
        self.frappe.session.user = "Guest"
        signup = self.modules["frappe.core.doctype.user.user"]
        signup.is_signup_disabled.return_value = True
        with patch.dict(sys.modules, self.modules), self.assertRaises(AccessError):
            self.api.register("customer@example.test", "Customer", "+254700000000")
        signup.is_signup_disabled.return_value = False
        self.frappe.db.exists.return_value = True
        with patch.dict(sys.modules, self.modules), self.assertRaises(AccessError):
            self.api.register("customer@example.test", "Customer", "+254700000000")
        self.frappe.get_doc.assert_not_called()

    def test_registration_with_missing_acceptance_does_not_create_a_user(self):
        self.frappe.session.user = "Guest"
        self.modules["intelligent_ordering.api.policies"].require_acceptance.side_effect = AccessError("Accept policies")
        with patch.dict(sys.modules, self.modules), self.assertRaises(AccessError):
            self.api.register("customer@example.test", "Customer", "+254700000000")
        self.frappe.get_doc.assert_not_called()

    def test_alternate_signup_cannot_bypass_customer_policy_consent(self):
        with self.assertRaises(AccessError):
            self.api.sign_up("customer@example.test", "Customer")

    def test_address_mutations_reject_other_customer_before_loading_address(self):
        profile = types.SimpleNamespace(name="OWN-PROFILE")
        self.frappe.delete_doc = Mock()
        with patch.object(self.api, "_profile", return_value=profile):
            self.frappe.db.exists.return_value = False
            for operation in (
                lambda: self.api.save_address("Road", "City", address_name="OTHER-ADDRESS"),
                lambda: self.api.delete_address("OTHER-ADDRESS"),
            ):
                with self.assertRaises(AccessError):
                    operation()
        self.frappe.get_doc.assert_not_called()
        self.frappe.delete_doc.assert_not_called()

    def test_saved_address_is_bound_to_session_profile_and_default_is_exclusive(self):
        profile = types.SimpleNamespace(name="OWN-PROFILE")
        self.frappe.db.count.return_value = 0
        self.frappe.db.get_value.return_value = None
        address = Mock(name="address")
        address.name = None
        self.frappe.get_doc.return_value = address
        with patch.object(self.api, "_profile", return_value=profile):
            self.api.save_address(" Road ", " City ", is_default="1")
        self.assertEqual(self.frappe.get_doc.call_args.args[0]["customer"], "OWN-PROFILE")
        self.assertEqual(address.update.call_args.args[0]["address_line_1"], "Road")
        self.assertEqual(address.update.call_args.args[0]["is_default"], 1)
        self.assertEqual(self.frappe.db.sql.call_args.args[1], "OWN-PROFILE")

    def test_payment_history_joins_own_order_and_never_exposes_provider_payload(self):
        self.frappe.db.sql.return_value = []
        with patch.object(self.api, "_profile", return_value=types.SimpleNamespace(name="OWN-PROFILE")):
            self.api.payment_history(page=2, page_size=10)
        sql, params = self.frappe.db.sql.call_args.args
        self.assertIn("WHERE o.customer = %s", sql)
        self.assertNotIn("callback_response", sql)
        self.assertEqual(params, ("OWN-PROFILE", 11, 10))
        with self.assertRaises(AccessError):
            self.api.payment_history(page=0)

    def test_payment_search_normalizes_values_and_cannot_find_another_customers_payment(self):
        database = sqlite3.connect(":memory:")
        self.addCleanup(database.close)
        database.row_factory = sqlite3.Row
        database.executescript("""
            CREATE TABLE `tabSales Order` (name TEXT, customer TEXT, currency TEXT);
            CREATE TABLE `tabPayment Transaction` (
                name TEXT, `order` TEXT, amount NUMERIC, payment_method TEXT, status TEXT,
                phone_number TEXT, mpesa_receipt_number TEXT, transaction_date TEXT, creation TEXT
            );
            INSERT INTO `tabSales Order` VALUES ('OWN', 'OWN-PROFILE', 'KES'), ('OTHER', 'OTHER-PROFILE', 'KES');
            INSERT INTO `tabPayment Transaction` VALUES
                ('PENDING', 'OWN', 4, 'M-Pesa', 'Pending', '254712345678', '', NULL, '2026-11-16'),
                ('PAID', 'OWN', 4, 'M-Pesa', 'Successful', '254712345678', 'TEST1234567', '2026-11-15', '2026-11-15'),
                ('PRIVATE', 'OTHER', 4, 'M-Pesa', 'Successful', '254712345678', 'OTHER123456', '2026-11-16', '2026-11-16');
        """)
        self.frappe.db.sql.side_effect = lambda query, params, **kwargs: [
            dict(row) for row in database.execute(query.replace("%s", "?"), params)
        ]
        with patch.object(self.api, "_profile", return_value=types.SimpleNamespace(name="OWN-PROFILE")):
            result = self.api.payment_history(search="0712 345 678", page_size=1)
            self.assertEqual([row["name"] for row in result["transactions"]], ["PENDING"])
            self.assertTrue(result["has_more"])
            second = self.api.payment_history(search="+254712345678", page=2, page_size=1)
            self.assertEqual([row["name"] for row in second["transactions"]], ["PAID"])
            receipt = self.api.payment_history(search="test1234567", search_by="receipt")
            self.assertEqual([row["name"] for row in receipt["transactions"]], ["PAID"])
            self.assertEqual(self.api.payment_history(search="OTHER123456", search_by="receipt")["transactions"], [])
        self.assertNotIn("callback_response", repr(result))

    def test_invalid_payment_search_never_queries_transactions(self):
        with patch.object(self.api, "_profile", return_value=types.SimpleNamespace(name="OWN")):
            for args in ({"search": "bad"}, {"search": "%", "search_by": "receipt"},
                         {"search": "x" * 41}, {"search": []}, {"search_by": "unknown"}):
                with self.subTest(args=args), self.assertRaises(AccessError):
                    self.api.payment_history(**args)
        self.frappe.db.sql.assert_not_called()

    def test_tracking_and_cancellation_cannot_load_an_unowned_order(self):
        self.frappe.db.exists.return_value = False
        with patch.object(self.api, "_profile", return_value=types.SimpleNamespace(name="OWN-PROFILE")):
            for operation in (
                lambda: self.api.track_order("OTHER-ORDER"),
                lambda: self.api.confirm_delivery_receipt("OTHER-ORDER"),
                lambda: self.api.request_cancellation("OTHER-ORDER", "Reason"),
            ):
                with self.assertRaises(AccessError):
                    operation()
        self.frappe.get_doc.assert_not_called()

    def test_customer_tracking_shows_only_assigned_rider_display_name(self):
        order = types.SimpleNamespace(
            name="SO-1", status="Ready for Delivery", payment_status="Paid",
            modified="now", get=lambda field: None,
        )
        self.frappe.db.get_value.return_value = "Rider One"
        self.frappe.get_all.side_effect = lambda doctype, **kwargs: (
            [{
                "name": "DEL-1", "status": "Assigned", "assigned_delivery_person": "rider@example.test",
                "scheduled_delivery_date": "2026-11-19", "delivery_area": "Central", "modified": "now",
            }]
            if doctype == "Delivery" else []
        )
        with patch.object(self.api, "_owned_order", return_value=order):
            result = self.api.track_order("SO-1")
        self.assertEqual(result["delivery"]["assigned_rider"], "Rider One")
        self.assertNotIn("assigned_delivery_person", result["delivery"])
        self.assertEqual(result["delivery"]["delivery_area"], "Central")

    def test_customer_confirms_only_delivered_owned_order_and_completes_paid_order(self):
        order = types.SimpleNamespace(
            name="SO-1", status="Ready for Delivery", payment_status="Paid",
        )
        delivery = types.SimpleNamespace(
            name="DEL-1", order="SO-1", status="Delivered", customer_receipt_confirmed=0,
            assigned_delivery_person="rider@example.test", scheduled_delivery_date="2026-11-19",
            activities=[], append=Mock(), save=Mock(),
        )
        self.frappe.db.get_value.return_value = "DEL-1"
        self.frappe.get_doc.return_value = delivery
        receipt_completion = Mock()
        fulfillment = types.ModuleType("intelligent_ordering.utils.order_fulfillment")
        fulfillment.complete_order_after_customer_receipt = receipt_completion
        with patch.dict(sys.modules, {"intelligent_ordering.utils.order_fulfillment": fulfillment}), \
             patch.object(self.api, "_owned_order", return_value=order), \
             patch.object(self.api, "track_order", return_value={"delivery": {"status": "Delivered"}}):
            result = self.api.confirm_delivery_receipt("SO-1")
        self.assertEqual(result["delivery"]["status"], "Delivered")
        self.assertEqual(delivery.customer_receipt_confirmed, 1)
        self.assertEqual(delivery.customer_receipt_confirmed_by, self.frappe.session.user)
        delivery.append.assert_called_once()
        delivery.save.assert_called_once_with(ignore_permissions=True)
        receipt_completion.assert_called_once_with(order, delivery)

    def test_customer_cannot_confirm_receipt_before_delivery_is_marked_delivered(self):
        order = types.SimpleNamespace(name="SO-1")
        delivery = types.SimpleNamespace(name="DEL-1", order="SO-1", status="In Transit")
        self.frappe.db.get_value.return_value = "DEL-1"
        self.frappe.get_doc.return_value = delivery
        with patch.object(self.api, "_owned_order", return_value=order), \
             self.assertRaisesRegex(AccessError, "only after the rider"):
            self.api.confirm_delivery_receipt("SO-1")
        self.frappe.db.sql.assert_called_once()

    def test_cancellation_request_saves_only_request_and_restores_internal_flag(self):
        order = types.SimpleNamespace(
            name="SO-1", status="Pending", payment_status="Unpaid", total=125,
            cancellation_request_status=None, cancellation_response=None,
            save=Mock(),
        )
        with patch.object(self.api, "_owned_order", return_value=order), patch.object(
            self.api, "track_order", return_value={"order_status": "Pending"}
        ):
            result = self.api.request_cancellation("SO-1", " Please cancel ")
        self.assertEqual(result["order_status"], "Pending")
        self.assertEqual(order.status, "Pending")
        self.assertEqual(order.total, 125)
        self.assertEqual(order.payment_status, "Unpaid")
        self.assertEqual(order.cancellation_reason, "Please cancel")
        self.assertEqual(order.cancellation_request_status, "Requested")
        self.assertFalse(self.frappe.flags.processing_customer_cancellation)

    def test_duplicate_terminal_and_empty_cancellation_requests_are_rejected(self):
        for status, request_status, reason in (
            ("Completed", None, "Reason"), ("Cancelled", None, "Reason"),
            ("Pending", "Requested", "Reason"), ("Pending", None, ""),
        ):
            order = types.SimpleNamespace(status=status, cancellation_request_status=request_status, save=Mock())
            with patch.object(self.api, "_owned_order", return_value=order), self.assertRaises(AccessError):
                self.api.request_cancellation("SO-1", reason)
            order.save.assert_not_called()

    def test_rejected_request_can_be_resubmitted_without_retaining_old_approval_metadata(self):
        order = types.SimpleNamespace(
            name="SO-1", status="Pending", cancellation_request_status="Rejected",
            cancellation_response="Old response", cancellation_resolved_at="Yesterday",
            cancellation_resolved_by="manager@example.test", save=Mock(),
        )
        with patch.object(self.api, "_owned_order", return_value=order), patch.object(
            self.api, "track_order", return_value={"cancellation_request_status": "Requested"}
        ):
            self.api.request_cancellation("SO-1", "New reason")
        self.assertEqual(order.cancellation_request_status, "Requested")
        self.assertIsNone(order.cancellation_response)
        self.assertIsNone(order.cancellation_resolved_at)
        self.assertIsNone(order.cancellation_resolved_by)

    def test_resolution_requires_staff_before_document_lookup(self):
        self.api._require_order_staff.side_effect = AccessError("Denied")
        with self.assertRaises(AccessError):
            self.api.resolve_cancellation("SO-1", "Approved", "Response")
        self.frappe.get_doc.assert_not_called()

    def test_notification_read_checks_recipient_before_mutation(self):
        self.frappe.db.exists.return_value = False
        with patch.object(self.api, "_profile"), self.assertRaises(AccessError):
            self.api.read_notification("OTHER-NOTICE")
        self.frappe.db.set_value.assert_not_called()
        self.assertEqual(self.frappe.db.exists.call_args.args[1]["for_user"], "customer@example.test")

    def test_status_notifications_are_addressed_to_the_orders_actual_profile_user(self):
        path = Path(__file__).parents[1] / "intelligent_ordering/utils/customer_notifications.py"
        spec = importlib.util.spec_from_file_location("customer_notifications_under_test", path)
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, self.modules):
            spec.loader.exec_module(module)
        original = Mock()
        original.get.return_value = "Pending"
        doc = Mock()
        doc.doctype = "Sales Order"
        doc.name = "SO-1"
        doc.get_doc_before_save.return_value = original
        doc.get.side_effect = lambda field: "Confirmed" if field == "status" else "Pending"
        self.frappe.db.get_value.side_effect = ["ACTUAL-PROFILE", "actual-owner@example.test"]
        module.on_update(doc)
        notification = self.frappe.get_doc.call_args.args[0]
        self.assertEqual(notification["for_user"], "actual-owner@example.test")
        self.assertEqual(notification["document_name"], "SO-1")
        self.assertIn("Confirmed", notification["subject"])
