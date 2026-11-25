import hashlib
import hmac
import secrets
import time

import frappe
from frappe.utils import escape_html, get_url, now_datetime

from intelligent_ordering.utils.fulfillment_notifications import _configuration, _phone_number, _submit


TTL = 600
RESEND_SECONDS = 60
MAX_ATTEMPTS = 5
INVALID_CHALLENGE = "This verification link or code is invalid or expired. Request a new one."
DELIVERY_UNAVAILABLE = "Contact verification is unavailable. Contact the store."
DELIVERY_UNCONFIRMED = "Delivery could not be confirmed. If it arrives, use it; otherwise wait before resending."
RESEND_WAIT = "Wait at least 60 seconds before requesting another verification."


def target(profile, channel):
    if channel == "email":
        return frappe.db.get_value("User", profile.user, "email")
    if channel == "phone":
        try:
            return _phone_number(profile.phone)
        except ValueError as error:
            frappe.throw(str(error), frappe.ValidationError)
    frappe.throw("Choose email or phone verification.", frappe.ValidationError)


def status(profile):
    email = target(profile, "email")
    try:
        phone = _phone_number(profile.phone)
    except ValueError:
        phone = None
    return {
        "email_verified": bool(email and profile.get("verified_email") == email
                               and profile.get("email_verified_at")),
        "phone_verified": bool(phone and profile.get("verified_phone") == phone
                               and profile.get("phone_verified_at")),
        "required_for_ordering": bool(profile.get("contact_verification_required")),
    }


def _key(user, channel):
    return f"smarto:contact-verification:{channel}:{hashlib.sha256(user.encode()).hexdigest()}"


def _digest(salt, value):
    return hmac.new(salt.encode(), value.encode(), hashlib.sha256).hexdigest()


def request_verification(profile, channel):
    destination = target(profile, channel)
    if not destination:
        frappe.throw("Save a valid contact before requesting verification.", frappe.ValidationError)
    if status(profile)[f"{channel}_verified"]:
        return {"message": "This contact is already verified."}
    key = _key(profile.user, channel)
    cache = frappe.cache
    with cache.lock(cache.make_key(key + ":lock"), timeout=60, blocking_timeout=5):
        previous = cache.get_value(key)
        now = time.time()
        if previous and now - previous["issued"] < RESEND_SECONDS:
            frappe.throw(RESEND_WAIT, frappe.ValidationError)
        config = None
        if channel == "phone":
            try:
                config = _configuration()
            except ValueError:
                frappe.log_error(title="Contact verification SMS configuration error",
                                 message="Review site-specific Africa's Talking settings.")
            if not config:
                frappe.throw(DELIVERY_UNAVAILABLE, frappe.ValidationError)
        token = secrets.token_urlsafe(32) if channel == "email" else f"{secrets.randbelow(1000000):06d}"
        salt = secrets.token_hex(32)
        cache.set_value(key, {
            "target": destination, "salt": salt, "digest": _digest(salt, token),
            "issued": now, "expires": now + TTL, "attempts": 0,
        }, expires_in_sec=TTL)
        if channel == "email":
            link = escape_html(get_url("/account/profile") + "#verify-email=" + token)
            try:
                frappe.sendmail(
                    recipients=[destination], subject="Verify your SmartO email",
                    message=f'<p>Sign in to SmartO, then open this link in the same browser '
                            f'and confirm your email:</p><p><a href="{link}">Verify email</a></p>'
                            f'<p>This single-use link expires in 10 minutes. '
                            f'If you did not request it, ignore it. Never share this link.</p>',
                    delayed=False,
                )
            except frappe.OutgoingEmailError:
                frappe.log_error(title="Contact verification email failed",
                                 message="Email verification delivery could not be confirmed.")
                frappe.throw(DELIVERY_UNCONFIRMED, frappe.ValidationError)
        else:
            outcome, _, _ = _submit(config, destination,
                                    f"Your SmartO phone verification code is {token}. "
                                    "It expires in 10 minutes. Do not share it.")
            if outcome != "Submitted":
                frappe.log_error(title="Contact verification SMS failed",
                                 message="SMS verification delivery could not be confirmed.")
                frappe.throw(DELIVERY_UNCONFIRMED, frappe.ValidationError)
    return {"message": "Verification sent. It expires in 10 minutes."}


def confirm_verification(profile, channel, token):
    destination = target(profile, channel)
    key = _key(profile.user, channel)
    cache = frappe.cache
    with cache.lock(cache.make_key(key + ":lock"), timeout=60, blocking_timeout=5):
        challenge = cache.get_value(key)
        now = time.time()
        if not challenge or now >= challenge["expires"] or challenge["attempts"] >= MAX_ATTEMPTS:
            frappe.throw(INVALID_CHALLENGE, frappe.ValidationError)
        challenge["attempts"] += 1
        cache.set_value(key, challenge, expires_in_sec=max(1, int(challenge["expires"] - now)))
        if (
            challenge["target"] != destination or not isinstance(token, str)
            or not 1 <= len(token) <= 128
            or not hmac.compare_digest(challenge["digest"], _digest(challenge["salt"], token))
        ):
            frappe.throw(INVALID_CHALLENGE, frappe.ValidationError)
        frappe.db.set_value("Customer Profile", profile.name, {
            f"verified_{channel}": destination, f"{channel}_verified_at": now_datetime(),
        })
        cache.delete_value(key)
    return {"message": "Contact verified."}


def require_verified_contacts(user, phone):
    frappe.db.sql("SELECT name FROM `tabUser` WHERE name = %s FOR UPDATE", user)
    name = frappe.db.get_value("Customer Profile", {"user": user}, "name")
    if not name:
        return
    profile = frappe.get_doc("Customer Profile", name, for_update=True)
    if not profile.get("contact_verification_required"):
        return
    checks = status(profile)
    try:
        same_phone = _phone_number(phone) == _phone_number(profile.phone)
    except ValueError:
        same_phone = False
    if not checks["email_verified"] or not checks["phone_verified"] or not same_phone:
        frappe.throw(
            "Verify your email and phone in My profile before ordering. Use your verified phone at checkout.",
            frappe.ValidationError,
        )


def invalidate_changed_contacts(doc, method=None):
    original = doc.get_doc_before_save()
    for field in ("verified_email", "email_verified_at", "verified_phone", "phone_verified_at",
                  "contact_verification_required"):
        doc.set(field, original.get(field) if original else (0 if field == "contact_verification_required" else None))
    phone_changed = not original or original.user != doc.user
    if original and original.phone != doc.phone:
        try:
            phone_changed = phone_changed or _phone_number(original.phone) != _phone_number(doc.phone)
        except ValueError:
            phone_changed = True
    if phone_changed:
        doc.verified_phone = ""
        doc.phone_verified_at = None
        if original:
            frappe.cache.delete_value(_key(original.user, "phone"))
    if not original or original.user != doc.user:
        doc.verified_email = ""
        doc.email_verified_at = None
        if original:
            frappe.cache.delete_value(_key(original.user, "email"))


def invalidate_changed_email(doc, method=None):
    original = doc.get_doc_before_save()
    if original and original.email != doc.email:
        name = frappe.db.get_value("Customer Profile", {"user": doc.name}, "name")
        if name:
            frappe.db.set_value("Customer Profile", name, {"verified_email": "", "email_verified_at": None})
            frappe.cache.delete_value(_key(doc.name, "email"))
