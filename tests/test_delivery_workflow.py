import base64
import importlib.util
import sys
import types
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import Mock, patch


ROOT = Path(__file__).parents[1]


class DeliveryError(Exception):
    pass


def load_module(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_services():
    frappe = types.ModuleType("frappe")
    frappe.whitelist = lambda **kwargs: lambda function: function
    frappe.ValidationError = frappe.PermissionError = frappe.DoesNotExistError = DeliveryError
    frappe.throw = Mock(side_effect=lambda message, *args: (_ for _ in ()).throw(DeliveryError(message)))
    frappe.db = Mock()
    frappe.conf = {}
    frappe.session = types.SimpleNamespace(user="Administrator")
    frappe.flags = types.SimpleNamespace()
    frappe.get_doc = Mock()
    frappe.get_all = Mock()
    frappe.get_list = Mock()
    frappe.get_roles = Mock(return_value=["System Manager"])
    utils = types.ModuleType("frappe.utils")
    utils.getdate = lambda value: date.fromisoformat(value) if isinstance(value, str) else value
    utils.now_datetime = lambda: datetime(2026, 1, 10, 12, 0)
    with patch.dict(sys.modules, {"frappe": frappe, "frappe.utils": utils}):
        rates = load_module("delivery_rates_under_test", "intelligent_ordering/utils/delivery_rates.py")
        notifications = load_module("notifications_under_test", "intelligent_ordering/utils/fulfillment_notifications.py")
        with patch.dict(sys.modules, {
            "intelligent_ordering.utils.delivery_rates": rates,
            "intelligent_ordering.utils.fulfillment_notifications": notifications,
        }):
            service = load_module("deliveries_under_test", "intelligent_ordering/api/deliveries.py")
    return service, rates, notifications, frappe


class TestDeliveryWorkflow(unittest.TestCase):
    def setUp(self):
        self.service, self.rates, self.notifications, self.frappe = load_services()
        self.delivery = Mock(
            order="SO-1", status="In Transit", assigned_delivery_person="driver@example.test",
            scheduled_delivery_date=date(2026, 1, 11), activities=[],
            completion_date=None, completed_by=None, dispatch_date=None,
        )
        self.delivery.name = "DEL-1"
        self.delivery.get.side_effect = lambda field: getattr(self.delivery, field, None)
        self.order = Mock(
            status="Ready for Delivery", payment_status="Paid", total=350, currency="KES",
            customer="CUSTOMER-1", customer_name_snapshot="Test Customer",
            customer_phone_snapshot="+254712345678",
            delivery_address_snapshot="1 Test Road, Nairobi", delivery_area="Central",
            delivery_fee=100,
        )
        self.order.name = "SO-1"
        self.order.get.side_effect = lambda field: getattr(self.order, field, None)
        self.frappe.get_doc.side_effect = lambda doctype, *args, **kwargs: (
            self.order if doctype == "Sales Order" else self.delivery
        )
        def get_value(doctype, *args, **kwargs):
            if doctype == "Delivery":
                if args and isinstance(args[0], dict):
                    return self.frappe.db.get_value.return_value
                return "SO-1"
            if doctype == "Sales Order":
                return types.SimpleNamespace(payment_status=self.order.payment_status)
            return "SO-1"

        self.frappe.db.get_value.return_value = None
        self.frappe.db.get_value.side_effect = get_value
        self.save_patch = patch.object(self.service, "_save")
        self.save = self.save_patch.start()
        self.addCleanup(self.save_patch.stop)

    def as_driver(self):
        self.frappe.session.user = "driver@example.test"
        self.frappe.get_roles.return_value = ["Delivery Staff"]

    def test_delivery_creation_snapshots_order_and_does_not_change_stock_payment_or_order(self):
        self.frappe.db.get_value.return_value = None
        self.service.create_delivery("SO-1")
        payload = self.frappe.get_doc.call_args.args[0]
        self.assertEqual(payload["delivery_fee"], 100)
        self.assertEqual(payload["delivery_area"], "Central")
        self.assertEqual(payload["delivery_address"], "1 Test Road, Nairobi")
        self.assertEqual(payload["status"], "Awaiting Assignment")
        self.assertEqual(payload["customer_phone"], "+254712345678")
        self.order.save.assert_not_called()
        self.order.db_set.assert_not_called()
        self.assertFalse(any(call.args[0] == "Payment Transaction" for call in self.frappe.get_doc.call_args_list))

    def test_duplicate_delivery_creation_returns_existing_document(self):
        self.frappe.db.get_value.return_value = "DEL-1"
        result = self.service.create_delivery("SO-1")
        self.assertEqual(result["name"], "DEL-1")
        self.save.assert_not_called()

    def test_creation_requires_ready_order(self):
        self.frappe.db.get_value.return_value = None
        self.order.status = "Pending"
        with self.assertRaisesRegex(DeliveryError, "Ready for Delivery"):
            self.service.create_delivery("SO-1")
        self.save.assert_not_called()

    def test_legacy_order_routing_does_not_add_fee_or_change_total(self):
        self.frappe.db.get_value.return_value = None
        self.order.delivery_area = None
        self.order.delivery_fee = 0
        with patch.object(self.service, "get_area_quote", return_value={"delivery_area": "Central"}) as quote:
            self.service.create_delivery("SO-1", "Central")
        quote.assert_called_once_with("Central", "KES")
        self.assertEqual(self.frappe.get_doc.call_args.args[0]["delivery_fee"], 0)
        self.order.save.assert_not_called()
        self.assertEqual(self.order.total, 350)

    def test_assignment_scheduling_and_reassignment_require_reason(self):
        self.delivery.status = "Awaiting Assignment"
        self.delivery.assigned_delivery_person = None
        self.frappe.get_roles.return_value = ["Delivery Staff"]
        self.service.assign_delivery("DEL-1", "driver@example.test", "2026-01-11")
        self.assertEqual(self.delivery.status, "Assigned")
        self.assertEqual(self.delivery.assigned_delivery_person, "driver@example.test")
        self.assertEqual(self.delivery.scheduled_delivery_date, date(2026, 1, 11))
        with self.assertRaisesRegex(DeliveryError, "reason"):
            self.service.assign_delivery("DEL-1", "second@example.test", "2026-01-12")
        self.service.assign_delivery("DEL-1", "second@example.test", "2026-01-12", "Shift change")
        self.assertEqual(self.delivery.assigned_delivery_person, "second@example.test")
        self.assertEqual(self.save.call_args.args[3], "driver@example.test")

    def test_repeated_assignment_is_idempotent(self):
        self.delivery.status = "Assigned"
        self.frappe.get_roles.return_value = ["Delivery Staff"]
        self.service.assign_delivery("DEL-1", "driver@example.test", "2026-01-11")
        self.save.assert_not_called()

    def test_invalid_person_and_schedule_are_rejected(self):
        self.frappe.get_roles.return_value = ["Customer"]
        with self.assertRaisesRegex(DeliveryError, "enabled user"):
            self.service.assign_delivery("DEL-1", "customer@example.test", "2026-01-11")
        self.frappe.get_roles.return_value = ["Delivery Staff"]
        self.frappe.db.get_value.return_value = 0
        with self.assertRaises(DeliveryError):
            self.service.assign_delivery("DEL-1", "disabled@example.test", "2026-01-11")
        for value in ("2026-01-09", "2026-02-31", "not a date", None):
            with self.subTest(value=value), self.assertRaises(DeliveryError):
                self.service._schedule(value)

    def test_reassignment_after_dispatch_is_rejected(self):
        self.frappe.get_roles.return_value = ["Delivery Staff"]
        for status in ("Picked Up", "Dispatched", "In Transit", "Delivered", "Cancelled"):
            self.delivery.status = status
            with self.assertRaisesRegex(DeliveryError, "cannot be assigned"):
                self.service.assign_delivery("DEL-1", "second@example.test", "2026-01-11", "Shift change")

    def test_replacement_rider_must_accept_even_when_original_rider_accepted(self):
        self.frappe.get_roles.return_value = ["Delivery Staff"]
        for status in ("Assigned", "Accepted", "Preparing", "Ready for Dispatch"):
            with self.subTest(status=status):
                self.delivery.status = status
                self.delivery.assigned_delivery_person = "driver@example.test"
                self.service.assign_delivery("DEL-1", "second@example.test", "2026-01-11", "Shift change")
                self.assertEqual(self.delivery.status, "Assigned")
                self.assertEqual(self.delivery.assigned_delivery_person, "second@example.test")
                self.assertEqual(self.save.call_args.args[2], status)

    def test_delayed_filter_keeps_rider_scope_and_excludes_terminal_work(self):
        self.as_driver()
        self.frappe.get_list.return_value = []
        self.service.list_deliveries(delayed="1")
        filters = self.frappe.get_list.call_args.kwargs["filters"]
        self.assertEqual(filters["assigned_delivery_person"], "driver@example.test")
        self.assertEqual(filters["scheduled_delivery_date"], ["<", date(2026, 1, 10)])
        self.assertEqual(filters["status"], ["not in", ["Delivered", "Failed", "Cancelled"]])
        for value in ("yes", "2"):
            with self.subTest(value=value), self.assertRaises(DeliveryError):
                self.service.list_deliveries(delayed=value)
        with self.assertRaises(DeliveryError):
            self.service.list_deliveries(status="Delivered", delayed="1")

    def test_paid_explicit_confirmation_completes_only_assigned_order(self):
        self.as_driver()
        calls = []
        self.save.side_effect = lambda *args: calls.append("delivery")
        self.order.save.side_effect = lambda **kwargs: calls.append("order")
        self.service.update_delivery("DEL-1", "Delivered", "Handed to customer", "1")
        self.assertEqual(self.delivery.status, "Delivered")
        self.assertEqual(self.delivery.completed_by, "driver@example.test")
        self.assertEqual(self.delivery.completion_date, datetime(2026, 1, 10, 12, 0))
        self.assertEqual(self.order.status, "Completed")
        self.assertEqual(calls, ["delivery", "order"])
        self.order.save.assert_called_once_with(ignore_permissions=True)
        self.order.db_set.assert_not_called()
        self.assertFalse(self.frappe.flags.processing_delivery)

    def test_unpaid_delivery_and_missing_confirmation_cannot_complete_order(self):
        self.as_driver()
        with self.assertRaisesRegex(DeliveryError, "confirmation"):
            self.service.update_delivery("DEL-1", "Delivered", confirmation=0)
        for status in ("Unpaid", "Pending", "Failed", "Refunded"):
            self.order.payment_status = status
            with self.subTest(status=status), self.assertRaisesRegex(DeliveryError, "payment"):
                self.service.update_delivery("DEL-1", "Delivered", confirmation=1)
        self.order.save.assert_not_called()
        self.save.assert_not_called()

    def test_manager_cannot_impersonate_assigned_person_at_completion(self):
        with self.assertRaisesRegex(DeliveryError, "assigned delivery person"):
            self.service.update_delivery("DEL-1", "Delivered", confirmation=1)
        self.order.save.assert_not_called()

    def test_duplicate_delivered_update_does_not_repeat_order_update(self):
        self.as_driver()
        self.delivery.status = "Delivered"
        self.order.status = "Completed"
        self.service.update_delivery("DEL-1", "Delivered", confirmation=1)
        self.save.assert_not_called()
        self.order.save.assert_not_called()

    def test_cancelled_order_cannot_be_dispatched_or_completed(self):
        self.as_driver()
        self.order.status = "Cancelled"
        with self.assertRaisesRegex(DeliveryError, "associated order"):
            self.service.update_delivery("DEL-1", "Delivered", confirmation=1)
        self.save.assert_not_called()

    def test_unpaid_physical_dispatch_is_blocked(self):
        self.as_driver()
        self.delivery.status = "Ready for Dispatch"
        self.order.payment_status = "Unpaid"
        with self.assertRaisesRegex(DeliveryError, "payment"):
            self.service.update_delivery("DEL-1", "Picked Up")
        self.save.assert_not_called()

    def test_delivery_completion_requires_a_proof_attachment(self):
        self.as_driver()
        with patch.object(self.service, "_proof_files", return_value=[]):
            with self.assertRaisesRegex(DeliveryError, "proof-of-delivery"):
                self.service.update_delivery("DEL-1", "Delivered", confirmation=1)
        self.save.assert_not_called()
        self.order.save.assert_not_called()

    def test_rider_can_reject_only_an_unaccepted_assigned_delivery_with_reason(self):
        self.as_driver()
        self.delivery.status = "Assigned"
        with patch.object(self.service, "_serialize", return_value={"name": "DEL-1"}):
            with self.assertRaisesRegex(DeliveryError, "required"):
                self.service.reject_delivery("DEL-1", " ")
            result = self.service.reject_delivery("DEL-1", "Rider unavailable")
        self.assertEqual(result, {"name": "DEL-1"})
        self.assertEqual(self.delivery.status, "Awaiting Assignment")
        self.assertIsNone(self.delivery.assigned_delivery_person)
        self.assertIsNone(self.delivery.scheduled_delivery_date)
        self.assertEqual(self.delivery.delivery_notes, "Rider unavailable")
        self.save.assert_called_once_with(
            self.delivery, self.order, "Assigned", "driver@example.test",
            "Assignment rejected: Rider unavailable",
        )

    def test_proof_upload_is_private_and_rejects_non_images(self):
        self.as_driver()
        self.delivery.status = "In Transit"
        file_manager = types.ModuleType("frappe.utils.file_manager")
        file_manager.save_file = Mock(return_value=types.SimpleNamespace(
            file_name="proof.png", file_url="/private/files/proof.png", creation="now",
        ))
        image = b"\x89PNG\r\n\x1a\n" + b"image-data"
        with patch.dict(sys.modules, {"frappe.utils.file_manager": file_manager}):
            result = self.service.upload_delivery_proof("DEL-1", base64.b64encode(image).decode())
            with self.assertRaisesRegex(DeliveryError, "PNG, JPEG, or WebP"):
                self.service.upload_delivery_proof("DEL-1", base64.b64encode(b"not an image").decode())
        self.assertEqual(result["file_url"], "/private/files/proof.png")
        self.assertEqual(file_manager.save_file.call_args.args[1], image)
        self.assertEqual(file_manager.save_file.call_args.kwargs["is_private"], 1)

    def test_dispatch_timestamp_recorded_once_and_notes_only_do_not_move_stock(self):
        self.as_driver()
        self.delivery.status = "Ready for Dispatch"
        self.service.update_delivery("DEL-1", "Dispatched", "Collected")
        dispatched = self.delivery.dispatch_date
        self.service.update_delivery("DEL-1", "Dispatched", "Leaving depot")
        self.assertEqual(self.delivery.dispatch_date, dispatched)
        self.assertEqual(self.delivery.delivery_notes, "Leaving depot")
        self.order.save.assert_not_called()

    def test_failure_and_cancellation_require_notes_and_do_not_cancel_order(self):
        self.as_driver()
        with self.assertRaisesRegex(DeliveryError, "reason"):
            self.service.update_delivery("DEL-1", "Failed")
        self.service.update_delivery("DEL-1", "Failed", "Customer unavailable")
        self.frappe.session.user = "Administrator"
        self.service.update_delivery("DEL-1", "Cancelled", "Return arranged")
        self.assertEqual(self.delivery.status, "Cancelled")
        self.assertEqual(self.order.status, "Ready for Delivery")
        self.order.save.assert_not_called()

    def test_unassigned_personnel_and_customers_cannot_read_or_mutate_delivery(self):
        self.as_driver()
        self.delivery.assigned_delivery_person = "second@example.test"
        with self.assertRaisesRegex(DeliveryError, "your assigned"):
            self.service.get_delivery("DEL-1")
        with self.assertRaises(DeliveryError):
            self.service.update_delivery("DEL-1", "Delivered", confirmation=1)
        with self.assertRaises(DeliveryError):
            self.service.assign_delivery("DEL-1", "driver@example.test", "2026-01-11")
        self.frappe.get_roles.return_value = ["Customer"]
        for operation, args in (
            (self.service.get_delivery, ("DEL-1",)),
            (self.service.list_deliveries, ()),
            (self.service.create_delivery, ("SO-1",)),
            (self.service.save_delivery_area, ("Central", 1)),
        ):
            with self.assertRaises(DeliveryError):
                operation(*args)

    def test_personnel_listing_is_owner_scoped_and_paginated(self):
        self.as_driver()
        self.frappe.get_list.return_value = [{"name": "DEL-1"}, {"name": "DEL-2"}]
        result = self.service.list_deliveries(status="Assigned", area="Central", page_size=1)
        self.assertEqual(result["deliveries"], [{"name": "DEL-1"}])
        self.assertTrue(result["has_more"])
        filters = self.frappe.get_list.call_args.kwargs["filters"]
        self.assertEqual(filters, {
            "assigned_delivery_person": "driver@example.test",
            "status": "Assigned", "delivery_area": "Central",
        })

    def test_order_is_locked_before_delivery_and_assignment_is_checked_after_lock(self):
        self.service._delivery_locked("DEL-1")
        calls = self.frappe.get_doc.call_args_list
        self.assertEqual([call.args[0] for call in calls], ["Sales Order", "Delivery"])
        self.assertTrue(all(call.kwargs["for_update"] for call in calls))

    def test_activity_and_notification_recording_is_transactional_and_protected(self):
        self.save_patch.stop()
        self.delivery.activities = [Mock()]
        with patch.object(self.service, "prepare_notification") as notify:
            self.service._save(self.delivery, self.order, "Dispatched", "driver@example.test", "Delivered")
        self.delivery.append.assert_called_once()
        activity = self.delivery.append.call_args.args[1]
        self.assertEqual(activity["responsible_user"], "Administrator")
        self.assertEqual(activity["from_status"], "Dispatched")
        self.assertEqual(activity["notes"], "Delivered")
        self.delivery.save.assert_called_once_with(ignore_permissions=True)
        notify.assert_not_called()
        self.assertFalse(self.frappe.flags.processing_delivery)


class TestDeliveryRatesAndNotifications(unittest.TestCase):
    def setUp(self):
        self.service, self.rates, self.notifications, self.frappe = load_services()

    def test_quotes_use_only_database_fees_and_currency(self):
        rate = Mock(enabled=1, currency="KES", delivery_fee=125)
        rate.name = "Central"
        self.frappe.get_doc.return_value = rate
        quote = self.rates.get_area_quote("Central", "KES", for_update=True)
        self.assertEqual(quote["delivery_fee"], 125)
        self.frappe.get_doc.assert_called_once_with("Delivery Area", "Central", for_update=True)
        rate.enabled = 0
        with self.assertRaises(DeliveryError):
            self.rates.get_area_quote("Central", "KES")
        rate.enabled = 1
        with self.assertRaises(DeliveryError):
            self.rates.get_area_quote("Central", "USD")

    def test_notification_events_are_prepared_not_falsely_sent_and_deduplicated(self):
        self.frappe.db.exists.return_value = False
        self.frappe.conf = {"fulfillment_notifications": {"provider": "future-sms"}}
        order = Mock(customer_phone_snapshot="+254712345678", status="Confirmed")
        order.name = "SO-1"
        self.notifications.prepare_notification("Order Confirmed", order)
        payload = self.frappe.get_doc.call_args.args[0]
        self.assertEqual(payload["status"], "Prepared")
        self.assertEqual(payload["provider"], "future-sms")
        self.assertEqual(payload["event_key"], "SO-1:Order Confirmed")
        self.assertFalse(self.frappe.flags.preparing_fulfillment_notification)
        self.frappe.db.exists.return_value = True
        self.notifications.prepare_notification("Order Confirmed", order)
        self.frappe.get_doc.assert_called_once()

    def test_order_confirmation_notification_only_on_real_confirmation_transition(self):
        order = Mock(status="Confirmed")
        order.name = "SO-1"
        with patch.object(self.notifications, "prepare_notification") as prepare:
            order.get_doc_before_save.return_value = None
            self.notifications.handle_order_status_change(order)
            prepare.assert_not_called()
            order.get_doc_before_save.return_value = Mock(status="Pending")
            self.notifications.handle_order_status_change(order)
            prepare.assert_called_once_with("Order Confirmed", order)
            prepare.reset_mock()
            order.get_doc_before_save.return_value = Mock(status="Confirmed")
            self.notifications.handle_order_status_change(order)
            prepare.assert_not_called()
