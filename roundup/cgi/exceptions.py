class HTTPException(Exception):
    pass

class Unauthorised(HTTPException):
    pass

class Redirect(HTTPException):
    pass

class NotFound(HTTPException):
    pass

class NotModified(HTTPException):
    pass

class FormError(ValueError):
    """An 'expected' exception occurred during form parsing.

    That is, something we know can go wrong, and don't want to alarm the user
    with.

    We trap this at the user interface level and feed back a nice error to the
    user.

    """
    pass

class SendFile(Exception):
    """Send a file from the database."""

class SendStaticFile(Exception):
    """Send a static file from the instance html directory."""
