from intelligent_ordering.utils.staff_pages import require_staff_page

no_cache = 1


def get_context(context):
    require_staff_page(context, "inventory")
