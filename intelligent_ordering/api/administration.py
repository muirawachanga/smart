import csv
import io

import frappe

from intelligent_ordering.utils.admin_analytics import (
    PERIOD_FORMATS,
    REPORTS,
    build_order_filter_sql,
    build_payment_filter_sql,
    parse_report_filters,
    report_filename,
    spreadsheet_cell,
)
from intelligent_ordering.utils.validation import validate_pagination


ROLE_GROUPS = {
    "overview": {
        "System Manager", "Business Admin", "Store Manager", "Order Manager",
        "Finance Manager", "Inventory Manager", "Delivery Manager",
    },
    "store": {"System Manager", "Business Admin", "Store Manager", "Order Manager"},
    "finance": {"System Manager", "Business Admin", "Store Manager", "Finance Manager"},
    "payment_export": {"System Manager", "Business Admin", "Finance Manager"},
    "inventory": {"System Manager", "Business Admin", "Inventory Manager"},
    "delivery": {
        "System Manager", "Business Admin", "Delivery Manager", "Order Manager",
    },
    "audit": {"System Manager", "Business Admin", "Store Manager"},
}
ORDER_STATUSES = (
    "Pending", "Confirmed", "Processing", "Ready for Delivery", "Completed", "Cancelled",
)
PAYMENT_STATUSES = (
    "Initiated", "Pending", "Successful", "Failed", "Cancelled", "Reversed",
)


def _require(group):
    roles = frappe.get_roles(frappe.session.user)
    if frappe.session.user != "Administrator" and not ROLE_GROUPS[group].intersection(roles):
        frappe.throw("You are not authorized to access this administration data.", frappe.PermissionError)


def _require_any(*groups):
    roles = set(frappe.get_roles(frappe.session.user))
    if frappe.session.user != "Administrator" and not any(
        roles.intersection(ROLE_GROUPS[group]) for group in groups
    ):
        frappe.throw("You are not authorized to access this administration data.", frappe.PermissionError)


def _filters(**values):
    try:
        return parse_report_filters(**values)
    except ValueError as error:
        frappe.throw(str(error), frappe.ValidationError)


def _page(page, page_size):
    try:
        return validate_pagination(page, page_size)
    except ValueError as error:
        frappe.throw(str(error), frappe.ValidationError)


def _order_predicate(filters):
    return build_order_filter_sql(filters)


def _payment_predicate(filters):
    return build_payment_filter_sql(filters)


@frappe.whitelist()
def dashboard():
    _require("overview")
    business = frappe.db.sql(
        """
        SELECT
          (SELECT COUNT(*) FROM `tabSales Order`) AS total_orders,
          (SELECT COUNT(*) FROM `tabCustomer Profile`) AS total_customers,
          (SELECT COUNT(*) FROM `tabProduct`) AS total_products,
          (SELECT COUNT(*) FROM `tabPayment Transaction` WHERE status = 'Successful') AS successful_payments,
          (SELECT COUNT(*) FROM `tabPayment Transaction` WHERE status IN ('Initiated','Pending')) AS pending_payments,
          (SELECT COUNT(*) FROM `tabSales Order` WHERE status = 'Pending') AS pending_orders,
          (SELECT COUNT(*) FROM `tabSales Order` WHERE status = 'Completed') AS completed_orders,
          (SELECT COUNT(*) FROM `tabSales Order` WHERE status = 'Cancelled') AS cancelled_orders,
          (SELECT COALESCE(SUM(amount), 0) FROM `tabPayment Transaction`
             WHERE status = 'Successful') AS total_sales
        """, as_dict=True,
    )[0]
    stock = frappe.db.sql(
        """
        SELECT COALESCE(SUM(b.quantity_on_hand), 0) AS total_stock,
               COALESCE(SUM(b.available_quantity), 0) AS available_stock,
               COALESCE(SUM(b.reserved_quantity), 0) AS reserved_stock
        FROM `tabStock Balance` b
        INNER JOIN `tabStock Warehouse` w
          ON w.name = b.warehouse AND w.status = 'Active'
        """, as_dict=True,
    )[0]
    stock_alerts = frappe.db.sql(
        """
        SELECT
          SUM(CASE WHEN COALESCE(s.available, 0) = 0 THEN 1 ELSE 0 END) AS out_of_stock_products,
          SUM(CASE WHEN s.available BETWEEN 1 AND 5 THEN 1 ELSE 0 END) AS low_stock_products
        FROM `tabProduct` p
        LEFT JOIN (
          SELECT b.product, SUM(b.available_quantity) AS available
          FROM `tabStock Balance` b
          INNER JOIN `tabStock Warehouse` w ON w.name = b.warehouse AND w.status = 'Active'
          GROUP BY b.product
        ) s ON s.product = p.name
        WHERE p.enabled = 1
        """, as_dict=True,
    )[0]
    deliveries = frappe.db.sql(
        """
        SELECT
          SUM(status = 'Awaiting Assignment') AS pending_deliveries,
          SUM(status IN ('Assigned','Accepted','Preparing','Ready for Dispatch')) AS assigned_deliveries,
          SUM(status IN ('Picked Up','Dispatched','In Transit')) AS dispatched_deliveries,
          SUM(status = 'Delivered') AS completed_deliveries,
          SUM(status = 'Failed') AS failed_deliveries
        FROM `tabDelivery`
        """, as_dict=True,
    )[0]
    roles = set(frappe.get_roles(frappe.session.user))
    result = {"business": {}, "inventory": {}, "delivery": {}}
    if frappe.session.user == "Administrator" or roles.intersection(ROLE_GROUPS["store"] | ROLE_GROUPS["finance"]):
        result["business"] = _integers(business)
    if frappe.session.user == "Administrator" or roles.intersection(ROLE_GROUPS["inventory"]):
        result["inventory"] = {
            "total_stock": int(stock.total_stock or 0),
            "available_stock": int(stock.available_stock or 0),
            "reserved_stock": int(stock.reserved_stock or 0),
            "low_stock_products": int(stock_alerts.low_stock_products or 0),
            "out_of_stock_products": int(stock_alerts.out_of_stock_products or 0),
        }
    if frappe.session.user == "Administrator" or roles.intersection(ROLE_GROUPS["delivery"]):
        result["delivery"] = _integers(deliveries)
    result["access"] = {
        "store": frappe.session.user == "Administrator" or bool(roles.intersection(ROLE_GROUPS["store"])),
        "finance": frappe.session.user == "Administrator" or bool(roles.intersection(ROLE_GROUPS["finance"])),
        "payment_export": frappe.session.user == "Administrator" or bool(roles.intersection(ROLE_GROUPS["payment_export"])),
        "inventory": frappe.session.user == "Administrator" or bool(roles.intersection(ROLE_GROUPS["inventory"])),
        "delivery": frappe.session.user == "Administrator" or bool(roles.intersection(ROLE_GROUPS["delivery"])),
        "audit": frappe.session.user == "Administrator" or bool(roles.intersection(ROLE_GROUPS["audit"])),
    }
    return result


def _integers(row):
    return {key: (int(value or 0) if key != "total_sales" else float(value or 0))
            for key, value in row.items()}


@frappe.whitelist()
def sales_analytics(
    start_date="", end_date="", product="", category="",
    order_status="", payment_status="",
):
    _require("finance")
    filters = _filters(
        start_date=start_date, end_date=end_date, product=product, category=category,
        order_status=order_status, payment_status=payment_status,
    )
    series = {}
    for period, date_format in PERIOD_FORMATS.items():
        series[period] = _sales_series(date_format, filters)
    return {
        **series,
        "by_product": _sales_by_product(filters),
        "by_category": _sales_by_category(filters),
        "by_delivery_area": _sales_by_area(filters),
        "basis": "Verified successful payments grouped by transaction date.",
        "filters": filters,
    }


@frappe.whitelist()
def filter_options():
    _require_any("store", "finance")
    return {
        "products": frappe.get_all(
            "Product", fields=["name", "product_name"], order_by="product_name",
            limit_page_length=0,
        ),
        "categories": frappe.get_all(
            "Product Category", fields=["name", "category_name"],
            order_by="category_name", limit_page_length=0,
        ),
    }


def _sales_series(date_format, filters):
    where, values = _payment_predicate(filters)
    return frappe.db.sql(
        f"""
        SELECT DATE_FORMAT(t.transaction_date, %s) AS period,
               COUNT(*) AS payments, SUM(t.amount) AS sales
        FROM `tabPayment Transaction` t
        INNER JOIN `tabSales Order` o ON o.name = t.`order`
        WHERE {where}
        GROUP BY DATE_FORMAT(t.transaction_date, %s)
        ORDER BY MIN(t.transaction_date)
        """, [date_format, *values, date_format], as_dict=True,
    )


def _sales_by_product(filters):
    order_filters = {**filters, "start_date": "", "end_date": ""}
    where, values = _order_predicate(order_filters)
    payment_where, payment_values = _payment_predicate(filters)
    return frappe.db.sql(
        f"""
        SELECT i.product AS product, i.product_name_snapshot AS product_name,
               SUM(i.quantity) AS quantity_sold, SUM(i.line_total) AS item_sales
        FROM `tabSales Order Item` i
        INNER JOIN `tabSales Order` o ON o.name = i.parent
        WHERE {where}
          AND EXISTS (
            SELECT 1 FROM `tabPayment Transaction` t
            INNER JOIN `tabSales Order` paid_order ON paid_order.name = t.`order`
            WHERE t.`order` = o.name AND {payment_where}
          )
        GROUP BY i.product, i.product_name_snapshot
        ORDER BY item_sales DESC, product_name
        LIMIT 100
        """, [*values, *payment_values], as_dict=True,
    )


def _sales_by_category(filters):
    order_filters = {**filters, "start_date": "", "end_date": ""}
    where, values = _order_predicate(order_filters)
    payment_where, payment_values = _payment_predicate(filters)
    return frappe.db.sql(
        f"""
        SELECT COALESCE(c.category_name, 'Uncategorized') AS category,
               SUM(i.line_total) AS item_sales, SUM(i.quantity) AS quantity_sold
        FROM `tabSales Order Item` i
        INNER JOIN `tabSales Order` o ON o.name = i.parent
        LEFT JOIN `tabProduct Category` c ON c.name = i.product_category_snapshot
        WHERE {where}
          AND EXISTS (
            SELECT 1 FROM `tabPayment Transaction` t
            INNER JOIN `tabSales Order` paid_order ON paid_order.name = t.`order`
            WHERE t.`order` = o.name AND {payment_where}
          )
        GROUP BY c.category_name
        ORDER BY item_sales DESC, category
        LIMIT 100
        """, [*values, *payment_values], as_dict=True,
    )


def _sales_by_area(filters):
    where, values = _payment_predicate(filters)
    return frappe.db.sql(
        f"""
        SELECT COALESCE(NULLIF(o.delivery_area, ''), 'Unspecified') AS delivery_area,
               COUNT(*) AS successful_payments, SUM(t.amount) AS sales
        FROM `tabPayment Transaction` t
        INNER JOIN `tabSales Order` o ON o.name = t.`order`
        WHERE {where}
        GROUP BY o.delivery_area
        ORDER BY sales DESC, delivery_area
        LIMIT 100
        """, values, as_dict=True,
    )


@frappe.whitelist()
def list_customers(search="", page=1, page_size=20):
    _require("store")
    if not isinstance(search, str) or len(search) > 100:
        frappe.throw("Customer search must be at most 100 characters.", frappe.ValidationError)
    page, page_size = _page(page, page_size)
    pattern = f"%{search.strip()}%"
    rows = frappe.db.sql(
        """
        SELECT c.name, c.full_name, c.phone, c.enabled, u.email,
               COUNT(DISTINCT o.name) AS total_orders,
               COALESCE(MAX(customer_payments.amount), 0) AS successful_payments,
               MAX(o.order_datetime) AS last_order
        FROM `tabCustomer Profile` c
        LEFT JOIN `tabUser` u ON u.name = c.user
        LEFT JOIN `tabSales Order` o ON o.customer = c.name
        LEFT JOIN (
          SELECT customer, SUM(amount) AS amount
          FROM `tabPayment Transaction` WHERE status = 'Successful'
          GROUP BY customer
        ) customer_payments ON customer_payments.customer = c.name
        WHERE (%s = '%%' OR c.name LIKE %s OR c.full_name LIKE %s
               OR c.phone LIKE %s OR u.email LIKE %s)
        GROUP BY c.name, c.full_name, c.phone, c.enabled, u.email
        ORDER BY c.full_name, c.name
        LIMIT %s OFFSET %s
        """, (pattern, pattern, pattern, pattern, pattern, page_size + 1,
              (page - 1) * page_size), as_dict=True,
    )
    return {"customers": rows[:page_size], "has_more": len(rows) > page_size, "page": page}


@frappe.whitelist()
def customer_activity(customer, page=1, page_size=20):
    _require("store")
    if not isinstance(customer, str) or not customer.strip() or len(customer) > 140:
        frappe.throw("Customer identifier is invalid.", frappe.ValidationError)
    page, page_size = _page(page, page_size)
    profile = frappe.get_doc("Customer Profile", customer.strip())
    profile.check_permission("read")
    orders = frappe.db.sql(
        """
        SELECT name, order_datetime, status, payment_status, currency, subtotal,
               delivery_fee, total
        FROM `tabSales Order` WHERE customer = %s
        ORDER BY order_datetime DESC, creation DESC LIMIT %s OFFSET %s
        """, (profile.name, page_size + 1, (page - 1) * page_size), as_dict=True,
    )
    return {
        "customer": {
            "name": profile.name, "full_name": profile.full_name,
            "phone": profile.phone, "enabled": profile.enabled,
            "email": frappe.db.get_value("User", profile.user, "email"),
        },
        "orders": orders[:page_size], "has_more": len(orders) > page_size,
        "page": page,
    }


@frappe.whitelist()
def product_performance(search="", category="", page=1, page_size=20):
    _require("store")
    if not isinstance(search, str) or len(search) > 100:
        frappe.throw("Product search must be at most 100 characters.", frappe.ValidationError)
    if not isinstance(category, str) or len(category) > 140:
        frappe.throw("Product category is invalid.", frappe.ValidationError)
    page, page_size = _page(page, page_size)
    pattern = f"%{search.strip()}%"
    rows = frappe.db.sql(
        """
        SELECT p.name, p.sku, p.product_name, p.category, p.price, p.currency,
               p.enabled, COUNT(DISTINCT CASE WHEN EXISTS (
                 SELECT 1 FROM `tabPayment Transaction` paid
                 WHERE paid.`order` = o.name AND paid.status = 'Successful'
               ) THEN o.name END) AS orders,
               COALESCE(SUM(CASE WHEN EXISTS (
                 SELECT 1 FROM `tabPayment Transaction` paid
                 WHERE paid.`order` = o.name AND paid.status = 'Successful'
               ) THEN i.quantity ELSE 0 END), 0) AS units_sold,
               COALESCE(SUM(CASE WHEN EXISTS (
                 SELECT 1 FROM `tabPayment Transaction` paid
                 WHERE paid.`order` = o.name AND paid.status = 'Successful'
               ) THEN i.line_total ELSE 0 END), 0) AS item_sales
        FROM `tabProduct` p
        LEFT JOIN `tabSales Order Item` i ON i.product = p.name
        LEFT JOIN `tabSales Order` o ON o.name = i.parent
        WHERE (%s = '%%' OR p.name LIKE %s OR p.sku LIKE %s OR p.product_name LIKE %s)
          AND (%s = '' OR p.category = %s)
        GROUP BY p.name, p.sku, p.product_name, p.category, p.price, p.currency, p.enabled
        ORDER BY units_sold DESC, p.product_name
        LIMIT %s OFFSET %s
        """, (pattern, pattern, pattern, pattern, category, category,
              page_size + 1, (page - 1) * page_size), as_dict=True,
    )
    return {"products": rows[:page_size], "has_more": len(rows) > page_size, "page": page}


@frappe.whitelist()
def admin_order_detail(order_name):
    _require("store")
    if not isinstance(order_name, str) or not order_name.strip() or len(order_name) > 140:
        frappe.throw("Order number is invalid.", frappe.ValidationError)
    order = frappe.get_doc("Sales Order", order_name.strip())
    order.check_permission("read")
    from intelligent_ordering.api.checkout import _serialize_order

    payments = frappe.get_all(
        "Payment Transaction", filters={"order": order.name},
        fields=["name", "status", "amount", "phone_number", "mpesa_receipt_number", "transaction_date"],
        order_by="creation desc", limit_page_length=100,
    )
    delivery = frappe.get_all(
        "Delivery", filters={"order": order.name},
        fields=["name", "status", "delivery_area", "delivery_address", "customer_phone",
                "delivery_fee", "currency", "assigned_delivery_person",
                "scheduled_delivery_date", "dispatch_date", "completion_date", "completed_by"],
        limit_page_length=1,
    )
    return {**_serialize_order(order), "payments": payments, "delivery": delivery[0] if delivery else None}


@frappe.whitelist()
def audit_events(search="", page=1, page_size=50):
    _require("audit")
    if not isinstance(search, str) or len(search) > 140:
        frappe.throw("Audit search must be at most 140 characters.", frappe.ValidationError)
    page, page_size = _page(page, page_size)
    pattern = f"%{search.strip()}%"
    rows = frappe.get_list(
        "Admin Audit Log",
        fields=["name", "event_type", "reference_doctype", "reference_name",
                "responsible_user", "event_datetime", "details"],
        or_filters=[
            ["reference_name", "like", pattern],
            ["event_type", "like", pattern],
            ["responsible_user", "like", pattern],
        ] if search.strip() else [],
        order_by="event_datetime desc", limit_start=(page - 1) * page_size,
        limit_page_length=page_size + 1,
    )
    return {"events": rows[:page_size], "has_more": len(rows) > page_size, "page": page}


REPORT_ACCESS = {
    "sales": "finance",
    "orders": "store",
    "customers": "store",
    "payments": "payment_export",
    "inventory": "inventory",
    "deliveries": "delivery",
}


@frappe.whitelist()
def export_report(
    report, file_format="csv", start_date="", end_date="", product="",
    category="", order_status="", payment_status="",
):
    if not isinstance(report, str) or report not in REPORTS:
        frappe.throw("Select a supported report.", frappe.ValidationError)
    _require(REPORT_ACCESS[report])
    filters = _filters(
        start_date=start_date, end_date=end_date, product=product, category=category,
        order_status=order_status, payment_status=payment_status,
    )
    if report == "inventory" and any(
        filters[key] for key in ("start_date", "end_date", "order_status", "payment_status")
    ):
        frappe.throw(
            "Inventory exports are current stock snapshots; clear date, order, and payment filters.",
            frappe.ValidationError,
        )
    try:
        filename = report_filename(
            report, file_format, filters["start_date"], filters["end_date"]
        )
    except ValueError as error:
        frappe.throw(str(error), frappe.ValidationError)
    headers, rows = _report_rows(report, filters)
    if file_format == "csv":
        stream = io.StringIO(newline="")
        writer = csv.writer(stream, lineterminator="\r\n")
        writer.writerow(headers)
        writer.writerows(rows)
        content = "\ufeff" + stream.getvalue()
        content_type = "text/csv; charset=utf-8"
    else:
        from frappe.utils.xlsxutils import make_xlsx

        content = make_xlsx([headers, *rows], f"{report[:30]} report").getvalue()
        content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    frappe.response["filename"] = filename
    frappe.response["filecontent"] = content
    frappe.response["type"] = "download"
    frappe.response["content_type"] = content_type


def _report_rows(report, filters):
    order_where, order_values = _order_predicate(filters)
    payment_where, payment_values = _payment_predicate(filters)
    if report == "sales":
        rows = frappe.db.sql(
            f"""
            SELECT t.name AS payment, t.transaction_date, t.`order`, t.mpesa_receipt_number,
                   t.amount, o.currency, o.customer_name_snapshot, o.delivery_area
            FROM `tabPayment Transaction` t
            INNER JOIN `tabSales Order` o ON o.name = t.`order`
            WHERE {payment_where}
            ORDER BY t.transaction_date, t.name
            LIMIT 50001
            """, payment_values, as_dict=True,
        )
        headers = ["Payment", "Payment Date", "Order", "M-Pesa Receipt", "Amount",
                   "Currency", "Customer", "Delivery Area"]
    elif report == "orders":
        rows = frappe.db.sql(
            f"""
            SELECT o.name, o.order_datetime, o.customer_name_snapshot, o.customer_phone_snapshot,
                   o.status, o.payment_status, o.currency, o.subtotal, o.delivery_fee, o.total,
                   o.delivery_area
            FROM `tabSales Order` o WHERE {order_where}
            ORDER BY o.order_datetime LIMIT 50001
            """, order_values, as_dict=True,
        )
        headers = ["Order", "Order Date", "Customer", "Phone", "Status", "Payment Status",
                   "Currency", "Subtotal", "Delivery Fee", "Total", "Delivery Area"]
    elif report == "customers":
        customer_where = ""
        customer_values = []
        if any(filters.values()):
            customer_where, customer_values = build_order_filter_sql(
                filters, order_alias="filtered_order", item_alias="customer_filter_item"
            )
            customer_where = (
                f"WHERE EXISTS (SELECT 1 FROM `tabSales Order` filtered_order "
                f"WHERE filtered_order.customer = c.name AND {customer_where})"
            )
        else:
            customer_where = ""
        rows = frappe.db.sql(
            f"""
            SELECT c.name, c.full_name, c.phone, u.email, c.enabled,
                   COUNT(DISTINCT o.name) AS orders, MAX(o.order_datetime) AS last_order
            FROM `tabCustomer Profile` c
            LEFT JOIN `tabUser` u ON u.name = c.user
            LEFT JOIN `tabSales Order` o ON o.customer = c.name
            {customer_where}
            GROUP BY c.name, c.full_name, c.phone, u.email, c.enabled
            ORDER BY c.full_name LIMIT 50001
            """, customer_values, as_dict=True,
        )
        headers = ["Customer", "Name", "Phone", "Email", "Enabled", "Orders", "Last Order"]
    elif report == "payments":
        rows = frappe.db.sql(
            f"""
            SELECT p.name, p.`order`, p.customer, p.phone_number, p.amount, p.status,
                   p.mpesa_receipt_number, p.transaction_date, p.environment
            FROM `tabPayment Transaction` p
            INNER JOIN `tabSales Order` o ON o.name = p.`order`
            WHERE ( %s = '' OR DATE(p.transaction_date) >= %s )
              AND ( %s = '' OR DATE(p.transaction_date) <= %s )
              AND ( %s = '' OR o.status = %s )
              AND ( %s = '' OR p.status = %s )
              AND ( %s = '' OR EXISTS (SELECT 1 FROM `tabSales Order Item` i
                   WHERE i.parent = o.name AND i.product = %s) )
              AND ( %s = '' OR EXISTS (SELECT 1 FROM `tabSales Order Item` i
                   WHERE i.parent = o.name AND i.product_category_snapshot = %s) )
            ORDER BY p.transaction_date LIMIT 50001
            """, (
                filters["start_date"], filters["start_date"],
                filters["end_date"], filters["end_date"],
                filters["order_status"], filters["order_status"],
                filters["payment_status"], filters["payment_status"],
                filters["product"], filters["product"],
                filters["category"], filters["category"],
            ), as_dict=True,
        )
        headers = ["Payment", "Order", "Customer", "Phone", "Amount", "Status",
                   "M-Pesa Receipt", "Transaction Date", "Environment"]
    elif report == "inventory":
        search_pattern = f"%{filters['product']}%"
        rows = frappe.db.sql(
            """
            SELECT b.product, p.sku, p.product_name, b.warehouse, w.warehouse_name,
                   b.quantity_on_hand, b.reserved_quantity, b.available_quantity
            FROM `tabStock Balance` b
            INNER JOIN `tabProduct` p ON p.name = b.product
            INNER JOIN `tabStock Warehouse` w ON w.name = b.warehouse AND w.status = 'Active'
            WHERE (%s = '%%' OR p.name LIKE %s OR p.sku LIKE %s OR p.product_name LIKE %s)
              AND (%s = '' OR p.category = %s)
            ORDER BY p.product_name, w.warehouse_name LIMIT 50001
            """, (
                search_pattern, search_pattern, search_pattern, search_pattern,
                filters["category"], filters["category"],
            ), as_dict=True,
        )
        headers = ["Product", "SKU", "Product Name", "Warehouse", "Warehouse Name",
                   "On Hand", "Reserved", "Available"]
    else:
        rows = frappe.db.sql(
            """
            SELECT d.name, d.`order`, d.customer_name, d.customer_phone,
                   d.delivery_area, d.assigned_delivery_person, d.status,
                   d.scheduled_delivery_date, d.dispatch_date, d.completion_date,
                   d.delivery_fee, d.currency
            FROM `tabDelivery` d
            INNER JOIN `tabSales Order` o ON o.name = d.`order`
            WHERE (%s = '' OR DATE(o.order_datetime) >= %s)
              AND (%s = '' OR DATE(o.order_datetime) <= %s)
              AND (%s = '' OR o.status = %s)
              AND (%s = '' OR EXISTS (SELECT 1 FROM `tabPayment Transaction` p
                   WHERE p.`order` = o.name AND p.status = %s))
              AND (%s = '' OR EXISTS (SELECT 1 FROM `tabSales Order Item` i
                   WHERE i.parent = o.name AND i.product = %s))
              AND (%s = '' OR EXISTS (SELECT 1 FROM `tabSales Order Item` i
                   WHERE i.parent = o.name AND i.product_category_snapshot = %s))
            ORDER BY d.creation LIMIT 50001
            """, (
                filters["start_date"], filters["start_date"],
                filters["end_date"], filters["end_date"],
                filters["order_status"], filters["order_status"],
                filters["payment_status"], filters["payment_status"],
                filters["product"], filters["product"],
                filters["category"], filters["category"],
            ), as_dict=True,
        )
        headers = ["Delivery", "Order", "Customer", "Phone", "Area", "Delivery Person",
                   "Status", "Scheduled", "Dispatched", "Completed", "Fee", "Currency"]
    if len(rows) > 50000:
        frappe.throw(
            "This report contains more than 50,000 rows. Add filters and export smaller date ranges.",
            frappe.ValidationError,
        )
    return headers, [_row_values(row, headers, report) for row in rows]


def _row_values(row, headers, report):
    keys = {
        "sales": ["payment", "transaction_date", "order", "mpesa_receipt_number",
                  "amount", "currency", "customer_name_snapshot", "delivery_area"],
        "orders": ["name", "order_datetime", "customer_name_snapshot", "customer_phone_snapshot",
                   "status", "payment_status", "currency", "subtotal", "delivery_fee", "total",
                   "delivery_area"],
        "customers": ["name", "full_name", "phone", "email", "enabled", "orders", "last_order"],
        "payments": ["name", "order", "customer", "phone_number", "amount", "status",
                     "mpesa_receipt_number", "transaction_date", "environment"],
        "inventory": ["product", "sku", "product_name", "warehouse", "warehouse_name",
                      "quantity_on_hand", "reserved_quantity", "available_quantity"],
        "deliveries": ["name", "order", "customer_name", "customer_phone", "delivery_area",
                       "assigned_delivery_person", "status", "scheduled_delivery_date",
                       "dispatch_date", "completion_date", "delivery_fee", "currency"],
    }[report]
    return [_safe_cell(row.get(key)) for key in keys]


def _safe_cell(value):
    return spreadsheet_cell(value)
