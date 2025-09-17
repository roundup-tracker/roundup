import contextvars
import functools
import logging
import os
import uuid

logger = logging.getLogger("roundup.logcontext")


class SimpleSentinel:
    """A hack to get a sentinel value where I can define __str__().

       I was using sentinel = object(). However some code paths
       resulted in the sentinel object showing up as an argument
       to print or logging.warning|error|debug(...). In this case
       seeing "<class 'object'>" in the output isn't useful.

       So I created this class (with slots) as a fast method where
       I could control the __str__ representation.

    """
    __slots__ = ("name", "str")

    def __init__(self, name=None, str_value=""):
        self.name = name
        self.str = str_value

    def __str__(self):
        # Generate a string without whitespace.
        # Used in logging where whitespace could be
        # a field delimiter
        return ("%s%s" % (
            self.name + "-" if self.name else "",
            self.str)).replace(" ", "_")

    def __repr__(self):
        return 'SimpleSentinel(name=%s, str_value="%s")' % (
            self.name, self.str)


# store the context variable names in a dict. Because
# contactvars.copy_context().items() returns nothing if set has
# not been called on a context var. I need the contextvar names
# even if they have not been set.
ctx_vars = {}

# set up sentinel values that will print a suitable error value
# and the context vars they are associated with.
_SENTINEL_ID = SimpleSentinel("trace_id", "not set")
ctx_vars['trace_id'] = contextvars.ContextVar("trace_id", default=_SENTINEL_ID)


_SENTINEL_REASON = SimpleSentinel("trace_reason", "missing")
ctx_vars['trace_reason'] = contextvars.ContextVar("trace_reason",
                                                  default=_SENTINEL_REASON)


def shorten_int_uuid(uuid):
    """Encode a UUID integer in a shorter form for display.

       A uuid is long. Make a shorter version that takes less room
       in a log line.
    """

    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz1234567890"
    result = ""
    while uuid:
        uuid, t = divmod(uuid, len(alphabet))
        result += alphabet[t]
    return result or "0"


def gen_trace_id():
    """Decorator to generate a trace id (encoded uuid4) and add to contextvar

       The logging routine uses this to label every log line. All
       logs with the same trace_id should be generated from a
       single request.

       This decorator is applied to an entry point for a request.
       Different methods of invoking Roundup have different entry
       points. As a result, this decorator can be called multiple
       times as some entry points can traverse another entry point
       used by a different invocation method. It will not set a
       trace_id if one is already assigned.

       A uuid4() is used as the uuid, but to shorten the log line,
       the uuid4 integer is encoded into a 62 character ascii
       alphabet (A-Za-z0-9).

       This decorator may produce duplicate (colliding) trace_id's
       when used with multiple processes on some platforms where
       uuid.uuid4().is_safe is unknown. Probability of a collision
       is unknown.

    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            prev = None
            trace_id = ctx_vars['trace_id']
            if trace_id.get() is _SENTINEL_ID:
                prev = trace_id.set(shorten_int_uuid(uuid.uuid4().int))
            try:
                r = func(*args, **kwargs)
            finally:
                if prev:
                    trace_id.reset(prev)
            return r
        return wrapper
    return decorator


def store_trace_reason(location=None):
    """Decorator finds and stores a reason trace was started in contextvar.

       Record the url for a regular web triggered request.
       Record the message id for an email triggered request.
       Record a roundup-admin command/action for roundup-admin request.

       Because the reason can be stored in different locations
       depending on where this is called, it is called with a
       location hint to activate the right extraction method.

       If the reason has already been stored (and it's not "missing",
       it tries to extract it again and verifies it's the same as the
       stored reason. If it's not the same it logs an error. This
       safety check may be removed in a future version of Roundup.
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):

            reason = None
            prev_trace_reason = None
            trace_reason = ctx_vars['trace_reason']
            stored_reason = trace_reason.get()

            # Fast return path. Not enabled to make sure SANITY
            # CHECK below runs. If the CHECK fails, we have a a
            # bad internal issue: contextvars shared between
            # threads, roundup modifying reason within a request, ...
            #
            # if stored_reason is not _SENTINEL_REASON:
            #     return func(*args, **kwargs)

            # use location to determine how to extract the reason
            if location == "wsgi" and 'REQUEST_URI' in args[1]:
                reason = args[1]['REQUEST_URI']
            elif location == "client" and 'REQUEST_URI' in args[3]:
                reason = args[3]['REQUEST_URI']
            elif location == "mailgw":
                reason = args[1].get_header('message-id', "no_message_id")
            elif location == "admin":
                try:
                    login = os.getlogin()
                except OSError:
                    login = "--unknown--"
                reason = "roundup-admin(%s): %s" % (login, args[1][:2])
            elif location.startswith("file://"):
                reason = location
            elif location == "client_main" and 'REQUEST_URI' in args[0].env:
                reason = args[0].env['REQUEST_URI']
            elif location == "xmlrpc-server":
                reason = args[0].path

            if reason is None:
                pass
            elif stored_reason is _SENTINEL_REASON:
                # no value stored and reason is not none, update
                prev_trace_reason = trace_reason.set(reason)
            elif reason != stored_reason:   # SANITY CHECK
                # Throw an error we have mismatched REASON's which
                # should never happen.
                logger.error("Mismatched REASON's: stored: %s, new: %s at %s",
                             stored_reason, reason, location)

            try:
                r = func(*args, **kwargs)
            finally:
                # reset context var in case thread is reused for
                # another request.
                if prev_trace_reason:
                    trace_reason.reset(prev_trace_reason)
            return r
        return wrapper
    return decorator


def get_context_info():
    """Return list of context var tuples [(var_name, var_value), ...]"""

    return [(name, ctx.get()) for name, ctx in ctx_vars.items()]


#Is returning a dict for this info more pythonic?
def get_context_dict():
    """Return dict of context var tuples ["var_name": "var_value", ...}"""
    return {name: ctx.get() for name, ctx in ctx_vars.items()}

# Dummy no=op implementation of this module:
#
#def noop_decorator(*args, **kwargs):
#    def decorator(func):
#        return func
#    return decorator
#
#def get_context_info():
#    return [ ("trace_id", "noop_trace_id"),
#             ("trace_reason", "noop_trace_reason") ]
#gen_trace_id = store_trace_reason = noop_decorator
