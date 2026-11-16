import importlib.util
import json
import sqlite3
import sys
import types
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

from test_mpesa import CONFIG, success_callback


class PaymentError(Exception):
    pass


def throw(message, *args):
    raise PaymentError(message)


def load_service():
    frappe = types.ModuleType("frappe")
    frappe.whitelist = lambda **kwargs: lambda function: function
    frappe.ValidationError = PaymentError
    frappe.PermissionError = PaymentError
    frappe.DoesNotExistError = PaymentError
    frappe.throw = Mock(side_effect=throw)
    frappe.db = Mock()
    frappe.conf = {"mpesa": CONFIG}
    frappe.session = types.SimpleNamespace(user="customer@example.test")
    frappe.flags = types.SimpleNamespace()
    frappe.get_doc = Mock()
    frappe.get_roles = Mock(return_value=["Customer"])
    utils = types.ModuleType("frappe.utils")
    utils.get_datetime = lambda value: value
    utils.now_datetime = datetime.now
    path = Path(__file__).parents[1] / "intelligent_ordering/api/payments.py"
    spec = importlib.util.spec_from_file_location("payments_under_test", path)
    service = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"frappe": frappe, "frappe.utils": utils}):
        spec.loader.exec_module(service)
    return service, frappe


class TestPaymentWorkflow(unittest.TestCase):
    def setUp(self):
        self.service, self.frappe = load_service()
        self.payment = Mock(
            name="PAY-1", order="SO-1", customer="customer",
            phone_number="254712345678", amount=250, environment="Sandbox",
            status="Pending", checkout_request_id="checkout-1",
            merchant_request_id="merchant-1", callback_response=json.dumps(success_callback()),
        )
        self.payment.get.side_effect = lambda field: getattr(self.payment, field, None)
        self.payment.name = "PAY-1"
        self.order = Mock(total=250, currency="KES", payment_status="Unpaid", status="Pending")
        self.order.name = "SO-1"
        self.frappe.get_doc.return_value = self.order
        self.client = Mock()
        self.client.config = CONFIG
        self.client.query.return_value = {
            "ResponseCode": "0", "ResultCode": "0",
            "CheckoutRequestID": "checkout-1", "MerchantRequestID": "merchant-1",
        }
        self.client_patch = patch.object(self.service, "_client", return_value=self.client)
        self.save_patch = patch.object(self.service, "_save")
        self.active_patch = patch.object(self.service, "_active_payment", return_value=None)
        self.client_patch.start()
        self.save = self.save_patch.start()
        self.active = self.active_patch.start()
        self.addCleanup(self.client_patch.stop)
        self.addCleanup(self.save_patch.stop)
        self.addCleanup(self.active_patch.stop)

    def test_finance_overview_calculates_verified_collections_and_currency_balances(self):
        self.frappe.session.user = "finance@example.test"
        self.frappe.get_roles.return_value = ["Finance Manager"]
        database = sqlite3.connect(":memory:")
        self.addCleanup(database.close)
        database.row_factory = sqlite3.Row
        database.create_function("CURDATE", 0, lambda: "2026-11-15")
        database.create_function("GREATEST", 2, max)
        database.create_function("YEARWEEK", 2, lambda value, mode: (
            datetime.fromisoformat(value).strftime("%G-W%V") if value else None
        ))
        database.create_function("DATE_FORMAT", 2, lambda value, pattern: (
            datetime.fromisoformat(value).strftime(pattern) if value else None
        ))
        database.executescript("""
            CREATE TABLE `tabSales Order` (name TEXT, status TEXT, currency TEXT, total NUMERIC);
            CREATE TABLE `tabPayment Transaction` (`order` TEXT, status TEXT, amount NUMERIC, transaction_date TEXT, payment_method TEXT);
            INSERT INTO `tabSales Order` VALUES
                ('PAID', 'Completed', 'KES', 100), ('OPEN', 'Pending', 'KES', 80),
                ('CANCELLED', 'Cancelled', 'KES', 200), ('FOREIGN', 'Pending', 'USD', 10);
            INSERT INTO `tabPayment Transaction` VALUES
                ('PAID', 'Successful', 100, '2026-11-15', 'M-Pesa'),
                ('OPEN', 'Pending', 80, '2026-11-15', 'M-Pesa'),
                ('OPEN', 'Failed', 80, '2026-11-15', 'M-Pesa'),
                ('OPEN', 'Reversed', 25, '2026-11-15', 'M-Pesa'),
                ('CANCELLED', 'Successful', 20, '2026-10-01', 'M-Pesa'),
                ('FOREIGN', 'Successful', 3, '2026-11-14', 'M-Pesa');
        """)
        self.frappe.db.sql.side_effect = lambda query, **kwargs: [
            dict(row) for row in database.execute(query).fetchall()
        ]
        result = self.service.finance_overview()
        totals = {row["currency"]: row for row in result["payments"]}
        self.assertEqual(totals["KES"], {
            "currency": "KES", "collected": 120, "pending": 80, "failed": 80, "reversed": 25,
            "daily_revenue": 100, "weekly_revenue": 100, "monthly_revenue": 100,
        })
        self.assertEqual(totals["USD"]["collected"], 3)
        self.assertEqual({row["currency"]: row["outstanding"] for row in result["outstanding"]},
                         {"KES": 80, "USD": 7})
        self.assertIn({
            "payment_method": "M-Pesa", "status": "Successful",
            "currency": "KES", "transactions": 2, "amount": 120,
        }, result["methods"])

    def test_finance_overview_rejects_unrelated_roles_before_querying_records(self):
        for role in ("Customer", "Delivery Staff", "Delivery Manager", "Customer Support",
                     "Inventory Manager", "Order Manager"):
            with self.subTest(role=role), self.assertRaises(PaymentError):
                self.frappe.get_roles.return_value = [role]
                self.service.finance_overview()
        self.frappe.db.sql.assert_not_called()

    def test_transaction_detail_returns_linked_order_and_server_reconciliation_authority(self):
        self.frappe.session.user = "staff@example.test"
        self.frappe.get_doc.return_value = self.payment
        self.frappe.db.get_value.return_value = {"name": "SO-1", "status": "Confirmed", "total": 250}
        for role, allowed in (("Finance Manager", True), ("Store Manager", False), ("Order Manager", False)):
            with self.subTest(role=role):
                self.frappe.get_roles.return_value = [role]
                result = self.service.get_transaction("PAY-1")
                self.assertEqual(result["can_reconcile"], allowed)
                self.assertEqual(result["order_summary"]["name"], "SO-1")
        self.payment.check_permission.assert_called_with("read")

    def test_verified_payment_marks_paid_without_confirming_or_touching_inventory(self):
        self.service._reconcile(self.payment)
        self.assertEqual(self.payment.status, "Successful")
        self.assertEqual(self.payment.mpesa_receipt_number, "TEST1234567")
        self.order.db_set.assert_called_once_with("payment_status", "Paid", update_modified=True)
        self.order.save.assert_not_called()
        self.assertEqual(self.order.status, "Pending")

    def test_query_success_without_callback_does_not_mark_paid(self):
        self.payment.callback_response = ""
        self.service._reconcile(self.payment)
        self.assertEqual(self.payment.status, "Pending")
        self.order.db_set.assert_not_called()

    def test_mismatching_identifiers_do_not_mark_paid(self):
        self.client.query.return_value["CheckoutRequestID"] = "different"
        self.service._reconcile(self.payment)
        self.assertEqual(self.payment.status, "Pending")
        self.order.db_set.assert_not_called()

    def test_callback_amount_phone_and_identifier_checks(self):
        parsed = self.service.parse_callback(success_callback())
        for field, value in (
            ("amount", 1), ("phone", "254711111111"),
            ("checkout_request_id", "other"), ("merchant_request_id", "other"),
        ):
            with self.subTest(field=field), self.assertRaises(PaymentError):
                self.service._validate_callback(self.payment, {**parsed, field: value})

    def test_failed_query_allows_retry_but_does_not_change_order(self):
        self.payment.callback_response = ""
        self.client.query.return_value.update(ResultCode="1037", ResultDesc="Timeout")
        self.service._reconcile(self.payment)
        self.assertEqual(self.payment.status, "Failed")
        self.order.db_set.assert_not_called()
        self.order.save.assert_not_called()

    def test_provider_cancellation_status(self):
        self.payment.callback_response = ""
        self.client.query.return_value.update(ResultCode="1032", ResultDesc="Cancelled")
        self.service._reconcile(self.payment)
        self.assertEqual(self.payment.status, "Cancelled")
        self.order.db_set.assert_not_called()

    def test_success_callback_and_failed_query_do_not_enable_another_charge(self):
        self.client.query.return_value.update(ResultCode="1037", ResultDesc="Timeout")
        self.service._reconcile(self.payment)
        self.assertEqual(self.payment.status, "Pending")
        self.order.db_set.assert_not_called()

    def test_duplicate_reconciliation_is_idempotent(self):
        self.service._reconcile(self.payment)
        self.service._reconcile(self.payment)
        self.order.db_set.assert_called_once()
        self.client.query.assert_called_once()

    def test_conflicting_callback_and_query_remain_unresolved(self):
        payload = success_callback()
        payload["Body"]["stkCallback"]["ResultCode"] = 1032
        self.payment.callback_response = json.dumps(payload)
        self.service._reconcile(self.payment)
        self.assertEqual(self.payment.status, "Pending")
        self.order.db_set.assert_not_called()

    def test_status_query_transport_failure_is_not_payment_failure(self):
        self.client.query.side_effect = self.service.DarajaError("Unavailable")
        self.service._reconcile(self.payment)
        self.assertEqual(self.payment.status, "Pending")
        self.assertIn("unresolved", self.payment.failure_description)
        self.order.db_set.assert_not_called()

    def test_customers_cannot_reconcile_or_view_staff_records(self):
        with self.assertRaises(PaymentError):
            self.service.reconcile_payment("PAY-1")
        with self.assertRaises(PaymentError):
            self.service.get_transaction("PAY-1")

    def test_invalid_callback_token_is_rejected(self):
        with self.assertRaises(PaymentError):
            self.service.callback(token="bad")

    def test_initiation_commits_attempt_before_external_side_effect(self):
        self.payment.status = "Initiated"
        self.payment.checkout_request_id = ""
        self.frappe.get_doc.side_effect = lambda doctype, *args, **kwargs: (
            self.payment if isinstance(doctype, dict) else self.order
        )
        self.frappe.db.get_value.return_value = None
        self.client.initiate.return_value = {
            "ResponseCode": "0", "MerchantRequestID": "merchant-1",
            "CheckoutRequestID": "checkout-1",
        }
        events = []
        self.frappe.db.commit.side_effect = lambda: events.append("commit")
        self.client.initiate.side_effect = lambda *args: (
            events.append("stk") or {
                "ResponseCode": "0", "MerchantRequestID": "merchant-1",
                "CheckoutRequestID": "checkout-1",
            }
        )
        with (
            patch.object(self.service, "_owned_order", return_value=self.order),
            patch.object(self.service, "_locked_payment", return_value=self.payment),
        ):
            result = self.service.initiate_payment("SO-1", "0712345678")
        self.assertEqual(events, ["commit", "stk"])
        self.assertEqual(result["status"], "Pending")
        self.assertEqual(self.client.initiate.call_args.args[2], 250)

    def test_duplicate_initiation_returns_existing_attempt(self):
        self.active.return_value = "PAY-1"
        self.frappe.get_doc.side_effect = lambda doctype, *args, **kwargs: (
            self.order if doctype == "Sales Order" else self.payment
        )
        with patch.object(self.service, "_owned_order", return_value=self.order):
            self.service.initiate_payment("SO-1", "0712345678")
        self.client.initiate.assert_not_called()
        self.frappe.db.commit.assert_not_called()

    def test_successful_callback_endpoint_is_idempotent(self):
        self.frappe.db.get_value.return_value = "PAY-1"
        self.payment.callback_response = ""
        self.frappe.request = Mock()
        self.frappe.request.get_data.return_value = json.dumps(success_callback()).encode()
        with patch.object(self.service, "_locked_payment", return_value=self.payment):
            first = self.service.callback(token="x" * 43)
            self.frappe.request.get_data.return_value = json.dumps(
                success_callback(), sort_keys=True
            ).encode()
            duplicate = self.service.callback(token="x" * 43)
        self.assertEqual(first["ResultCode"], 0)
        self.assertEqual(duplicate["ResultCode"], 0)
        self.order.db_set.assert_called_once()

    def test_failed_callback_is_verified_against_query(self):
        self.frappe.db.get_value.return_value = "PAY-1"
        self.payment.callback_response = ""
        payload = success_callback()
        payload["Body"]["stkCallback"]["ResultCode"] = 1032
        payload["Body"]["stkCallback"].pop("CallbackMetadata")
        self.frappe.request = Mock()
        self.frappe.request.get_data.return_value = json.dumps(payload).encode()
        self.client.query.return_value.update(ResultCode="1032", ResultDesc="Cancelled")
        with patch.object(self.service, "_locked_payment", return_value=self.payment):
            result = self.service.callback(token="x" * 43)
        self.assertEqual(result["ResultCode"], 0)
        self.assertEqual(self.payment.status, "Cancelled")
        self.order.db_set.assert_not_called()

    def test_invalid_callback_body_does_not_mutate_payment(self):
        self.frappe.db.get_value.return_value = "PAY-1"
        self.frappe.request = Mock()
        self.frappe.request.get_data.return_value = b'{"Body": {}}'
        with self.assertRaises(PaymentError):
            self.service.callback(token="x" * 43)
        self.save.assert_not_called()

    def test_unknown_stk_outcome_stays_initiated_and_blocks_automatic_retry(self):
        self.payment.status = "Initiated"
        self.frappe.db.get_value.return_value = None
        self.frappe.get_doc.side_effect = lambda doctype, *args, **kwargs: (
            self.payment if isinstance(doctype, dict) else self.order
        )
        self.client.initiate.side_effect = self.service.DarajaError("Timeout")
        with (
            patch.object(self.service, "_owned_order", return_value=self.order),
            patch.object(self.service, "_locked_payment", return_value=self.payment),
        ):
            result = self.service.initiate_payment("SO-1", "0712345678")
        self.assertEqual(result["status"], "Initiated")
        self.assertIn("unknown", result["failure_description"])

    def test_expiry_is_disabled_by_default(self):
        self.frappe.session.user = "Administrator"
        with self.assertRaisesRegex(PaymentError, "not configured"):
            self.service.expire_unpaid_order("SO-1")
