from intelligent_ordering.utils.customer_pages import require_customer_page


def get_context(context):
    require_customer_page(context)
