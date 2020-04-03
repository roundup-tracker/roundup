"""Exceptions for use across all Roundup components.
"""

__docformat__ = 'restructuredtext'


class RoundupException(Exception):
    pass

class LoginError(RoundupException):
    pass


class Unauthorised(RoundupException):
    pass

class RejectBase(RoundupException):
    pass

class Reject(RejectBase):
    """An auditor may raise this exception when the current create or set
    operation should be stopped.

    It is up to the specific interface invoking the create or set to
    handle this exception sanely. For example:

    - mailgw will trap and ignore Reject for file attachments and messages
    - cgi will trap and present the exception in a nice format
    """
    pass


class RejectRaw(Reject):
    """
    Performs the same function as Reject, except HTML in the message is not
    escaped when displayed to the user.
    """
    pass


class UsageError(ValueError):
    pass

# vim: set filetype=python ts=4 sw=4 et si
