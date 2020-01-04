try:
    from html import escape as html_escape_  # python 3

    def html_escape(str, quote=False):
        # html_escape under python 3 sets quote to true by default
        # make it python 2 compatible
        return html_escape_(str, quote=quote)
except ImportError:
    # python 2 fallback
    from cgi import escape as html_escape  # noqa: F401
