import frappe


@frappe.whitelist(allow_guest=True)
def ping():
    """Return a minimal liveness response without exposing site configuration."""
    return {"status": "ok", "api_version": 1}


@frappe.whitelist()
def current_user():
    """Return the authenticated user's identity and assigned roles."""
    if frappe.session.user == "Guest":
        frappe.throw("Authentication is required.", frappe.AuthenticationError)

    return {
        "user": frappe.session.user,
        "roles": frappe.get_roles(frappe.session.user),
    }
