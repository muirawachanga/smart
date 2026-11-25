import importlib.util
import sys
import types
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import Mock, patch


class ContactError(Exception):
    pass


class Profile(dict):
    __getattr__ = dict.get
    __setattr__ = dict.__setitem__
    set = dict.__setitem__


class Cache:
    def __init__(self):
        self.values = {}
        self.lock = Mock(side_effect=lambda *args, **kwargs: nullcontext())

    def make_key(self, key):
        return "site:" + key

    def get_value(self, key):
        return self.values.get(key)

    def set_value(self, key, value, **kwargs):
        self.values[key] = dict(value)

    def delete_value(self, key):
        self.values.pop(key, None)


class TestContactVerification(unittest.TestCase):
    def setUp(self):
        self.frappe = types.ModuleType("frappe")
        self.frappe.cache = Cache()
        self.frappe.db = Mock()
        self.frappe.db.get_value.side_effect = lambda doctype, *args: (
            "customer@example.test" if doctype == "User" else "PROFILE"
        )
        self.frappe.ValidationError = self.frappe.OutgoingEmailError = ContactError
        self.frappe.throw = Mock(side_effect=lambda message, error: (_ for _ in ()).throw(error(message)))
        self.frappe.sendmail = Mock()
        self.frappe.log_error = Mock()
        utils = types.ModuleType("frappe.utils")
        utils.escape_html = lambda value: value
        utils.get_url = lambda path: "https://shop.example.test" + path
        utils.now_datetime = lambda: "2026-11-25 01:00:00"
        sms = types.ModuleType("intelligent_ordering.utils.fulfillment_notifications")
        sms._configuration = Mock(return_value={"environment": "sandbox"})
        sms._submit = Mock(return_value=("Submitted", "provider-id", ""))
        sms._phone_number = lambda value: "+" + value.lstrip("+") if value else self.fail_phone()
        self.sms = sms
        path = Path(__file__).parents[1] / "intelligent_ordering/utils/contact_verification.py"
        spec = importlib.util.spec_from_file_location("contacts_under_test", path)
        self.contacts = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"frappe": self.frappe, "frappe.utils": utils, sms.__name__: sms}):
            spec.loader.exec_module(self.contacts)
        self.now = 1000
        self.clock = patch.object(self.contacts.time, "time", side_effect=lambda: self.now)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.profile = Profile(
            name="PROFILE", user="customer@example.test", phone="+254712345678",
            contact_verification_required=1,
        )
        self.frappe.get_doc = Mock(return_value=self.profile)
        self.frappe.db.set_value.side_effect = self.persist

    @staticmethod
    def fail_phone():
        raise ValueError("Invalid phone")

    def persist(self, doctype, name, values):
        self.profile.update(values)

    def request_phone(self):
        with patch.object(self.contacts.secrets, "randbelow", return_value=12345):
            return self.contacts.request_verification(self.profile, "phone")

    def test_phone_challenge_is_hashed_and_single_use_and_updates_only_own_profile(self):
        self.request_phone()
        challenge = next(iter(self.frappe.cache.values.values()))
        self.assertNotIn("012345", repr(challenge))
        self.assertIn("012345", self.sms._submit.call_args.args[2])
        self.assertFalse(self.contacts.status(self.profile)["phone_verified"])
        self.contacts.confirm_verification(self.profile, "phone", "012345")
        self.assertTrue(self.contacts.status(self.profile)["phone_verified"])
        self.frappe.db.set_value.assert_called_once_with("Customer Profile", "PROFILE", {
            "verified_phone": "+254712345678", "phone_verified_at": "2026-11-25 01:00:00",
        })
        with self.assertRaises(ContactError):
            self.contacts.confirm_verification(self.profile, "phone", "012345")

    def test_email_link_uses_fragment_and_does_not_verify_until_confirmed(self):
        with patch.object(self.contacts.secrets, "token_urlsafe", return_value="email-token"):
            result = self.contacts.request_verification(self.profile, "email")
        mail = self.frappe.sendmail.call_args.kwargs
        self.assertEqual(mail["recipients"], ["customer@example.test"])
        self.assertIn("/account/profile#verify-email=email-token", mail["message"])
        self.assertNotIn("email-token", repr(result))
        self.assertFalse(self.contacts.status(self.profile)["email_verified"])
        self.contacts.confirm_verification(self.profile, "email", "email-token")
        self.assertTrue(self.contacts.status(self.profile)["email_verified"])

    def test_five_wrong_attempts_exhaust_challenge_even_if_correct_code_follows(self):
        self.request_phone()
        for _ in range(5):
            with self.assertRaises(ContactError):
                self.contacts.confirm_verification(self.profile, "phone", "wrong")
        with self.assertRaises(ContactError):
            self.contacts.confirm_verification(self.profile, "phone", "012345")
        self.frappe.db.set_value.assert_not_called()

    def test_expiry_resend_throttle_and_replacement(self):
        self.request_phone()
        with self.assertRaisesRegex(ContactError, "60 seconds"):
            self.request_phone()
        self.now += 60
        with patch.object(self.contacts.secrets, "randbelow", return_value=987654):
            self.contacts.request_verification(self.profile, "phone")
        with self.assertRaises(ContactError):
            self.contacts.confirm_verification(self.profile, "phone", "012345")
        self.now += 600
        with self.assertRaises(ContactError):
            self.contacts.confirm_verification(self.profile, "phone", "987654")
        self.frappe.db.set_value.assert_not_called()

    def test_challenges_are_bound_to_user_channel_and_current_contact(self):
        self.request_phone()
        other = Profile(self.profile, user="other@example.test", name="OTHER")
        for profile, channel in ((other, "phone"), (self.profile, "email")):
            with self.assertRaises(ContactError):
                self.contacts.confirm_verification(profile, channel, "012345")
        self.profile.phone = "+254700000000"
        with self.assertRaises(ContactError):
            self.contacts.confirm_verification(self.profile, "phone", "012345")
        self.frappe.db.set_value.assert_not_called()

    def test_provider_failures_are_explicit_and_never_verify_contact(self):
        self.sms._submit.return_value = ("Unknown", "", "provider detail")
        with self.assertRaisesRegex(ContactError, "Delivery could not be confirmed"):
            self.request_phone()
        self.frappe.log_error.assert_called_once()
        self.frappe.db.set_value.assert_not_called()
        self.now += 60
        self.sms._configuration.return_value = None
        with self.assertRaisesRegex(ContactError, "unavailable"):
            self.request_phone()
        self.frappe.sendmail.side_effect = ContactError("SMTP detail")
        with self.assertRaisesRegex(ContactError, "Delivery could not be confirmed"):
            self.contacts.request_verification(self.profile, "email")
        self.assertNotIn("SMTP detail", repr(self.frappe.log_error.call_args))

    def test_checkout_requires_both_verified_contacts_and_matching_phone_for_new_accounts(self):
        for email, phone in ((False, False), (True, False), (False, True)):
            self.profile.update(
                verified_email="customer@example.test" if email else "",
                email_verified_at="today" if email else None,
                verified_phone=self.profile.phone if phone else "",
                phone_verified_at="today" if phone else None,
            )
            with self.assertRaisesRegex(ContactError, "My profile"):
                self.contacts.require_verified_contacts(self.profile.user, self.profile.phone)
        self.profile.update(verified_email="customer@example.test", email_verified_at="today",
                            verified_phone=self.profile.phone, phone_verified_at="today")
        self.contacts.require_verified_contacts(self.profile.user, self.profile.phone)
        with self.assertRaises(ContactError):
            self.contacts.require_verified_contacts(self.profile.user, "+254700000000")
        self.frappe.db.get_value.side_effect = lambda doctype, *args: (
            "changed@example.test" if doctype == "User" else "PROFILE"
        )
        with self.assertRaises(ContactError):
            self.contacts.require_verified_contacts(self.profile.user, self.profile.phone)

    def test_legacy_profiles_remain_able_to_order_without_being_falsely_verified(self):
        self.profile.contact_verification_required = 0
        self.contacts.require_verified_contacts(self.profile.user, self.profile.phone)
        self.assertFalse(self.contacts.status(self.profile)["phone_verified"])

    def test_profile_edits_cannot_fabricate_verification_or_disable_requirement(self):
        original = Profile(self.profile)
        self.profile.get_doc_before_save = lambda: original
        self.profile.update(verified_email="forged", verified_phone=self.profile.phone,
                            phone_verified_at="forged", contact_verification_required=0)
        self.contacts.invalidate_changed_contacts(self.profile)
        self.assertIsNone(self.profile.verified_email)
        self.assertIsNone(self.profile.verified_phone)
        self.assertEqual(self.profile.contact_verification_required, 1)

    def test_phone_edit_clears_proof_and_pending_challenge(self):
        self.request_phone()
        original = Profile(self.profile, verified_phone=self.profile.phone, phone_verified_at="today")
        self.profile.get_doc_before_save = lambda: original
        self.profile.phone = "+254700000000"
        self.contacts.invalidate_changed_contacts(self.profile)
        self.assertFalse(self.profile.verified_phone)
        self.assertIsNone(self.profile.phone_verified_at)
        with self.assertRaises(ContactError):
            self.contacts.confirm_verification(self.profile, "phone", "012345")

    def test_equivalent_phone_format_keeps_proof(self):
        original = Profile(self.profile, verified_phone=self.profile.phone, phone_verified_at="today")
        self.profile.get_doc_before_save = lambda: original
        self.profile.phone = "254712345678"
        self.contacts.invalidate_changed_contacts(self.profile)
        self.assertTrue(self.contacts.status(self.profile)["phone_verified"])

    def test_email_change_clears_proof_and_pending_challenge(self):
        self.contacts.request_verification(self.profile, "email")
        user = types.SimpleNamespace(
            name=self.profile.user, email="changed@example.test",
            get_doc_before_save=lambda: types.SimpleNamespace(email=self.profile.user),
        )
        self.contacts.invalidate_changed_email(user)
        self.assertEqual(self.frappe.cache.values, {})
        self.assertFalse(self.profile.verified_email)

    def test_invalid_channels_and_token_types_cannot_write_proof(self):
        self.request_phone()
        for channel, token in (("bad", "012345"), ("phone", None), ("phone", ["012345"])):
            with self.assertRaises(ContactError):
                self.contacts.confirm_verification(self.profile, channel, token)
        self.frappe.db.set_value.assert_not_called()
