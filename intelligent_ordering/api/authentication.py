import frappe
from frappe.rate_limiter import rate_limit
from frappe.utils import validate_email_address

from intelligent_ordering.utils.authentication import login_destination, validate_new_password


@frappe.whitelist()
def destination(redirect_to=""):
    return {"destination": login_destination(redirect_to)}


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=5, seconds=3600)
def forgot_password(email):
    from frappe.core.doctype.user.user import reset_password

    if not isinstance(email, str) or len(email) > 140:
        frappe.throw("Enter a valid email address.", frappe.ValidationError)
    email = validate_email_address(email.strip().lower(), throw=True)
    try:
        reset_password(user=email)
    except frappe.DoesNotExistError:
        frappe.clear_messages()
    except frappe.OutgoingEmailError:
        frappe.log_error(title="SmartO password reset email failed", message=frappe.get_traceback())
        frappe.clear_messages()
    frappe.clear_messages()
    return {"message": "If this email is registered, password reset instructions will be sent to it."}


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=10, seconds=3600)
def reset_password(key, password, confirm_password):
    from frappe.core.doctype.user.user import update_password

    if not isinstance(key, str) or not 1 <= len(key) <= 128:
        frappe.throw("Use a valid password reset link.", frappe.ValidationError)
    validate_new_password(password, confirm_password)
    update_password(new_password=password, key=key, logout_all_sessions=1)
    if frappe.local.response.get("http_status_code", 200) >= 400 or frappe.session.user == "Guest":
        frappe.throw("This password reset link is invalid, expired, or already used.", frappe.ValidationError)
    frappe.local.login_manager.logout()
    return {"message": "Password updated. Sign in with your new password."}
