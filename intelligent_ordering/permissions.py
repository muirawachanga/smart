import frappe


STAFF_ROLES = {
    "System Manager",
    "Business Admin",
    "Store Manager",
    "Order Manager",
    "Finance Manager",
    "Inventory Manager",
    "Delivery Manager",
}


def _customer_only(user):
    if user == "Administrator" or STAFF_ROLES.intersection(frappe.get_roles(user)):
        return False
    return True


def _customer_read_permission(doc, ptype, user, linked_profile=None):
    if doc is None or ptype not in {"read", "select"} or not _customer_only(user):
        return None
    if "Customer" not in frappe.get_roles(user):
        return False

    profile_name = linked_profile or doc.name
    profile_user = frappe.db.get_value("Customer Profile", profile_name, "user")
    return profile_user == user


def customer_profile_query(user):
    user = user or frappe.session.user
    if not _customer_only(user):
        return ""
    return f"`tabCustomer Profile`.`user` = {frappe.db.escape(user)}"


def product_query(user):
    user = user or frappe.session.user
    if not _customer_only(user):
        return ""
    return (
        "`tabProduct`.`enabled` = 1 AND "
        "(`tabProduct`.`category` IS NULL OR `tabProduct`.`category` = '' OR "
        "EXISTS (SELECT 1 FROM `tabProduct Category` "
        "WHERE `tabProduct Category`.`name` = `tabProduct`.`category` "
        "AND `tabProduct Category`.`enabled` = 1))"
    )


def product_category_query(user):
    user = user or frappe.session.user
    if not _customer_only(user):
        return ""
    return "`tabProduct Category`.`enabled` = 1"


def customer_address_query(user):
    user = user or frappe.session.user
    if not _customer_only(user):
        return ""
    escaped_user = frappe.db.escape(user)
    return (
        "`tabCustomer Address`.`customer` IN "
        "(SELECT `tabCustomer Profile`.`name` FROM `tabCustomer Profile` "
        f"WHERE `tabCustomer Profile`.`user` = {escaped_user})"
    )


def sales_order_query(user):
    user = user or frappe.session.user
    if not _customer_only(user):
        return ""
    escaped_user = frappe.db.escape(user)
    return (
        "`tabSales Order`.`customer` IN "
        "(SELECT `tabCustomer Profile`.`name` FROM `tabCustomer Profile` "
        f"WHERE `tabCustomer Profile`.`user` = {escaped_user})"
    )


def shopping_cart_query(user):
    user = user or frappe.session.user
    if user == "Administrator" or STAFF_ROLES.intersection(frappe.get_roles(user)):
        return ""
    if "Customer" not in frappe.get_roles(user):
        return "1 = 0"
    return f"`tabShopping Cart`.`user` = {frappe.db.escape(user)}"


def customer_profile_has_permission(doc, ptype, user=None):
    user = user or frappe.session.user
    return _customer_read_permission(doc, ptype, user)


def customer_address_has_permission(doc, ptype, user=None):
    user = user or frappe.session.user
    if doc is None or ptype not in {"read", "select"} or not _customer_only(user):
        return None
    if "Customer" not in frappe.get_roles(user):
        return False

    return frappe.db.get_value("Customer Profile", doc.customer, "user") == user


def sales_order_has_permission(doc, ptype, user=None):
    user = user or frappe.session.user
    if doc is None or ptype not in {"read", "select"} or not _customer_only(user):
        return None
    if "Customer" not in frappe.get_roles(user):
        return False

    return _customer_read_permission(doc, ptype, user, doc.customer)


def shopping_cart_has_permission(doc, ptype, user=None):
    user = user or frappe.session.user
    if user == "Administrator" or STAFF_ROLES.intersection(frappe.get_roles(user)):
        return None
    if "Customer" not in frappe.get_roles(user):
        return False
    if ptype not in {"create", "read", "write", "select"} or doc is None:
        return False
    return doc.user == user


def delivery_query(user):
    from intelligent_ordering.api.deliveries import is_manager

    user = user or frappe.session.user
    if is_manager(user):
        return ""
    if "Delivery Staff" not in frappe.get_roles(user):
        return "1 = 0"
    return f"`tabDelivery`.`assigned_delivery_person` = {frappe.db.escape(user)}"


def delivery_has_permission(doc, ptype, user=None):
    from intelligent_ordering.api.deliveries import is_manager

    user = user or frappe.session.user
    if ptype not in {"read", "select"}:
        return False
    if is_manager(user):
        return None
    return bool(
        doc and "Delivery Staff" in frappe.get_roles(user)
        and doc.assigned_delivery_person == user
    )
