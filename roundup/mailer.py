"""Sending Roundup-specific mail over SMTP.
"""
__docformat__ = 'restructuredtext'

import time, os, socket, smtplib, sys, traceback, logging

from roundup import __version__
from roundup.date import get_timezone, Date

from email import charset
from email.utils import formatdate, specialsre, escapesre
from email.charset import Charset
from email.header import Header
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.nonmultipart import MIMENonMultipart

from roundup.anypy import email_
from roundup.anypy.strings import b2s, s2u

try:
    import gpg, gpg.core
except ImportError:
    gpg = None


class MessageSendError(RuntimeError):
    pass


def nice_sender_header(name, address, charset):
    # construct an address header so it's as human-readable as possible
    # even in the presence of a non-ASCII name part
    if not name:
        return address
    try:
        encname = b2s(name.encode('ASCII'))
    except UnicodeEncodeError:
        # use Header to encode correctly.
        encname = Header(name, charset=charset).encode()

    # the important bits of formataddr()
    if specialsre.search(encname):
        encname = '"%s"' % escapesre.sub(r'\\\g<0>', encname)

    # now format the header as a string - don't return a Header as anonymous
    # headers play poorly with Messages (eg. won't get wrapped properly)
    return '%s <%s>' % (encname, address)


class Mailer:
    """Roundup-specific mail sending."""
    def __init__(self, config):
        self.config = config
        self.logger = logging.getLogger('roundup.mailer')

        # set to indicate to roundup not to actually _send_ email
        # this var must contain a file to write the mail to
        self.debug = os.environ.get('SENDMAILDEBUG', '') \
            or config["MAIL_DEBUG"]

        # set timezone so that things like formatdate(localtime=True)
        # use the configured timezone
        # apparently tzset doesn't exist in python under Windows, my bad.
        # my pathetic attempts at googling a Windows-solution failed
        # so if you're on Windows your mail won't use your configured
        # timezone.
        if hasattr(time, 'tzset'):
            os.environ['TZ'] = get_timezone(self.config.TIMEZONE).tzname(None)
            time.tzset()

    def set_message_attributes(self, message, to, subject, author=None):
        ''' Add attributes to a standard output message
        "to"      - recipients list
        "subject" - Subject
        "author"  - (name, address) tuple or None for admin email

        Subject and author are encoded using the EMAIL_CHARSET from the
        config (default UTF-8).
        '''
        # encode header values if they need to be
        charset = getattr(self.config, 'EMAIL_CHARSET', 'utf-8')
        tracker_name = s2u(self.config.TRACKER_NAME)
        if not author:
            author = (tracker_name, self.config.ADMIN_EMAIL)
            name = author[0]
        else:
            name = s2u(author[0])
        author = nice_sender_header(name, author[1], charset)
        try:
            subject.encode('ascii')
            message['Subject'] = subject
        except UnicodeError:
            message['Subject'] = Header(subject, charset)
        message['To'] = ', '.join(to)
        message['From'] = author
        message['Date'] = formatdate(localtime=True)

        # add a Precedence header so autoresponders ignore us
        message['Precedence'] = 'bulk'

        # Add a unique Roundup header to help filtering
        try:
            tracker_name.encode('ascii')
            message['X-Roundup-Name'] = tracker_name
        except UnicodeError:
            message['X-Roundup-Name'] = Header(tracker_name, charset)

        # and another one to avoid loops
        message['X-Roundup-Loop'] = 'hello'
        # finally, an aid to debugging problems
        message['X-Roundup-Version'] = __version__

    def get_text_message(self, _charset='utf-8', _subtype='plain'):
        message = MIMENonMultipart('text', _subtype)
        cs = Charset(_charset)
        if cs.body_encoding == charset.BASE64:
            cs.body_encoding = charset.QP
        message.set_charset(cs)
        del message['Content-Transfer-Encoding']
        return message

    def get_standard_message(self, multipart=False):
        '''Form a standard email message from Roundup.
        Returns a Message object.
        '''
        if multipart:
            message = MIMEMultipart()
        else:
            message = self.get_text_message(getattr(self.config,
                                                    'EMAIL_CHARSET', 'utf-8'))

        return message

    def standard_message(self, to, subject, content, author=None):
        """Send a standard message.

        Arguments:
        - to: a list of addresses usable by email.utils.parseaddr().
        - subject: the subject as a string.
        - content: the body of the message as a string.
        - author: the sender as a (name, address) tuple

        All strings are assumed to be UTF-8 encoded.
        """
        charset = getattr(self.config, 'EMAIL_CHARSET', 'utf-8')
        message = self.get_standard_message()
        self.set_message_attributes(message, to, subject, author)
        message.set_payload(s2u(content), charset=charset)
        self.smtp_send(to, message.as_string())

    def bounce_message(self, bounced_message, to, error,
                       subject='Failed issue tracker submission', crypt=False):
        """Bounce a message, attaching the failed submission.

        Arguments:
        - bounced_message: an mailgw.RoundupMessage object.
        - to: a list of addresses usable by email.utils.parseaddr(). Might be
          extended or overridden according to the config
          ERROR_MESSAGES_TO setting.
        - error: the reason of failure as a string.
        - subject: the subject as a string.
        - crypt: require encryption with pgp for user -- applies only to
          mail sent back to the user, not the dispatcher or admin.

        """
        crypt_to = None
        if crypt:
            crypt_to = to
            to = None
        # see whether we should send to the dispatcher or not
        dispatcher_email = getattr(self.config, "DISPATCHER_EMAIL",
                                   getattr(self.config, "ADMIN_EMAIL"))
        error_messages_to = getattr(self.config, "ERROR_MESSAGES_TO", "user")
        if error_messages_to == "dispatcher":
            to = [dispatcher_email]
            crypt = False
            crypt_to = None
        elif error_messages_to == "both":
            if crypt:
                to = [dispatcher_email]
            else:
                to.append(dispatcher_email)

        message = self.get_standard_message(multipart=True)

        # add the error text
        part = MIMEText('\n'.join(error))
        message.attach(part)

        # attach the original message to the returned message
        part = MIMEText(bounced_message.flatten())
        message.attach(part)

        self.logger.debug("bounce_message: to=%s, crypt_to=%s", to, crypt_to)

        if to:
            # send
            self.set_message_attributes(message, to, subject)
            try:
                self.smtp_send(to, message.as_string())
            except MessageSendError as e:
                # squash mail sending errors when bouncing mail
                # TODO this *could* be better, as we could notify admin of the
                # problem (even though the vast majority of bounce errors are
                # because of spam)
                self.logger.debug("MessageSendError: %s", str(e))
                pass
        if crypt_to:
            plain = gpg.core.Data(message.as_string())
            cipher = gpg.core.Data()
            ctx = gpg.core.Context()
            ctx.set_armor(1)
            keys = []
            adrs = []
            for adr in crypt_to:
                ctx.op_keylist_start(adr, 0)
                # only first key per email
                k = ctx.op_keylist_next()
                if k is not None:
                    adrs.append(adr)
                    keys.append(k)
                ctx.op_keylist_end()
            if not adrs:
                self.logger.debug("bounce_message: no keys found for %s",
                                  crypt_to)
            crypt_to = adrs
        if crypt_to:
            try:
                ctx.op_encrypt(keys, 1, plain, cipher)
                cipher.seek(0, 0)
                message = MIMEMultipart('encrypted', boundary=None,
                                        _subparts=None,
                                        protocol="application/pgp-encrypted")
                part = MIMEBase('application', 'pgp-encrypted')
                part.set_payload("Version: 1\r\n")
                message.attach(part)
                part = MIMEBase('application', 'octet-stream')
                part.set_payload(cipher.read())
                message.attach(part)
            except gpg.GPGMEError:
                self.logger.debug("bounce_message: Cannot encrypt to %s",
                                  str(crypt_to))
                crypt_to = None
        if crypt_to:
            self.set_message_attributes(message, crypt_to, subject)
            try:
                self.smtp_send(crypt_to, message.as_string())
            except MessageSendError as e:
                # ignore on error, see above.
                self.logger.debug("MessageSendError: %s", str(e))
                pass

    def exception_message(self):
        '''Send a message to the admins with information about the latest
        traceback.
        '''
        subject = '%s: %s' % (self.config.TRACKER_NAME, sys.exc_info()[1])
        to = [self.config.ADMIN_EMAIL]
        content = '\n'.join(traceback.format_exception(*sys.exc_info()))
        self.standard_message(to, subject, content)

    def smtp_send(self, to, message, sender=None):
        """Send a message over SMTP, using roundup's config.

        Arguments:
        - to: a list of addresses usable by rfc822.parseaddr().
        - message: a StringIO instance with a full message.
        - sender: if not 'None', the email address to use as the
        envelope sender.  If 'None', the admin email is used.
        """

        if not sender:
            sender = self.config.ADMIN_EMAIL
        if self.debug:
            # don't send - just write to a file, use unix from line so
            # that resulting file can be openened in a mailer
            fmt = '%a %b %m %H:%M:%S %Y'
            unixfrm = 'From %s %s' % (sender, Date('.').pretty(fmt))
            open(self.debug, 'a').write('%s\nFROM: %s\nTO: %s\n%s\n\n' %
                                        (unixfrm, sender,
                                         ', '.join(to), message))
        else:
            # now try to send the message
            try:
                # send the message as admin so bounces are sent there
                # instead of to roundup
                smtp = SMTPConnection(self.config)
                smtp.sendmail(sender, to, message)
            except socket.error as value:
                raise MessageSendError("Error: couldn't send email: "
                                       "mailhost %s" % value)
            except smtplib.SMTPException as msg:
                raise MessageSendError("Error: couldn't send email: %s" % msg)


class SMTPConnection(smtplib.SMTP):
    ''' Open an SMTP connection to the mailhost specified in the config
    '''
    def __init__(self, config):
        smtplib.SMTP.__init__(self, config.MAILHOST, port=config['MAIL_PORT'],
                              local_hostname=config['MAIL_LOCAL_HOSTNAME'])

        # start the TLS if requested
        if config["MAIL_TLS"]:
            self.ehlo()
            self.starttls(config["MAIL_TLS_KEYFILE"],
                          config["MAIL_TLS_CERTFILE"])

        # ok, now do we also need to log in?
        mailuser = config["MAIL_USERNAME"]
        if mailuser:
            self.login(mailuser, config["MAIL_PASSWORD"])

# vim: set et sts=4 sw=4 :
