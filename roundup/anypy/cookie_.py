try:
    # Python 3+
    from http import cookies as Cookie
    from http.cookies import BaseCookie, CookieError, SimpleCookie
    from http.cookies import _getdate as get_cookie_date
except ImportError:
    # ruff: noqa: F401, PLC2701
    # Python 2.5-2.7
    from Cookie import BaseCookie, CookieError, SimpleCookie
    from Cookie import _getdate as get_cookie_date
