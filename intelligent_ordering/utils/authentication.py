from urllib.parse import unquote, urlsplit

import frappe

from intelligent_ordering.utils.staff_pages import PAGE_ROLES


SHOPPING_PATHS = {
    "/", "/products", "/categories", "/cart", "/checkout", "/payment", "/track-order",
    "/account", "/account/profile", "/account/addresses", "/account/payments",
    "/account/notifications", "/order-confirmation",
}


def login_destination(requested=""):
    user = frappe.session.user
    if user == "Guest":
        frappe.throw("Authentication is required.", frappe.AuthenticationError)
    roles = set(frappe.get_roles(user))
    if isinstance(requested, str) and len(requested) <= 2048:
        # Validate the decoded destination to reject encoded external or unauthorized paths.
        decoded = unquote(requested)
        if decoded.startswith("/") and not decoded.startswith("//") and not any(
            ord(char) < 32 or char == "\\" for char in decoded
        ):
            url = urlsplit(decoded)
            path = url.path.rstrip("/") or "/"
            if not url.scheme and not url.netloc:
                if path in SHOPPING_PATHS or path.startswith("/products/"):
                    if not path.startswith("/account") or "Customer" in roles:
                        return requested
                if path.startswith("/order-confirmation/") and "Customer" in roles:
                    return requested
                if path.startswith("/dashboard/"):
                    page = path.removeprefix("/dashboard/")
                    if page in PAGE_ROLES and (user == "Administrator" or roles & PAGE_ROLES[page]):
                        return requested
    if user == "Administrator" or roles & {"System Manager", "Business Admin"}:
        return "/dashboard/admin"
    for allowed, path in (
        ({"Store Manager"}, "/dashboard/owner"),
        ({"Finance Manager"}, "/dashboard/sales"),
        ({"Order Manager"}, "/dashboard/orders"),
        ({"Inventory Manager"}, "/dashboard/inventory"),
        ({"Delivery Manager"}, "/dashboard/delivery"),
        ({"Delivery Staff"}, "/dashboard/rider"),
        ({"Customer Support"}, "/dashboard/support"),
        ({"Customer"}, "/"),
    ):
        if roles & allowed:
            return path
    return "/access-denied"


def validate_new_password(password, confirmation, user_data=()):
    from frappe.utils.password_strength import test_password_strength

    if not isinstance(password, str) or not 12 <= len(password) <= 128:
        frappe.throw("Use a password between 12 and 128 characters.", frappe.ValidationError)
    if password != confirmation:
        frappe.throw("Passwords do not match.", frappe.ValidationError)
    if test_password_strength(password, user_inputs=user_data).get("score", 0) < 3:
        frappe.throw("Choose a stronger password, such as a long, unique passphrase.", frappe.ValidationError)
