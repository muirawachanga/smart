import sys
import types
import unittest
from unittest.mock import Mock, patch

import requests

from test_delivery_workflow import DeliveryError, load_services


class TestFulfillmentSMS(unittest.TestCase):
    def setUp(self):
        _, _, self.sms, self.frappe = load_services()
        self.config = {
            "provider": "africas_talking", "enabled": True, "environment": "sandbox",
            "username": "sandbox", "api_key": "test-key",
        }
        self.frappe.conf = {"fulfillment_notifications": self.config}
        self.frappe.log_error = Mock()
        self.notification = types.SimpleNamespace(
            name="NOT-1", status="Prepared", provider="africas_talking",
            sms_environment="sandbox", recipient_phone="0712345678",
            event_type="Order Confirmed", order="SO-1", attempts=0,
            last_error="", provider_message_id="", save=Mock(), insert=Mock(),
        )
        self.frappe.get_all.return_value = ["NOT-1"]
        self.frappe.get_doc.return_value = self.notification

    def response(self, code=101, message_id="AT-1", number="+254712345678"):
        response = Mock(status_code=201)
        response.json.return_value = {"SMSMessageData": {"Recipients": [{
            "number": number, "statusCode": code, "messageId": message_id,
        }]}}
        return response

    def test_payment_events_require_a_real_transition_and_use_transaction_key(self):
        payment = Mock(status="Successful", order="SO-1")
        payment.name = "PAY-1"
        order = Mock()
        self.frappe.get_doc.return_value = order
        with patch.object(self.sms, "prepare_notification") as prepare:
            payment.get_doc_before_save.return_value = None
            self.sms.handle_payment_status_change(payment)
            payment.get_doc_before_save.return_value = Mock(status="Successful")
            self.sms.handle_payment_status_change(payment)
            prepare.assert_not_called()
            payment.get_doc_before_save.return_value = Mock(status="Pending")
            self.sms.handle_payment_status_change(payment)
            prepare.assert_called_once_with(
                "Payment Successful", order, event_key="payment:PAY-1:Successful",
            )

    def test_new_events_capture_provider_environment_without_backfilling(self):
        order = Mock(customer_phone_snapshot="+254712345678", status="Confirmed")
        order.name = "SO-1"
        self.frappe.db.exists.return_value = False
        self.sms.prepare_notification("Order Confirmed", order)
        event = self.frappe.get_doc.call_args.args[0]
        self.assertEqual(event["sms_environment"], "sandbox")
        self.assertEqual(event["status"], "Prepared")
        self.config["environment"] = ["invalid"]
        self.sms.prepare_notification("Order Confirmed", order)
        self.assertIsNone(self.frappe.get_doc.call_args.args[0]["sms_environment"])

    def test_phone_normalization_and_invalid_phone(self):
        for value in ("0712 345 678", "254712345678", "+254 (712) 345-678"):
            self.assertEqual(self.sms._phone_number(value), "+254712345678")
        self.assertEqual(self.sms._phone_number("+12025550123"), "+12025550123")
        for value in (None, "1234", "712345678", "+0123456789"):
            with self.assertRaises(ValueError):
                self.sms._phone_number(value)

    def test_submission_is_claimed_before_http_and_never_resent(self):
        def post(url, **kwargs):
            self.assertEqual(self.notification.status, "Sending")
            self.assertEqual(self.frappe.db.commit.call_count, 1)
            self.assertEqual(url, self.sms.SMS_ENDPOINTS["sandbox"])
            self.assertEqual(kwargs["data"]["to"], "+254712345678")
            self.assertFalse(kwargs["allow_redirects"])
            return self.response()

        with patch.object(self.sms.requests, "post", side_effect=post) as post_mock:
            self.sms.send_pending_sms()
            self.sms.send_pending_sms()
        post_mock.assert_called_once()
        self.assertEqual(self.notification.status, "Submitted")
        self.assertEqual(self.notification.provider_message_id, "AT-1")
        self.assertEqual(self.notification.attempts, 1)
        self.assertFalse(self.frappe.flags.preparing_fulfillment_notification)

    def test_response_outcomes_and_environment(self):
        config = dict(self.config, environment="production", username="live-user", sender_id="SHOP")
        for code, expected in ((101, "Submitted"), (102, "Submitted"), (405, "Failed"), (401, "Unknown")):
            with self.subTest(code=code), patch.object(self.sms.requests, "post", return_value=self.response(code)) as post:
                status, _, _ = self.sms._submit(config, "+254712345678", "test")
                self.assertEqual(status, expected)
                self.assertEqual(post.call_args.args[0], self.sms.SMS_ENDPOINTS["production"])
                self.assertEqual(post.call_args.kwargs["data"]["from"], "SHOP")
        for response in (self.response(101, "None"), self.response(number="+254700000000"), Mock(status_code=500)):
            with patch.object(self.sms.requests, "post", return_value=response):
                self.assertEqual(self.sms._submit(config, "+254712345678", "test")[0], "Unknown")
        with patch.object(self.sms.requests, "post", side_effect=requests.Timeout()):
            self.assertEqual(self.sms._submit(config, "+254712345678", "test")[0], "Unknown")

    def test_unknown_and_invalid_phone_are_not_retried_automatically(self):
        with patch.object(self.sms.requests, "post", side_effect=requests.Timeout()) as post:
            self.sms.send_pending_sms()
            self.sms.send_pending_sms()
        post.assert_called_once()
        self.assertEqual(self.notification.status, "Unknown")
        self.notification.status = "Prepared"
        self.notification.recipient_phone = "bad number"
        with patch.object(self.sms.requests, "post") as post:
            self.sms.send_pending_sms()
            post.assert_not_called()
        self.assertEqual(self.notification.status, "Failed")
        self.assertIn("phone number", self.notification.last_error)

    def test_disabled_invalid_and_mismatched_environment_do_not_send(self):
        self.config["enabled"] = False
        self.sms.send_pending_sms()
        self.frappe.get_all.assert_not_called()
        self.config.update(enabled=True, username="not-sandbox")
        self.sms.send_pending_sms()
        self.frappe.log_error.assert_called_once()
        self.frappe.get_all.assert_not_called()
        self.config["username"] = "sandbox"
        self.notification.sms_environment = "production"
        with patch.object(self.sms.requests, "post") as post:
            self.sms.send_pending_sms()
            post.assert_not_called()
        self.assertEqual(self.notification.status, "Prepared")

    def test_retry_is_authorized_audited_and_only_for_failed_events(self):
        self.frappe.session.user = "staff@example.test"
        self.frappe.get_roles.return_value = ["Order Manager"]
        self.notification.status = "Failed"
        with self.assertRaises(DeliveryError):
            self.sms.retry_failed_sms("NOT-1")
        self.frappe.get_roles.return_value = ["Business Admin"]
        audit = types.ModuleType("intelligent_ordering.utils.audit")
        audit.record_admin_event = Mock()
        with patch.dict(sys.modules, {"intelligent_ordering.utils.audit": audit}):
            self.assertEqual(self.sms.retry_failed_sms("NOT-1")["status"], "Prepared")
            audit.record_admin_event.assert_called_once()
            for status in ("Sending", "Unknown", "Submitted", "Prepared"):
                self.notification.status = status
                with self.assertRaises(DeliveryError):
                    self.sms.retry_failed_sms("NOT-1")


if __name__ == "__main__":
    unittest.main()
