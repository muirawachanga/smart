ERROR_PAGES = {
    403: ("This page isn't available to your account", "Sign in with the right account or contact the store for help."),
    404: ("We couldn't find that page", "Check the link or return to the homepage."),
    500: ("Something went wrong", "Please try again later or contact the store for help."),
    503: ("The store is temporarily unavailable", "Please try again later or contact the store for help."),
}


def customer_error_response(request, response):
    if not response or request.method not in {"GET", "HEAD"}:
        return
    path = request.path
    if path == "/app" or path.startswith(("/app/", "/dashboard/", "/api/", "/assets/", "/files/", "/private/")):
        return
    status = response.status_code
    if status not in ERROR_PAGES or response.mimetype != "text/html":
        return
    title, message = ERROR_PAGES[status]
    response.set_data(f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} | SmartO</title>
<style>body{{font-family:system-ui,sans-serif;background:#f8faf8;color:#1c302c;margin:0}}
main{{max-width:38rem;margin:10vh auto;padding:2rem}}a{{color:#145c4d}}.button{{display:inline-block;
background:#145c4d;color:white;padding:.8rem 1rem;border-radius:.4rem;margin:1rem 1rem 0 0}}</style>
</head><body><main><p>SmartO</p><h1>{title}</h1><p>{message}</p>
<a class="button" href="/">Return to homepage</a><a href="/contact">Contact the store</a></main></body></html>""")
    response.headers["Cache-Control"] = "no-store"
