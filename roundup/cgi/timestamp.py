'''Set of functions of adding/checking timestamp to be used to limit
   form submission for cgi actions.
'''

import time, struct, binascii, base64
from roundup.cgi.exceptions import FormError
from roundup.i18n import _
from roundup.anypy.strings import b2s, s2b


def pack_timestamp():
    return b2s(base64.b64encode(struct.pack("i", int(time.time()))).strip())


def unpack_timestamp(s):
    try:
        timestamp = struct.unpack("i", base64.b64decode(s2b(s)))[0]
    except (struct.error, binascii.Error, TypeError):
        raise FormError(_("Form is corrupted."))
    return timestamp


class Timestamped:
    def timecheck(self, field, delay):
        try:
            created = unpack_timestamp(self.form[field].value)
        except KeyError:
            raise FormError(_("Form is corrupted, missing: %s." % field))
        if time.time() - created < delay:
            raise FormError(_("Responding to form too quickly."))
        return True
