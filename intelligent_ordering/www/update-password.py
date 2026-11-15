from intelligent_ordering.utils.auth_pages import prepare_auth_page

no_cache = 1


def get_context(context):
    prepare_auth_page(context)
