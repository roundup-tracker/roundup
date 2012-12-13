import time, struct, base64
from roundup.cgi.actions import RegisterAction
from roundup.cgi.exceptions import *

def timestamp():
    return base64.encodestring(struct.pack("i", time.time())).strip()

def unpack_timestamp(s):
    return struct.unpack("i",base64.decodestring(s))[0]

class Timestamped:
    def check(self):
        try:
            created = unpack_timestamp(self.form['opaque'].value)
        except KeyError:
            raise FormError, "somebody tampered with the form"
        if time.time() - created < 4:
            raise FormError, "responding to the form too quickly"
        return True

class TimestampedRegister(Timestamped, RegisterAction):
    def permission(self):
        self.check()
        RegisterAction.permission(self)

def init(instance):
    instance.registerUtil('timestamp', timestamp)
    instance.registerAction('register', TimestampedRegister)
