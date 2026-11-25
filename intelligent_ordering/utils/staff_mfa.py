import frappe

from intelligent_ordering.install import APP_ROLES
from intelligent_ordering.utils.audit import record_admin_event


STAFF_ROLES = (set(APP_ROLES) - {"Customer"}) | {"System Manager"}


def configure(roles, activate=False, confirmation="", email_verified=False):
    """Preview or activate staff MFA through Bench, never a public API."""
    if frappe.session.user != "Administrator" and "System Manager" not in frappe.get_roles():
        frappe.throw("Only a System Manager can configure staff MFA.", frappe.PermissionError)
    if (
        not isinstance(roles, list) or not roles
        or any(not isinstance(role, str) or role not in STAFF_ROLES for role in roles)
    ):
        frappe.throw("Select a non-empty list of SmartO staff roles.", frappe.ValidationError)
    if not isinstance(activate, bool) or not isinstance(email_verified, bool):
        frappe.throw("Activation and email verification must be boolean values.", frappe.ValidationError)
    selected = sorted(set(roles))
    for role in selected:
        if not frappe.db.exists("Role", role):
            frappe.throw(f"Role {role} is missing. Run migrate first.", frappe.ValidationError)

    settings = frappe.get_doc("System Settings")
    enabled = bool(settings.enable_two_factor_auth)
    enabled_roles = set(frappe.get_all("Role", filters={"two_factor_auth": 1}, pluck="name"))
    outside_staff = enabled_roles - STAFF_ROLES
    if not enabled:
        outside_staff.discard("All")
    if outside_staff or (enabled and (
        settings.two_factor_method != "OTP App" or settings.bypass_2fa_for_retricted_ip_users
    )):
        frappe.throw(
            "Existing MFA settings conflict with staff-only authenticator MFA. "
            "Review System Settings and Role MFA flags before changing this site's policy.",
            frappe.ValidationError,
        )
    result = {
        "site": frappe.local.site,
        "status": "preview",
        "method": "OTP App",
        "roles": sorted((enabled_roles & STAFF_ROLES) | set(selected)),
        "notice": "Applies at the next password login. Existing sessions are not revoked. "
                  "First-time enrollment requires working outgoing email. "
                  "Review all users holding the selected roles before activation.",
    }
    if not activate:
        return result
    if confirmation != frappe.local.site or not email_verified:
        frappe.throw(
            "Confirm this site's exact name and verify outgoing enrollment email before activation.",
            frappe.ValidationError,
        )

    frappe.db.savepoint("smarto_staff_mfa")
    try:
        settings.enable_two_factor_auth = 1
        settings.two_factor_method = "OTP App"
        settings.bypass_2fa_for_retricted_ip_users = 0
        settings.otp_issuer_name = settings.otp_issuer_name or "SmartO"
        settings.save(ignore_permissions=True)
        # Frappe enables the All role when global MFA is first enabled.
        for role_name in ["All", *selected]:
            role = frappe.get_doc("Role", role_name)
            role.two_factor_auth = int(role_name != "All")
            role.save(ignore_permissions=True)
        record_admin_event("Staff MFA enabled", "System Settings", "System Settings", ", ".join(selected))
    except Exception:
        frappe.db.rollback(save_point="smarto_staff_mfa")
        raise
    result["status"] = "activated"
    return result
