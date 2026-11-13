import copy
import unittest
from unittest.mock import Mock

import requests

from intelligent_ordering.utils.mpesa import (
    DarajaClient, DarajaError, DarajaRejected,
    normalize_phone, parse_callback, payment_amount,
)


CONFIG = {
    "environment": "Sandbox", "consumer_key": "test-key",
    "consumer_secret": "test-secret", "shortcode": "174379",
    "passkey": "test-passkey",
    "callback_url": "https://shop.example.test/api/method/intelligent_ordering.api.payments.callback",
}


def success_callback():
    return {"Body": {"stkCallback": {
        "MerchantRequestID": "merchant-1", "CheckoutRequestID": "checkout-1",
        "ResultCode": 0, "ResultDesc": "Success",
        "CallbackMetadata": {"Item": [
            {"Name": "Amount", "Value": 250},
            {"Name": "MpesaReceiptNumber", "Value": "TEST1234567"},
            {"Name": "TransactionDate", "Value": 20261113083000},
            {"Name": "PhoneNumber", "Value": 254712345678},
        ]},
    }}}


class TestMpesa(unittest.TestCase):
    def test_mobile_validation(self):
        for value in ("0712345678", "+254712345678", "254712345678"):
            self.assertEqual(normalize_phone(value), "254712345678")
        for value in ("123", "0201234567", None, "+255712345678", True, "25471\u0667\u0663\u0664\u0665\u0666\u0667\u0668"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_phone(value)

    def test_amount_validation_never_rounds_orders(self):
        self.assertEqual(payment_amount("250.00"), 250)
        for value in ("0", "-1", "1.25", "NaN", "Infinity", None, True, 250001):
            with self.subTest(value=value), self.assertRaises(ValueError):
                payment_amount(value)

    def test_oauth_and_stk_push_use_server_parameters(self):
        session = Mock()
        token = Mock(status_code=200)
        token.json.return_value = {"access_token": "access-token"}
        push = Mock(status_code=200)
        push.json.return_value = {"ResponseCode": "0", "CheckoutRequestID": "checkout-1"}
        session.request.side_effect = [token, push]
        client = DarajaClient(CONFIG, session)
        result = client.initiate("SO-2026-00001", "0712345678", 250, "callback-token")
        self.assertEqual(result["ResponseCode"], "0")
        oauth = session.request.call_args_list[0]
        self.assertEqual(oauth.kwargs["auth"], ("test-key", "test-secret"))
        request = session.request.call_args_list[1]
        self.assertIn("sandbox.safaricom.co.ke", request.args[1])
        self.assertEqual(request.kwargs["json"]["Amount"], 250)
        self.assertEqual(request.kwargs["json"]["PhoneNumber"], "254712345678")
        self.assertTrue(request.kwargs["json"]["CallBackURL"].endswith("?token=callback-token"))
        self.assertNotIn("ConsumerSecret", request.kwargs["json"])
        self.assertFalse(request.kwargs["allow_redirects"])

    def test_production_and_status_query(self):
        session = Mock()
        response = Mock(status_code=200)
        response.json.side_effect = [
            {"access_token": "token"},
            {"CheckoutRequestID": "checkout-1", "ResultCode": "0"},
        ]
        session.request.return_value = response
        client = DarajaClient({**CONFIG, "environment": "Production"}, session)
        result = client.query("checkout-1")
        self.assertEqual(result["ResultCode"], "0")
        self.assertIn("https://api.safaricom.co.ke", session.request.call_args.args[1])
        self.assertEqual(session.request.call_args.kwargs["json"]["CheckoutRequestID"], "checkout-1")

    def test_oauth_missing_token_and_transport_failures_are_explicit(self):
        session = Mock()
        response = Mock(status_code=200)
        response.json.return_value = {"error": "unauthorized"}
        session.request.return_value = response
        with self.assertRaises(DarajaError):
            DarajaClient(CONFIG, session).access_token()
        session.request.side_effect = requests.Timeout("sensitive provider details")
        with self.assertRaisesRegex(DarajaError, "Daraja request failed"):
            DarajaClient(CONFIG, session).access_token()

    def test_callback_success_and_failure(self):
        result = parse_callback(success_callback())
        self.assertEqual(result["amount"], 250)
        self.assertEqual(result["receipt"], "TEST1234567")
        failed = success_callback()
        failed["Body"]["stkCallback"] = {
            "MerchantRequestID": "merchant-1", "CheckoutRequestID": "checkout-1",
            "ResultCode": 1032, "ResultDesc": "Cancelled",
        }
        self.assertEqual(parse_callback(failed)["code"], 1032)

    def test_explicit_provider_rejection_is_distinct_from_unknown_outcome(self):
        session = Mock()
        response = Mock(status_code=400)
        response.json.return_value = {"errorCode": "400.002.02"}
        session.request.return_value = response
        with self.assertRaises(DarajaRejected):
            DarajaClient(CONFIG, session).access_token()

    def test_invalid_callback_and_duplicate_metadata_are_rejected(self):
        malformed = copy.deepcopy(success_callback())
        malformed["Body"]["stkCallback"]["CallbackMetadata"]["Item"].append(
            {"Name": "Amount", "Value": 1}
        )
        for payload in ({}, [], None, malformed):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                parse_callback(payload)

    def test_invalid_configuration_fails_closed(self):
        for config in (
            {**CONFIG, "environment": "Test"},
            {**CONFIG, "consumer_secret": ""},
            {**CONFIG, "callback_url": "http://example.test/callback"},
            {**CONFIG, "callback_url": "https://example.test/callback?token=static"},
        ):
            with self.assertRaises(ValueError):
                DarajaClient(config)
