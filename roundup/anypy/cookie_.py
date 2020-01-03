
try:
    # Python 3+
    from http import cookies as Cookie
    from http.cookies import CookieError, BaseCookie, SimpleCookie
    from http.cookies import _getdate as get_cookie_date
except ImportError:
    # Python 2.5-2.7
    from Cookie import CookieError, BaseCookie, SimpleCookie
    from Cookie import _getdate as get_cookie_date
