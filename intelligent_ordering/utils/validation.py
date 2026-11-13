DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100
MAX_SEARCH_LENGTH = 100
MAX_CATEGORY_LENGTH = 140


def validate_pagination(page, page_size):
    """Return validated one-based page and bounded page size values."""
    parsed_page = _positive_integer(page, "page")
    parsed_page_size = _positive_integer(page_size, "page_size")

    if parsed_page_size > MAX_PAGE_SIZE:
        raise ValueError(f"page_size must not exceed {MAX_PAGE_SIZE}.")

    return parsed_page, parsed_page_size


def _positive_integer(value, field_name):
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be a positive integer.")

    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field_name} must be a positive integer.") from None

    if str(value).strip() != str(parsed) or parsed < 1:
        raise ValueError(f"{field_name} must be a positive integer.")

    return parsed


def validate_catalog_filters(search="", category="", page=1, page_size=DEFAULT_PAGE_SIZE):
    """Normalize and validate user-supplied catalog filters."""
    if search is not None and not isinstance(search, str):
        raise ValueError("search must be text.")
    if category is not None and not isinstance(category, str):
        raise ValueError("category must be text.")

    search = (search or "").strip()
    category = (category or "").strip()

    if len(search) > MAX_SEARCH_LENGTH:
        raise ValueError(f"search must not exceed {MAX_SEARCH_LENGTH} characters.")
    if len(category) > MAX_CATEGORY_LENGTH:
        raise ValueError(f"category must not exceed {MAX_CATEGORY_LENGTH} characters.")

    parsed_page, parsed_page_size = validate_pagination(page, page_size)
    return search, category, parsed_page, parsed_page_size


def escape_like(value):
    """Escape SQL LIKE metacharacters for use with ESCAPE '!'."""
    return value.replace("!", "!!").replace("%", "!%").replace("_", "!_")
