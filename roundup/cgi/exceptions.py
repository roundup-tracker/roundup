"""Exceptions for use in Roundup's web interface.
"""

__docformat__ = 'restructuredtext'

from roundup.exceptions import LoginError, Unauthorised  # noqa: F401

from roundup.anypy.html import html_escape

from roundup.exceptions import RoundupException


class RoundupCGIException(RoundupException):
    pass


class HTTPException(RoundupCGIException):
    """Base exception for all HTTP error codes."""
    pass


class Redirect(HTTPException):
    """HTTP 302 status code"""
    pass


class NotModified(HTTPException):
    """HTTP 304 status code"""
    pass


class NotFound(HTTPException):
    """HTTP 404 status code unless self.response_code is set to
       400 prior to raising exception.
    """
    pass


class PreconditionFailed(HTTPException):
    """HTTP 412 status code"""
    pass


class RateLimitExceeded(HTTPException):
    """HTTP 429 error code"""
    pass


class DetectorError(RoundupException):
    """Raised when a detector throws an exception.
Contains details of the exception."""
    def __init__(self, subject, html, txt):
        self.subject = subject
        self.html = html
        self.txt = txt
        BaseException.__init__(self, subject + ' ' + txt)


class FormError(ValueError):
    """An 'expected' exception occurred during form parsing.

    That is, something we know can go wrong, and don't want to alarm the user
    with.

    We trap this at the user interface level and feed back a nice error to the
    user.

    """
    pass


class IndexerQueryError(RoundupException):
    """Raised to handle errors from FTS searches due to query
       syntax errors.
    """
    pass


class SendFile(RoundupException):
    """Send a file from the database."""


class SendStaticFile(RoundupException):
    """Send a static file from the instance html directory."""


class SeriousError(RoundupException):
    """Raised when we can't reasonably display an error message on a
    templated page.

    The exception value will be displayed in the error page, HTML
    escaped.
    """
    def __str__(self):
        return """
<html><head><title>Roundup issue tracker: An error has occurred</title>
 <link rel="stylesheet" type="text/css" href="@@file/style.css">
</head>
<body class="body" marginwidth="0" marginheight="0">
 <p class="error-message">%s</p>
</body></html>
""" % html_escape(self.args[0])

# vim: set filetype=python sts=4 sw=4 et si :
