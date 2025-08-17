#
# Copyright (c) 2001 Bizar Software Pty Ltd (http://www.bizarsoftware.com.au/)
# This module is free software, and you may redistribute it and/or modify
# under the same terms as Python, so long as this copyright message and
# disclaimer are retained in their original form.
#
# IN NO EVENT SHALL BIZAR SOFTWARE PTY LTD BE LIABLE TO ANY PARTY FOR
# DIRECT, INDIRECT, SPECIAL, INCIDENTAL, OR CONSEQUENTIAL DAMAGES ARISING
# OUT OF THE USE OF THIS CODE, EVEN IF THE AUTHOR HAS BEEN ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.
#
# BIZAR SOFTWARE PTY LTD SPECIFICALLY DISCLAIMS ANY WARRANTIES, INCLUDING,
# BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS
# FOR A PARTICULAR PURPOSE.  THE CODE PROVIDED HEREUNDER IS ON AN "AS IS"
# BASIS, AND THERE IS NO OBLIGATION WHATSOEVER TO PROVIDE MAINTENANCE,
# SUPPORT, UPDATES, ENHANCEMENTS, OR MODIFICATIONS.
#

"""Extending hyperdb with types specific to issue-tracking.
"""
__docformat__ = 'restructuredtext'

import base64
import logging
import mimetypes
import time

from email import encoders
from email.header import Header
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.parser import FeedParser
from email.utils import formataddr

import roundup.anypy.random_ as random_

from roundup import date, hyperdb, password
from roundup.anypy.strings import b2s, s2u
from roundup.hyperdb import iter_roles
from roundup.i18n import _, RoundupNullTranslations
from roundup.mailer import Mailer, MessageSendError, nice_sender_header

try:
    import gpg, gpg.core  # noqa: E401
except ImportError:
    gpg = None


class Database(object):

    # remember the journal uid for the current journaltag so that:
    # a. we don't have to look it up every time we need it, and
    # b. if the journaltag disappears during a transaction, we don't barf
    #    (eg. the current user edits their username)
    journal_uid = None

    def __init__(self):
        self.i18n = RoundupNullTranslations()

    def getuid(self):
        """Return the id of the "user" node associated with the user
        that owns this connection to the hyperdatabase."""
        if self.journaltag is None:
            return None
        elif self.journaltag == 'admin':
            # admin user may not exist, but always has ID 1
            return '1'
        else:
            if (self.journal_uid is None or self.journal_uid[0] !=
                    self.journaltag):
                uid = self.user.lookup(self.journaltag)
                self.journal_uid = (self.journaltag, uid)
            return self.journal_uid[1]

    def setCurrentUser(self, username):
        """Set the user that is responsible for current database
        activities.
        """
        self.journaltag = username

    def isCurrentUser(self, username):
        """Check if a given username equals the already active user.
        """
        return self.journaltag == username

    def getUserTimezone(self):
        """Return user timezone defined in 'timezone' property of user class.
        If no such property exists return 0
        """
        userid = self.getuid()
        timezone = None
        try:
            tz = self.user.get(userid, 'timezone')
            date.get_timezone(tz)
            timezone = tz
        except KeyError:
            pass
        # If there is no class 'user' or current user doesn't have timezone
        # property or that property is not set assume he/she lives in
        # the timezone set in the tracker config.
        if timezone is None:
            timezone = self.config['TIMEZONE']
        return timezone

    def confirm_registration(self, otk):
        props = self.getOTKManager().getall(otk)
        for propname, proptype in self.user.getprops().items():
            value = props.get(propname, None)
            if value is None:
                pass
            elif isinstance(proptype, hyperdb.Date):
                props[propname] = date.Date(value)
            elif isinstance(proptype, hyperdb.Interval):
                props[propname] = date.Interval(value)
            elif isinstance(proptype, hyperdb.Password):
                props[propname] = password.Password(encrypted=value,
                                                    config=self.config)

        # tag new user creation with 'admin'
        self.journaltag = 'admin'

        # create the new user
        cl = self.user

        props['roles'] = self.config.NEW_WEB_USER_ROLES
        try:
            # ASSUME:: ValueError raised during create due to key value
            # conflict. I an use message in exception to determine
            # when I should intercept the exception with a more
            # friendly error message. If i18n is used to translate
            # original exception message this will fail and translated
            # text (probably unfriendly) will be used.
            userid = cl.create(**props)
        except ValueError as e:
            username = props['username']
            # Try to make error message less cryptic to the user.
            if str(e) == 'node with key "%s" exists' % username:
                raise ValueError(
                    _("Username '%s' already exists.") % username)
            else:
                raise

            # clear the props from the otk database
        self.getOTKManager().destroy(otk)
        # commit cl.create (and otk changes)
        self.commit()

        return userid

    def log_debug(self, msg, *args, **kwargs):
        """Log a message with level DEBUG."""

        logger = self.get_logger()
        logger.debug(msg, *args, **kwargs)

    def log_info(self, msg, *args, **kwargs):
        """Log a message with level INFO."""

        logger = self.get_logger()
        logger.info(msg, *args, **kwargs)

    def get_logger(self):
        """Return the logger for this database."""

        # Because getting a logger requires acquiring a lock, we want
        # to do it only once.
        if not hasattr(self, '__logger'):
            self.__logger = logging.getLogger('roundup.hyperdb')

        return self.__logger

    def clearCache(self):
        """ Backends may keep a cache.
            It must be cleared at end of commit and rollback methods.
            We allow to register user-defined cache-clearing routines
            that are called by this routine.
        """
        if getattr(self, 'cache_callbacks', None):
            for method, param in self.cache_callbacks:
                method(param)

    def registerClearCacheCallback(self, method, param=None):
        """ Register a callback method for clearing the cache.
            It is called with the given param as the only parameter.
            Even if the parameter is not specified, the method has to
            accept a single parameter.
        """
        if not getattr(self, 'cache_callbacks', None):
            self.cache_callbacks = []
        self.cache_callbacks.append((method, param))


class DetectorError(RuntimeError):
    """ Raised by detectors that want to indicate that something's amiss
    """
    pass


# deviation from spec - was called ItemClass
class IssueClass:
    """This class is intended to be mixed-in with a hyperdb backend
    implementation. The backend should provide a mechanism that
    enforces the title, messages, files, nosy and superseder
    properties:

    - title = hyperdb.String(indexme='yes')
    - messages = hyperdb.Multilink("msg")
    - files = hyperdb.Multilink("file")
    - nosy = hyperdb.Multilink("user")
    - superseder = hyperdb.Multilink(classname)
    """

    # The tuple below does not affect the class definition.
    # It just lists all names of all issue properties
    # marked for message extraction tool.
    #
    # XXX is there better way to get property names into message catalog??
    #
    # Note that this list also includes properties
    # defined in the classic template:
    # assignedto, keyword, priority, status.
    (
        ''"title", ''"messages", ''"files", ''"nosy", ''"superseder",
        ''"assignedto", ''"keyword", ''"priority", ''"status",
        # following properties are common for all hyperdb classes
        # they are listed here to keep things in one place
        ''"actor", ''"activity", ''"creator", ''"creation",
    )

    def _update_properties(self, classname, properties):
        """The newly-created class automatically includes the "messages",
        "files", "nosy", and "superseder" properties.  If the 'properties'
        dictionary attempts to specify any of these properties or a
        "creation", "creator", "activity" or "actor" property, a ValueError
        is raised. This method must be called by __init__.

        """
        if 'title' not in properties:
            properties['title'] = hyperdb.String(indexme='yes')
        if 'messages' not in properties:
            properties['messages'] = hyperdb.Multilink("msg")
        if 'files' not in properties:
            properties['files'] = hyperdb.Multilink("file")
        if 'nosy' not in properties:
            # note: journalling is turned off as it really just wastes
            # space. this behaviour may be overridden in an instance
            properties['nosy'] = hyperdb.Multilink("user", do_journal="no")
        if 'superseder' not in properties:
            properties['superseder'] = hyperdb.Multilink(classname)

    # New methods:
    def addmessage(self, issueid, summary, text):
        """Add a message to an issue's mail spool.

        A new "msg" node is constructed using the current date, the user that
        owns the database connection as the author, and the specified summary
        text.

        The "files" and "recipients" fields are left empty.

        The given text is saved as the body of the message and the node is
        appended to the "messages" field of the specified issue.
        """

    def nosymessage(self, issueid, msgid, oldvalues, whichnosy='nosy',
                    from_address=None, cc=None, bcc=None,
                    cc_emails=None,
                    bcc_emails=None, subject=None,
                    note_filter=None, add_headers=None):
        """Send a message to the members of an issue's nosy list.

        The message is sent only to users on the nosy list who are not
        already on the "recipients" list for the message.

        These users are then added to the message's "recipients" list.

        If 'msgid' is None, the message gets sent only to the nosy
        list, and it's called a 'System Message'.

        The "subject" argument is used as subject for the message. If no
        subject is passed, a subject will be generated from the message.
        Note the subject does not include the item designator [classID]
        prefix that allows proper processing of reply emails. The caller
        needs to include that label in the subject if needed.

        The "cc" argument indicates additional recipients to send the
        message to that may not be specified in the message's recipients
        list.

        The "bcc" argument also indicates additional recipients to send the
        message to that may not be specified in the message's recipients
        list. These recipients will not be included in the To: or Cc:
        address lists. Note that the list of bcc users *is* updated in
        the recipient list of the message, so this field has to be
        protected (using appropriate permissions), otherwise the bcc
        will be deduceable for users who have web access to the tracker.

        The cc_emails and bcc_emails arguments take a list of additional
        recipient email addresses (just the mail address not roundup users)
        this can be useful for sending to additional email addresses
        which are not roundup users. These arguments are currently not
        used by roundups nosyreaction but can be used by customized
        (nosy-)reactors.

        A note on encryption: If pgp encryption for outgoing mails is
        turned on in the configuration and no specific pgp roles are
        defined, we try to send encrypted mail to *all* users
        *including* cc, bcc, cc_emails and bcc_emails and this might
        fail if not all the keys are available in roundups keyring.

        If note_filter is specified it is a function with this
        prototype:
            note_filter(original_note, issueid, newvalues, oldvalues)
        If called, note_filter returns the new value for the message body.

        The add_headers parameter allows to set additional headers for
        the outgoing email.
        """

        if cc is None: cc = []                              # noqa: E701
        if bcc is None: bcc = []                            # noqa: E701
        if cc_emails is None: cc_emails = []                # noqa: E701
        if bcc_emails is None: bcc_emails = []              # noqa: E701
        if add_headers is None: add_headers = {}            # noqa: E701

        encrypt = self.db.config.PGP_ENABLE and self.db.config.PGP_ENCRYPT
        pgproles = self.db.config.PGP_ROLES
        if msgid:
            authid = self.db.msg.get(msgid, 'author')
            recipients = self.db.msg.get(msgid, 'recipients', [])
        else:
            # "system message"
            authid = None
            recipients = []

        sendto = dict(plain=[], crypt=[])
        bcc_sendto = dict(plain=[], crypt=[])
        seen_message = {}
        for recipient in recipients:
            seen_message[recipient] = 1

        def add_recipient(userid, to):
            """ make sure they have an address """
            address = self.db.user.get(userid, 'address')
            if address:
                ciphered = encrypt and (not pgproles or
                                        self.db.user.has_role(
                                            userid, *iter_roles(pgproles)))
                type = ['plain', 'crypt'][ciphered]
                to[type].append(address)
                recipients.append(userid)

        def good_recipient(userid):
            """ Make sure we don't send mail to either the anonymous
                user or a user who has already seen the message.
                Also check permissions on the message if not a system
                message: A user must have view permission on content and
                files to be on the receiver list. We do *not* check the
                author etc. for now.
            """
            allowed = True
            if msgid:
                for prop in 'content', 'files':
                    if prop in self.db.msg.properties:
                        allowed = allowed and self.db.security.hasPermission(
                            'View', userid, 'msg', prop, msgid)
            return (userid and
                    (self.db.user.get(userid, 'username') != 'anonymous') and
                    allowed and userid not in seen_message)

        # possibly send the message to the author, as long as they aren't
        # anonymous
        if (good_recipient(authid) and
            (self.db.config.MESSAGES_TO_AUTHOR == 'yes' or
             (self.db.config.MESSAGES_TO_AUTHOR == 'new' and not oldvalues) or
             (self.db.config.MESSAGES_TO_AUTHOR == 'nosy' and authid in
              self.get(issueid, whichnosy)))):
            add_recipient(authid, sendto)

        if authid:
            seen_message[authid] = 1

        # now deal with the nosy and cc people who weren't recipients.
        for userid in cc + self.get(issueid, whichnosy):
            if good_recipient(userid):
                add_recipient(userid, sendto)
                seen_message[userid] = 1
        if encrypt and not pgproles:
            sendto['crypt'].extend(cc_emails)
        else:
            sendto['plain'].extend(cc_emails)

        # now deal with bcc people.
        for userid in bcc:
            if good_recipient(userid):
                add_recipient(userid, bcc_sendto)
                seen_message[userid] = 1
        if encrypt and not pgproles:
            bcc_sendto['crypt'].extend(bcc_emails)
        else:
            bcc_sendto['plain'].extend(bcc_emails)

        if oldvalues:
            note = self.generateChangeNote(issueid, oldvalues)
        else:
            note = self.generateCreateNote(issueid)
        if note_filter:
            cn = self.classname
            cl = self.db.classes[cn]
            note = note_filter(note, issueid, self.db, cl, oldvalues)

        # If we have new recipients, update the message's recipients
        # and send the mail.
        if sendto['plain'] or sendto['crypt']:
            # update msgid and recipients only if non-bcc have changed
            if msgid is not None:
                self.db.msg.set(msgid, recipients=recipients)
        if sendto['plain'] or bcc_sendto['plain']:
            self.send_message(issueid, msgid, note, sendto['plain'],
                              from_address, bcc_sendto['plain'],
                              subject, add_headers=add_headers)
        if sendto['crypt'] or bcc_sendto['crypt']:
            self.send_message(issueid, msgid, note, sendto['crypt'],
                              from_address, bcc_sendto['crypt'], subject,
                              crypt=True, add_headers=add_headers)

    # backwards compatibility - don't remove
    sendmessage = nosymessage

    def encrypt_to(self, message, sendto):
        """ Encrypt given message to sendto receivers.
            Returns a new RFC 3156 conforming message.
        """
        plain = gpg.core.Data(message.as_string())
        cipher = gpg.core.Data()
        ctx = gpg.core.Context()
        ctx.set_armor(1)
        keys = []
        for adr in sendto:
            ctx.op_keylist_start(adr, 0)
            # only first key per email
            k = ctx.op_keylist_next()
            if k is not None:
                keys.append(k)
            else:
                msg = _('No key for "%(adr)s" in keyring') % locals()
                raise MessageSendError(msg)
            ctx.op_keylist_end()
        ctx.op_encrypt(keys, 1, plain, cipher)
        cipher.seek(0, 0)
        msg = MIMEMultipart('encrypted', boundary=None, _subparts=None,
                            protocol="application/pgp-encrypted")
        part = MIMEBase('application', 'pgp-encrypted')
        part.set_payload("Version: 1\r\n")
        msg.attach(part)
        part = MIMEBase('application', 'octet-stream')
        part.set_payload(cipher.read())
        msg.attach(part)
        return msg

    def send_message(self, issueid, msgid, note, sendto, from_address=None,
                     bcc_sendto=None, subject=None, crypt=False,
                     add_headers=None, authid=None):
        '''Actually send the nominated message from this issue to the sendto
           recipients, with the note appended. It's possible to add
           headers to the message with the add_headers variable.
        '''

        if bcc_sendto is None: bcc_sendto = []            # noqa: E701
        if add_headers is None: add_headers = {}          # noqa: E701
        users = self.db.user
        messages = self.db.msg
        files = self.db.file

        if msgid is None:
            inreplyto = None
            messageid = None
        else:
            inreplyto = messages.get(msgid, 'inreplyto')
            messageid = messages.get(msgid, 'messageid')

        # make up a messageid if there isn't one (web edit)
        if not messageid:
            # this is an old message that didn't get a messageid, so
            # create one
            messageid = "<%s.%s.%s%s@%s>" % (
                time.time(),
                b2s(base64.b32encode(random_.token_bytes(10))),
                self.classname, issueid, self.db.config['MAIL_DOMAIN'])
            if msgid is not None:
                messages.set(msgid, messageid=messageid)

        # compose title
        cn = self.classname
        title = self.get(issueid, 'title') or '%s message copy' % cn

        # figure author information
        if authid:
            pass
        elif msgid:
            authid = messages.get(msgid, 'author')
        else:
            authid = self.db.getuid()
        authname = users.get(authid, 'realname')
        if not authname:
            authname = users.get(authid, 'username', '')
        authaddr = users.get(authid, 'address', '')

        if authaddr and self.db.config.MAIL_ADD_AUTHOREMAIL:
            authaddr = " <%s>" % formataddr(('', authaddr))
        elif authaddr:
            authaddr = ""

        # make the message body
        m = ['']

        # put in roundup's signature
        if self.db.config.EMAIL_SIGNATURE_POSITION == 'top':
            m.append(self.email_signature(issueid, msgid))

        # add author information
        if authid and self.db.config.MAIL_ADD_AUTHORINFO:
            if msgid and len(self.get(issueid, 'messages')) == 1:
                m.append(_("New submission from %(authname)s%(authaddr)s:")
                         % locals())
            elif msgid:
                m.append(_("%(authname)s%(authaddr)s added the comment:")
                         % locals())
            else:
                m.append(_("Change by %(authname)s%(authaddr)s:") % locals())
            m.append('')

        # add the content
        if msgid is not None:
            m.append(messages.get(msgid, 'content', ''))

        # get the files for this message
        message_files = []
        if msgid:
            for fileid in messages.get(msgid, 'files'):
                # check the attachment size
                filesize = self.db.filesize('file', fileid, None)
                if filesize <= self.db.config.NOSY_MAX_ATTACHMENT_SIZE:
                    message_files.append(fileid)
                else:
                    base = self.db.config.TRACKER_WEB
                    link = "".join((base, files.classname, fileid))
                    filename = files.get(fileid, 'name')
                    m.append(_("File '%(filename)s' not attached - "
                               "you can download it from %(link)s.") %
                             locals())

        # add the change note
        if note:
            m.append(note)

        # put in roundup's signature
        if self.db.config.EMAIL_SIGNATURE_POSITION == 'bottom':
            m.append(self.email_signature(issueid, msgid))

        # figure the encoding
        charset = getattr(self.db.config, 'EMAIL_CHARSET', 'utf-8')

        # construct the content and convert to unicode object
        body = s2u('\n'.join(m))

        # make sure the To line is always the same (for testing mostly)
        sendto.sort()

        # make sure we have a from address
        if from_address is None:
            from_address = self.db.config.TRACKER_EMAIL

        # additional bit for after the From: "name"
        from_tag = getattr(self.db.config, 'EMAIL_FROM_TAG', '')
        if from_tag:
            from_tag = ' ' + from_tag

        if subject is None:
            subject = '[%s%s] %s' % (cn, issueid, title)

        author = (authname + from_tag, from_address)

        # send an individual message per recipient?
        if self.db.config.NOSY_EMAIL_SENDING != 'single':
            sendto = [[address] for address in sendto]
        else:
            sendto = [sendto]

        # tracker sender info
        tracker_name = s2u(self.db.config.TRACKER_NAME)
        tracker_name = nice_sender_header(tracker_name, from_address,
                                          charset)

        # now send one or more messages
        # TODO: I believe we have to create a new message each time as we
        # can't fiddle the recipients in the message ... worth testing
        # and/or fixing some day
        first = True
        for to_addr in sendto:
            # create the message
            mailer = Mailer(self.db.config)

            message = mailer.get_standard_message(multipart=message_files)

            # set reply-to as requested by config option
            # TRACKER_REPLYTO_ADDRESS
            replyto_config = self.db.config.TRACKER_REPLYTO_ADDRESS
            if replyto_config:
                if replyto_config == "AUTHOR":
                    # note that authaddr at this point is already
                    # surrounded by < >, so get the original address
                    # from the db as nice_send_header adds < >
                    replyto_addr = nice_sender_header(
                        authname,
                        users.get(authid, 'address', ''),
                        charset)
                else:
                    replyto_addr = replyto_config
            else:
                replyto_addr = tracker_name
            message['Reply-To'] = replyto_addr

            # message ids
            if messageid:
                message['Message-Id'] = messageid
            if inreplyto:
                message['In-Reply-To'] = inreplyto

            # Generate a header for each link or multilink to
            # a class that has a name attribute
            for propname, prop in self.getprops().items():
                if not isinstance(prop, (hyperdb.Link, hyperdb.Multilink)):
                    continue
                cl = self.db.getclass(prop.classname)
                label = None
                if 'name' in cl.getprops():
                    label = 'name'
                if prop.msg_header_property in cl.getprops():
                    label = prop.msg_header_property
                if prop.msg_header_property == "":
                    # if msg_header_property is set to empty string
                    # suppress the header entirely. You can't use
                    # 'msg_header_property == None'. None is the
                    # default value.
                    label = None
                if not label:
                    continue
                if isinstance(prop, hyperdb.Link):
                    value = self.get(issueid, propname)
                    if value is None:
                        continue
                    values = [value]
                else:
                    values = self.get(issueid, propname)
                    if not values:
                        continue
                values = [cl.get(v, label) for v in values]
                values = ', '.join(values)
                header = "X-Roundup-%s-%s" % (self.classname, propname)
                try:
                    values.encode('ascii')
                    message[header] = values
                except UnicodeError:
                    message[header] = Header(values, charset)

            # Add header for main id number to make filtering
            # email easier than extracting from subject line.
            header = "X-Roundup-%s-Id" % (self.classname)
            values = issueid
            try:
                values.encode('ascii')
                message[header] = values
            except UnicodeError:
                message[header] = Header(values, charset)
            # Generate additional headers
            for k in add_headers:
                v = add_headers[k]
                try:
                    v.encode('ascii')
                    message[k] = v
                except UnicodeError:
                    message[k] = Header(v, charset)

            if not inreplyto:
                # Default the reply to the first message
                msgs = self.get(issueid, 'messages')
                # Assume messages are sorted by increasing message number here
                # If the issue is just being created, and the submitter didn't
                # provide a message, then msgs will be empty.
                if msgs and msgs[0] != msgid:
                    inreplyto = messages.get(msgs[0], 'messageid')
                    if inreplyto:
                        message['In-Reply-To'] = inreplyto

            # attach files
            if message_files:
                # first up the text as a part
                part = mailer.get_standard_message()
                part.set_payload(body, part.get_charset())
                message.attach(part)

                for fileid in message_files:
                    name = files.get(fileid, 'name')
                    mime_type = (files.get(fileid, 'type') or
                                 mimetypes.guess_type(name)[0] or
                                 'application/octet-stream')
                    if mime_type == 'text/plain':
                        content = files.get(fileid, 'content')
                        part = MIMEText('')
                        del part['Content-Transfer-Encoding']
                        try:
                            enc = content.encode('ascii')
                            part = mailer.get_text_message('us-ascii')
                            part.set_payload(enc)
                        except UnicodeError:
                            # the content cannot be 7bit-encoded.
                            # use quoted printable
                            # XXX stuffed if we know the charset though :(
                            part = mailer.get_text_message('utf-8')
                            part.set_payload(content, part.get_charset())
                    elif mime_type == 'message/rfc822':
                        content = files.get(fileid, 'content')
                        main, sub = mime_type.split('/')
                        p = FeedParser()
                        p.feed(content)
                        part = MIMEBase(main, sub)
                        part.set_payload([p.close()])
                    else:
                        # some other type, so encode it
                        content = files.get(fileid, 'binary_content')
                        main, sub = mime_type.split('/')
                        part = MIMEBase(main, sub)
                        part.set_payload(content)
                        encoders.encode_base64(part)
                    cd = 'Content-Disposition'
                    part[cd] = 'attachment;\n filename="%s"' % name
                    message.attach(part)

            else:
                message.set_payload(body, message.get_charset())

            if crypt:
                send_msg = self.encrypt_to(message, to_addr)
            else:
                send_msg = message
            mailer.set_message_attributes(send_msg, to_addr, subject, author)
            if crypt:
                send_msg['Message-Id'] = message['Message-Id']
                send_msg['Reply-To'] = message['Reply-To']
                if message.get('In-Reply-To'):
                    send_msg['In-Reply-To'] = message['In-Reply-To']

            if to_addr:
                mailer.smtp_send(to_addr, send_msg.as_string())
            if first:
                if crypt:
                    # send individual bcc mails, otherwise receivers can
                    # deduce bcc recipients from keys in message
                    for bcc in bcc_sendto:
                        send_msg = self.encrypt_to(message, [bcc])
                        send_msg['Message-Id'] = message['Message-Id']
                        send_msg['Reply-To'] = message['Reply-To']
                        if message.get('In-Reply-To'):
                            send_msg['In-Reply-To'] = message['In-Reply-To']
                        mailer.smtp_send([bcc], send_msg.as_string())
                elif bcc_sendto:
                    mailer.smtp_send(bcc_sendto, send_msg.as_string())
            first = False

    def email_signature(self, issueid, msgid):
        ''' Add a signature to the e-mail with some useful information
        '''
        # simplistic check to see if the url is valid,
        # then append a trailing slash if it is missing
        base = self.db.config.TRACKER_WEB
        if (not isinstance(base, type('')) or
                not (base.startswith('http://') or
                     base.startswith('https://'))):
            web = "Configuration Error: TRACKER_WEB isn't a " \
                "fully-qualified URL"
        else:
            if not base.endswith('/'):
                base = base + '/'
            web = base + self.classname + issueid

        # ensure the email address is properly quoted
        email = formataddr((self.db.config.TRACKER_NAME,
                            self.db.config.TRACKER_EMAIL))

        line = '_' * max(len(web)+2, len(email))
        return '\n%s\n%s\n<%s>\n%s' % (line, email, web, line)

    def generateCreateNote(self, issueid):
        """Generate a create note that lists initial property values
        """
        cn = self.classname
        cl = self.db.classes[cn]
        props = cl.getprops(protected=0)

        # list the values
        m = []
        prop_items = sorted(props.items())
        for propname, prop in prop_items:
            # Omit quiet properties from history/changelog
            if prop.quiet:
                continue
            value = cl.get(issueid, propname, None)
            # skip boring entries
            if not value:
                continue
            if isinstance(prop, hyperdb.Link):
                link = self.db.classes[prop.classname]
                key = link.labelprop(default_to_id=1)
                if key:
                    value = link.get(value, key)
            elif isinstance(prop, hyperdb.Multilink):
                link = self.db.classes[prop.classname]
                key = link.labelprop(default_to_id=1)
                if key:
                    value = [link.get(entry, key) for entry in value]
                value.sort()
                value = ', '.join(value)
            else:
                value = str(value)
                if '\n' in value:
                    value = '\n'+self.indentChangeNoteValue(value)
            m.append('%s: %s' % (propname, value))
        m.insert(0, '----------')
        m.insert(0, '')
        return '\n'.join(m)

    def generateChangeNote(self, issueid, oldvalues):
        """Generate a change note that lists property changes
        """
        if not isinstance(oldvalues, type({})):
            raise TypeError("'oldvalues' must be dict-like, not %s." %
                            type(oldvalues))

        cn = self.classname
        cl = self.db.classes[cn]
        changed = {}
        props = cl.getprops(protected=0)

        # determine what changed
        for key in oldvalues.keys():
            if key in ['files', 'messages']:
                continue
            if key in ('actor', 'activity', 'creator', 'creation'):
                continue
            # not all keys from oldvalues might be available in database
            # this happens when property was deleted
            try:
                new_value = cl.get(issueid, key)
            except KeyError:
                continue
            # the old value might be non existent
            # this happens when property was added
            try:
                old_value = oldvalues[key]
                if isinstance(new_value, type([])):
                    new_value.sort()
                    old_value.sort()
                if new_value != old_value:
                    changed[key] = old_value
            except Exception:
                changed[key] = new_value

        # list the changes
        m = []
        changed_items = sorted(changed.items())
        for propname, oldvalue in changed_items:
            prop = props[propname]
            # Omit quiet properties from history/changelog
            if prop.quiet:
                continue
            value = cl.get(issueid, propname, None)
            if isinstance(prop, hyperdb.Link):
                link = self.db.classes[prop.classname]
                key = link.labelprop(default_to_id=1)
                if key:
                    if value:
                        value = link.get(value, key)
                    else:
                        value = ''
                    if oldvalue:
                        oldvalue = link.get(oldvalue, key)
                    else:
                        oldvalue = ''
                change = '%s -> %s' % (oldvalue, value)
            elif isinstance(prop, hyperdb.Multilink):
                change = ''
                if value is None: value = []                    # noqa: E701
                if oldvalue is None: oldvalue = []              # noqa: E701
                changed_links = []
                link = self.db.classes[prop.classname]
                key = link.labelprop(default_to_id=1)
                # check for additions
                for entry in value:
                    if entry in oldvalue: continue              # noqa: E701
                    if key:
                        changed_links.append(link.get(entry, key))
                    else:
                        changed_links.append(entry)
                if changed_links:
                    changed_links.sort()
                    change = '+%s' % (', '.join(changed_links))
                    changed_links = []
                # check for removals
                for entry in oldvalue:
                    if entry in value: continue                 # noqa: E701
                    if key:
                        changed_links.append(link.get(entry, key))
                    else:
                        changed_links.append(entry)
                if changed_links:
                    changed_links.sort()
                    change += ' -%s' % (', '.join(changed_links))
            else:
                change = '%s -> %s' % (oldvalue, value)
                if '\n' in change:
                    value = self.indentChangeNoteValue(str(value))
                    oldvalue = self.indentChangeNoteValue(str(oldvalue))
                    change = _('\nNow:\n%(new)s\nWas:\n%(old)s') % {
                        "new": value, "old": oldvalue}
            m.append('%s: %s' % (propname, change))
        if m:
            m.insert(0, '----------')
            m.insert(0, '')
        return '\n'.join(m)

    def indentChangeNoteValue(self, text):
        lines = text.rstrip('\n').split('\n')
        lines = ['  '+line for line in lines]
        return '\n'.join(lines)

# vim: set filetype=python sts=4 sw=4 et si :
