import base64
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import requests


class DarajaError(Exception):
    """A provider request could not be completed safely."""


class DarajaRejected(DarajaError):
    """The provider explicitly rejected a request without accepting an STK push."""


def normalize_phone(value):
    if not isinstance(value, str):
        raise ValueError("Enter a Kenyan M-Pesa mobile number.")
    phone = re.sub(r"[\s()-]", "", value.strip())
    if phone.startswith("+"):
        phone = phone[1:]
    if re.fullmatch(r"0[17][0-9]{8}", phone):
        phone = "254" + phone[1:]
    if not re.fullmatch(r"254[17][0-9]{8}", phone):
        raise ValueError("Enter a Kenyan M-Pesa mobile number.")
    return phone


def payment_amount(value):
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError("M-Pesa amount must be a positive whole KES amount.") from None
    if not amount.is_finite() or amount <= 0 or amount != amount.to_integral_value():
        raise ValueError("M-Pesa amount must be a positive whole KES amount.")
    if amount > 250000:
        raise ValueError("M-Pesa amount exceeds the supported per-transaction limit.")
    return int(amount)


def parse_callback(payload):
    try:
        callback = payload["Body"]["stkCallback"]
        merchant = callback["MerchantRequestID"]
        checkout = callback["CheckoutRequestID"]
        code = callback["ResultCode"]
        description = callback["ResultDesc"]
        if (
            not isinstance(merchant, str) or not 1 <= len(merchant) <= 140
            or not isinstance(checkout, str) or not 1 <= len(checkout) <= 140
            or isinstance(code, bool) or not isinstance(code, int)
            or not isinstance(description, str) or len(description) > 1000
        ):
            raise ValueError
        result = {
            "merchant_request_id": merchant,
            "checkout_request_id": checkout,
            "code": code,
            "description": description,
        }
        if code == 0:
            items = callback["CallbackMetadata"]["Item"]
            if not isinstance(items, list):
                raise ValueError
            metadata = {}
            for item in items:
                name = item["Name"]
                if not isinstance(name, str) or name in metadata:
                    raise ValueError
                metadata[name] = item.get("Value")
            receipt = metadata["MpesaReceiptNumber"]
            if not isinstance(receipt, str) or not re.fullmatch(r"[A-Z0-9]{10,20}", receipt):
                raise ValueError
            transaction_date = str(metadata["TransactionDate"])
            if not re.fullmatch(r"\d{14}", transaction_date):
                raise ValueError
            result.update(
                amount=payment_amount(metadata["Amount"]),
                phone=normalize_phone(str(metadata["PhoneNumber"])),
                receipt=receipt,
                transaction_date=datetime.strptime(transaction_date, "%Y%m%d%H%M%S"),
            )
        return result
    except (KeyError, TypeError, ValueError, OverflowError):
        raise ValueError("Invalid M-Pesa callback data.") from None


class DarajaClient:
    def __init__(self, config, session=None):
        self.config = config
        self.session = session or requests.Session()
        environment = config.get("environment", "Sandbox")
        if environment not in {"Sandbox", "Production"}:
            raise ValueError("M-Pesa environment must be Sandbox or Production.")
        self.base_url = (
            "https://sandbox.safaricom.co.ke" if environment == "Sandbox"
            else "https://api.safaricom.co.ke"
        )
        for field in ("consumer_key", "consumer_secret", "shortcode", "passkey", "callback_url"):
            if not isinstance(config.get(field), str) or not config[field].strip():
                raise ValueError(f"M-Pesa configuration is missing {field}.")
        callback_url = urlparse(config["callback_url"])
        if (
            callback_url.scheme != "https" or not callback_url.hostname
            or callback_url.query or callback_url.fragment or callback_url.username
        ):
            raise ValueError("Configure a public HTTPS M-Pesa callback URL without a query string.")
        if config.get("transaction_type", "CustomerPayBillOnline") not in {
            "CustomerPayBillOnline", "CustomerBuyGoodsOnline"
        }:
            raise ValueError("Invalid M-Pesa transaction type.")

    def _json(self, method, path, **kwargs):
        try:
            response = self.session.request(
                method, self.base_url + path, timeout=(5, 25),
                allow_redirects=False, **kwargs
            )
            if response.status_code in {400, 401, 403}:
                rejected = response.json()
                if (
                    isinstance(rejected, dict)
                    and isinstance(rejected.get("errorCode"), str)
                    and not rejected.get("CheckoutRequestID")
                ):
                    raise DarajaRejected("Daraja rejected the request. Check account configuration and parameters.")
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError):
            raise DarajaError("Daraja request failed; reconcile before retrying.") from None
        if not isinstance(payload, dict) or 300 <= response.status_code < 400:
            raise DarajaError("Daraja returned an invalid response.")
        return payload

    def access_token(self):
        payload = self._json(
            "GET", "/oauth/v1/generate?grant_type=client_credentials",
            auth=(self.config["consumer_key"], self.config["consumer_secret"]),
        )
        token = payload.get("access_token")
        if not isinstance(token, str) or not token:
            raise DarajaRejected("Daraja OAuth authentication failed.")
        return token

    def _credentials(self):
        timestamp = datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y%m%d%H%M%S")
        password = base64.b64encode(
            (self.config["shortcode"] + self.config["passkey"] + timestamp).encode()
        ).decode()
        return {
            "BusinessShortCode": self.config["shortcode"],
            "Password": password,
            "Timestamp": timestamp,
        }

    def initiate(self, order, phone, amount, callback_token):
        callback_url = self.config["callback_url"] + "?token=" + callback_token
        return self._json(
            "POST", "/mpesa/stkpush/v1/processrequest",
            headers={"Authorization": "Bearer " + self.access_token()},
            json={
                **self._credentials(),
                "TransactionType": self.config.get("transaction_type", "CustomerPayBillOnline"),
                "Amount": payment_amount(amount),
                "PartyA": normalize_phone(phone),
                "PartyB": self.config["shortcode"],
                "PhoneNumber": normalize_phone(phone),
                "CallBackURL": callback_url,
                "AccountReference": order[-12:],
                "TransactionDesc": "Order payment",
            },
        )

    def query(self, checkout_request_id):
        return self._json(
            "POST", "/mpesa/stkpushquery/v1/query",
            headers={"Authorization": "Bearer " + self.access_token()},
            json={**self._credentials(), "CheckoutRequestID": checkout_request_id},
        )
