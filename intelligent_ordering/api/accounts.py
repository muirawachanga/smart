import frappe
from frappe.utils import escape_html, validate_email_address

from intelligent_ordering.api.checkout import _save_customer_profile
from intelligent_ordering.install import APP_ROLES
from intelligent_ordering.utils.audit import record_admin_event
from intelligent_ordering.utils.checkout import validate_customer_name, validate_phone
from intelligent_ordering.utils.validation import validate_pagination


def _require():
    if frappe.session.user == "Guest" or (
        frappe.session.user != "Administrator"
        and "System Manager" not in frappe.get_roles(frappe.session.user)
    ):
        frappe.throw("Only a System Manager can administer accounts.", frappe.PermissionError)


def _text(value, label, maximum=140):
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        frappe.throw(f"Enter a valid {label}.", frappe.ValidationError)
    return value.strip()


def _role(role):
    if not isinstance(role, str) or role not in APP_ROLES:
        frappe.throw("Select an approved customer or operational staff role.", frappe.ValidationError)
    if not frappe.db.exists("Role", {"name": role, "disabled": 0}):
        frappe.throw("This role is missing or disabled. Ask the administrator to review site roles.",
                     frappe.ValidationError)
    return role


def _manageable(user, roles):
    return (
        user.name not in {"Administrator", "Guest", frappe.session.user}
        and not user.get("role_profile_name")
        and len(roles) == 1 and set(roles).issubset(APP_ROLES)
    )


def _locked_user(name):
    name = _text(name, "account")
    frappe.db.sql("SELECT name FROM `tabUser` WHERE name = %s FOR UPDATE", name)
    user = frappe.get_doc("User", name, for_update=True)
    user.check_permission("write")
    roles = [row.role for row in user.get("roles", [])]
    if not _manageable(user, roles):
        frappe.throw(
            "This account is protected or has a custom/multiple-role setup. Manage it in Desk.",
            frappe.PermissionError,
        )
    return user, roles[0]


def _send_invitation(user):
    try:
        user.send_welcome_mail_to_user()
    except frappe.OutgoingEmailError:
        frappe.clear_messages()
        frappe.throw(
            "Password-setup email could not be queued. Configure an enabled default outgoing Email Account in Frappe and retry.",
            frappe.ValidationError,
        )


@frappe.whitelist()
def list_accounts(search="", page=1, page_size=20):
    _require()
    if not isinstance(search, str) or len(search) > 140:
        frappe.throw("Search must be text of at most 140 characters.", frappe.ValidationError)
    try:
        page, page_size = validate_pagination(page, page_size)
    except ValueError as error:
        frappe.throw(str(error), frappe.ValidationError)
    pattern = f"%{search.strip()}%"
    users = frappe.get_list(
        "User", fields=["name", "email", "full_name", "enabled", "user_type", "modified", "role_profile_name"],
        filters={"name": ["not in", ["Administrator", "Guest"]]},
        or_filters=[[field, "like", pattern] for field in ("email", "full_name")] if search.strip() else [],
        order_by="full_name asc, name asc", limit_start=(page - 1) * page_size,
        limit_page_length=page_size + 1,
    )
    selected = users[:page_size]
    role_rows = frappe.get_all(
        "Has Role", filters={"parent": ["in", [user.name for user in selected]], "parenttype": "User"},
        fields=["parent", "role"], limit_page_length=0,
    ) if selected else []
    for user in selected:
        user.roles = sorted(row.role for row in role_rows if row.parent == user.name)
        user.can_manage = bool(_manageable(user, user.roles))
    return {"accounts": selected, "roles": list(APP_ROLES), "page": page, "has_more": len(users) > page_size}


@frappe.whitelist(methods=["POST"])
def create_account(email, full_name, phone, role):
    _require()
    role = _role(role)
    email = validate_email_address(_text(email, "email address").lower(), throw=True)
    try:
        full_name = validate_customer_name(full_name)
        phone = validate_phone(phone)
    except ValueError as error:
        frappe.throw(str(error), frappe.ValidationError)
    if frappe.db.exists("User", email):
        frappe.throw("This email already has an account. Search and manage the existing account.", frappe.ValidationError)
    user = frappe.get_doc({
        "doctype": "User", "email": email, "first_name": escape_html(full_name), "mobile_no": phone,
        "enabled": 1, "user_type": "System User" if APP_ROLES[role] else "Website User",
        "send_welcome_email": 0, "roles": [{"role": role}],
    })
    user.insert()
    if {row.role for row in user.get("roles", [])} != {role}:
        frappe.throw("Site defaults changed the requested roles. Review User configuration in Desk.",
                     frappe.ValidationError)
    if role == "Customer":
        _save_customer_profile(user.name, full_name, phone)
    # Avoid Frappe's notification wrapper, which suppresses outgoing-mail errors.
    _send_invitation(user)
    record_admin_event("Account invitation requested", "User", user.name, f"Assigned role: {role}")
    return {"name": user.name, "message": "Account created and password-setup email queued. Delivery is not confirmed."}


@frappe.whitelist(methods=["POST"])
def update_access(user_name, role, enabled, modified):
    _require()
    role = _role(role)
    if enabled not in (0, 1, "0", "1"):
        frappe.throw("Choose a valid account status.", frappe.ValidationError)
    user, previous_role = _locked_user(user_name)
    if not isinstance(modified, str) or str(user.modified) != modified:
        frappe.throw("Account changed. Refresh before updating access.", frappe.ValidationError)
    if (previous_role == "Customer") != (role == "Customer"):
        frappe.throw("Keep customer and staff accounts separate; conversion is not supported here.",
                     frappe.ValidationError)
    if previous_role == "Delivery Staff" and (role != previous_role or not int(enabled)):
        if frappe.db.exists("Delivery", {
            "assigned_delivery_person": user.name, "status": ["not in", ["Delivered", "Cancelled"]],
        }):
            frappe.throw("Resolve or reassign this rider's undelivered assignments before changing access.",
                         frappe.ValidationError)
    user.set("roles", [{"role": role}])
    user.enabled = int(enabled)
    user.save()
    from frappe.sessions import clear_sessions

    # Role or enabled changes must also apply to already authenticated sessions.
    clear_sessions(user=user.name, force=True)
    return {"message": "Access updated. Existing sessions were revoked; the user must sign in again."}


@frappe.whitelist(methods=["POST"])
def send_invitation(user_name):
    _require()
    user, role = _locked_user(user_name)
    if not user.enabled:
        frappe.throw("Enable this account before sending password-setup instructions.", frappe.ValidationError)
    _send_invitation(user)
    record_admin_event("Account invitation requested", "User", user.name, f"Assigned role: {role}")
    return {"message": "Password-setup email queued. Delivery is not confirmed; previous setup links may no longer work."}
