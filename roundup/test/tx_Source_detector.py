#
# Example output when the web interface changes item 3 and the email
# (non pgp) interface changes item 4:
#
# tx_SourceCheckAudit(3) pre db.tx_Source: cgi
# tx_SourceCheckAudit(4) pre db.tx_Source: email
# tx_SourceCheckAudit(3) post db.tx_Source: cgi
# tx_SourceCheckAudit(4) post db.tx_Source: email
# tx_SourceCheckReact(4) pre db.tx_Source: email
# tx_SourceCheckReact(4) post db.tx_Source: email
# tx_SourceCheckReact(3) pre db.tx_Source: cgi
# tx_SourceCheckReact(3) post db.tx_Source: cgi
#
# Note that the calls are interleaved, but the proper
# tx_Source is associated with the same ticket.

from __future__ import print_function
import time as time

def tx_SourceCheckAudit(db, cl, nodeid, newvalues):
    ''' An auditor to print the value of the source of the
        transaction that trigger this change. The sleep call
        is used to delay the transaction so that multiple changes will
        overlap. The expected output from this detector are 2 lines
        with the same value for tx_Source. Tx source is:
          None - Reported when using a script or it is an error if
                 the change arrives by another method.
          "cli" - reported when using roundup-admin
          "web" - reported when using html based web pages
          "rest" - reported when using the /rest web API
          "xmlrpc" - reported when using the /xmlrpc web API
          "email" - reported when using an unautheticated email based technique
          "email-sig-openpgp" - reported when email with a valid pgp
                                signature is used
    '''
    if __debug__ and False:
        print("\n  tx_SourceCheckAudit(%s) db.tx_Source: %s"%(nodeid, db.tx_Source))

    newvalues['tx_Source'] = db.tx_Source

    # example use for real to prevent a change from happening if it's
    # submited via email
    #
    # if db.tx_Source == "email":
    #    raise Reject, 'Change not allowed via email'

def tx_SourceCheckReact(db, cl, nodeid, oldvalues):
    ''' An reactor to print the value of the source of the
        transaction that trigger this change. The sleep call
        is used to delay the transaction so that multiple changes will
        overlap. The expected output from this detector are 2 lines
        with the same value for tx_Source. Tx source is:
          None - Reported when using a script or it is an error if
                 the change arrives by another method.
          "cli" - reported when using roundup-admin
          "web" - reported when using html based web pages
          "rest" - reported when using the /rest web API
          "xmlrpc" - reported when using the /xmlrpc web API
          "email" - reported when using an unautheticated email based technique
          "email-sig-openpgp" - reported when email with a valid pgp
                                signature is used
    '''

    if __debug__ and False:
        print("  tx_SourceCheckReact(%s) db.tx_Source: %s"%(nodeid, db.tx_Source))



def init(db):
    db.issue.audit('create', tx_SourceCheckAudit)
    db.issue.audit('set', tx_SourceCheckAudit)

    db.issue.react('set', tx_SourceCheckReact)
    db.issue.react('create', tx_SourceCheckReact)

    db.msg.audit('create', tx_SourceCheckAudit)
