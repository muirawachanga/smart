app_name = "intelligent_ordering"
app_title = "Intelligent Ordering"
app_publisher = "Project Team"
app_description = "AI-powered ordering and fulfillment management foundation"
app_email = "noreply@example.com"
app_license = "MIT"

after_install = "intelligent_ordering.install.after_install"
after_migrate = "intelligent_ordering.install.after_migrate"

doc_events = {
    "Sales Order": {
        "on_update": [
            "intelligent_ordering.utils.inventory.handle_order_status_change",
            "intelligent_ordering.utils.fulfillment_notifications.handle_order_status_change",
            "intelligent_ordering.utils.audit.audit_order_status",
        ],
    },
    "Product": {"after_insert": "intelligent_ordering.utils.audit.audit_product",
                "on_update": "intelligent_ordering.utils.audit.audit_product"},
    "Product Category": {"after_insert": "intelligent_ordering.utils.audit.audit_category",
                         "on_update": "intelligent_ordering.utils.audit.audit_category"},
    "Payment Transaction": {"on_update": "intelligent_ordering.utils.audit.audit_payment_status"},
    "Stock Ledger Entry": {"after_insert": "intelligent_ordering.utils.audit.audit_stock_movement"},
    "Delivery": {"after_insert": "intelligent_ordering.utils.audit.audit_delivery",
                 "on_update": "intelligent_ordering.utils.audit.audit_delivery"},
    "User": {
        "after_insert": "intelligent_ordering.utils.audit.audit_user_roles",
        "on_update": "intelligent_ordering.utils.audit.audit_user_roles",
    },
}

permission_query_conditions = {
    "Product": "intelligent_ordering.permissions.product_query",
    "Product Category": "intelligent_ordering.permissions.product_category_query",
    "Customer Profile": "intelligent_ordering.permissions.customer_profile_query",
    "Customer Address": "intelligent_ordering.permissions.customer_address_query",
    "Sales Order": "intelligent_ordering.permissions.sales_order_query",
    "Shopping Cart": "intelligent_ordering.permissions.shopping_cart_query",
    "Delivery": "intelligent_ordering.permissions.delivery_query",
}

has_permission = {
    "Customer Profile": "intelligent_ordering.permissions.customer_profile_has_permission",
    "Customer Address": "intelligent_ordering.permissions.customer_address_has_permission",
    "Sales Order": "intelligent_ordering.permissions.sales_order_has_permission",
    "Shopping Cart": "intelligent_ordering.permissions.shopping_cart_has_permission",
    "Delivery": "intelligent_ordering.permissions.delivery_has_permission",
}
