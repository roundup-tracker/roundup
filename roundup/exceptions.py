#$Id: exceptions.py,v 1.1 2004-03-26 00:44:11 richard Exp $
'''Exceptions for use across all Roundup components.
'''

__docformat__ = 'restructuredtext'

class Reject(Exception):
    '''An auditor may raise this exception when the current create or set
    operation should be stopped.

    It is up to the specific interface invoking the create or set to
    handle this exception sanely. For example:

    - mailgw will trap and ignore Reject for file attachments and messages
    - cgi will trap and present the exception in a nice format
    '''
    pass

# vim: set filetype=python ts=4 sw=4 et si
