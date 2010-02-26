
try:
    from http import cookies as Cookie
    from http.cookies import CookieError, BaseCookie, SimpleCookie
    from http.cookies import _getdate as get_cookie_date
except:
    from Cookie import CookieError, BaseCookie, SimpleCookie
    from Cookie import _getdate as get_cookie_date
