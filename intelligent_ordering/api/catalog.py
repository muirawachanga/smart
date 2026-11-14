import frappe

from intelligent_ordering.utils.validation import escape_like, validate_catalog_filters


CATALOG_SORTS = {
    "name_asc": "p.product_name ASC, p.name ASC",
    "name_desc": "p.product_name DESC, p.name ASC",
    "price_asc": "p.price ASC, p.name ASC",
    "price_desc": "p.price DESC, p.name ASC",
}

PRODUCT_SELECT = """
    SELECT
        p.name, p.sku, p.product_name, c.category_name AS category,
        p.description, p.image, p.price, p.currency,
        COALESCE(stock.available_quantity, 0) AS available_quantity,
        CASE WHEN COALESCE(stock.available_quantity, 0) > 0
            THEN 'In Stock' ELSE 'Out of Stock' END AS stock_status
    FROM `tabProduct` p
    LEFT JOIN `tabProduct Category` c
        ON c.name = p.category AND c.enabled = 1
    LEFT JOIN (
        SELECT balance.product, SUM(balance.available_quantity) AS available_quantity
        FROM `tabStock Balance` AS balance
        INNER JOIN `tabStock Warehouse` AS warehouse
            ON warehouse.name = balance.warehouse AND warehouse.status = 'Active'
        GROUP BY balance.product
    ) AS stock ON stock.product = p.name
"""

PUBLIC_CONDITIONS = [
    "p.enabled = 1",
    "(p.category IS NULL OR p.category = '' OR c.name IS NOT NULL)",
]


@frappe.whitelist(allow_guest=True)
def get_catalog(search="", category="", page=1, page_size=20, sort="name_asc"):
    """Return enabled catalog products and categories for the public storefront."""
    try:
        search, category, page, page_size = validate_catalog_filters(
            search, category, page, page_size
        )
    except ValueError as error:
        frappe.throw(str(error), frappe.ValidationError)

    if not isinstance(sort, str) or sort not in CATALOG_SORTS:
        frappe.throw("The selected sort order is invalid.", frappe.ValidationError)

    conditions = PUBLIC_CONDITIONS.copy()
    values = []

    if category:
        if not frappe.db.exists(
            "Product Category", {"name": category, "enabled": 1}
        ):
            frappe.throw("The selected category is unavailable.", frappe.ValidationError)
        conditions.append("p.category = %s")
        values.append(category)

    if search:
        escaped_search = escape_like(search)
        conditions.append(
            "(p.product_name LIKE %s ESCAPE '!' "
            "OR p.sku LIKE %s ESCAPE '!' "
            "OR COALESCE(p.description, '') LIKE %s ESCAPE '!')"
        )
        values.extend([f"%{escaped_search}%"] * 3)

    where_clause = " AND ".join(conditions)
    count_rows = frappe.db.sql(
        f"""
        SELECT COUNT(*)
        FROM `tabProduct` p
        LEFT JOIN `tabProduct Category` c
            ON c.name = p.category AND c.enabled = 1
        WHERE {where_clause}
        """,
        values,
    )
    total = count_rows[0][0]

    rows = frappe.db.sql(
        f"""
        {PRODUCT_SELECT}
        WHERE {where_clause}
        ORDER BY {CATALOG_SORTS[sort]}
        LIMIT %s OFFSET %s
        """,
        values + [page_size + 1, (page - 1) * page_size],
        as_dict=True,
    )

    has_more = len(rows) > page_size
    products = rows[:page_size]
    categories = frappe.get_all(
        "Product Category",
        filters={"enabled": 1},
        fields=["name", "category_name"],
        order_by="category_name asc",
    )

    return {
        "products": products,
        "categories": categories,
        "page": page,
        "page_size": page_size,
        "total": total,
        "has_more": has_more,
    }


@frappe.whitelist(allow_guest=True)
def get_product(product):
    """Return one public product using the same visibility and stock rules as the catalog."""
    if not isinstance(product, str) or not product.strip() or len(product.strip()) > 140:
        frappe.throw("A valid product identifier is required.", frappe.ValidationError)

    rows = frappe.db.sql(
        f"""
        {PRODUCT_SELECT}
        WHERE {" AND ".join(PUBLIC_CONDITIONS)} AND p.name = %s
        LIMIT 1
        """,
        [product.strip()],
        as_dict=True,
    )
    if not rows:
        frappe.throw("This product is unavailable.", frappe.DoesNotExistError)
    return rows[0]
