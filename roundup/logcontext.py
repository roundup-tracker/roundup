"""Generate and store thread local logging context including unique
trace id for request, request source etc. to be logged.

Trace id generator can use nanoid or uuid.uuid4 stdlib function.
Nanoid is preferred if nanoid is installed using pip. Nanoid is
faster and generates a shorter id.

If nanoid is installed in the tracker's lib subdirectory, it must be
enabled using the tracker's interfaces.py by adding::

   # if nanoid is installed in the tracker's lib directory and
   # if you want to change the length of the nanoid from 12
   # to 14 chars use:
   from functools import partial
   from nanoid import generate
   import roundup.logcontext
   # change 14 to 12 to get the default nanoid size.
   roundup.logcontext.idgen=partial(generate, size=14)

   # If nanoid is instanned and you want to use use the shortened uuid
   # add this to interfaces.py::
   import roundup.logcontext
   roundup.logcontext.idgen=roundup.logcontext.short_uuid

If you are wrapping a staticmethod, you need to include staticmethod
before the calls to gen_trace_id or store_trace_reason when wrapping a
static method. If you don't the static method gets the self argument
prepended which breaks the call. For example to wrap the 'serve'
staticmethod from WhiteNoise::

    WhiteNoise.serve = staticmethod(store_trace_reason(
             extract="'whitenoise ' + args[1]['REQUEST_URI']")(
             gen_trace_id()(WhiteNoise.serve)))

"""
import contextvars
import functools
import logging
import os
import uuid
from typing import Callable


def short_uuid() -> str:
    """Encode a UUID integer in a shorter form for display.

       A uuid is long. Make a shorter version that takes less room
       in a log line and is easier to store.
    """
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz1234567890"
    result = ""
    alphabet_len = len(alphabet)
    uuid_int = uuid.uuid4().int
    while uuid_int:
        uuid_int, t = divmod(uuid_int, alphabet_len)
        result += alphabet[t]
    return result or "0"


try:
    from nanoid import generate
    # With size=12 and the normal alphabet, it take ~4 months
    # with 1000 nanoid's/sec to generate a collision with 1%
    # probability. That's 100 users sec continously. These id's
    # are used to link logging messages/traces that are all done
    # in a few seconds. Collisions are unlikely to happen in the
    # same time period leading to confusion.
    #
    # nanoid is faster than shortened uuids.
    # 1,000,000 generate(size=12) timeit.timeit at 25.4 seconds
    # 1,000,000 generate(size=21) timeit.timeit at 33.7 seconds

    #: Variable used for setting the id generator.
    idgen: Callable = functools.partial(generate, size=12)
except ImportError:
    # 1,000,000 of short_uuid() timeit.timeit at 54.1 seconds
    idgen = short_uuid  #: :meta hide-value:


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
ctx_vars: dict[str, contextvars.ContextVar] = {}

# set up sentinel values that will print a suitable error value
# and the context vars they are associated with.
_SENTINEL_PROCESSNAME = SimpleSentinel("processName", None)
ctx_vars['processName'] = contextvars.ContextVar("processName",
                                                  default=_SENTINEL_PROCESSNAME)


_SENTINEL_ID = SimpleSentinel("trace_id", "not set")
ctx_vars['trace_id'] = contextvars.ContextVar("trace_id", default=_SENTINEL_ID)


_SENTINEL_REASON = SimpleSentinel("trace_reason", "missing")
ctx_vars['trace_reason'] = contextvars.ContextVar("trace_reason",
                                                  default=_SENTINEL_REASON)


def gen_trace_id() -> Callable:
    """Decorator to generate a trace id (nanoid or encoded uuid4) as contextvar

       The logging routine uses this to label every log line. All
       logs with the same trace_id should be generated from a
       single request.

       This decorator is applied to an entry point for a request.
       Different methods of invoking Roundup have different entry
       points. As a result, this decorator can be called multiple
       times as some entry points can traverse another entry point
       used by a different invocation method. It will not set a
       trace_id if one is already assigned.

       If a uuid4() is used as the id, the uuid4 integer is encoded
       into a 62 character alphabet (A-Za-z0-9) to shorten
       the log line.

       This decorator may produce duplicate (colliding) trace_id's
       when used with multiple processes on some platforms where
       uuid.uuid4().is_safe is unknown. Probability of a collision
       is unknown.

       If nanoid is used to generate the id, it is 12 chars long and
       uses a 64 char ascii alphabet, the 62 above with '_' and '-'.
       The shorter nanoid has < 1% chance of collision in ~4 months
       when generating 1000 id's per second.

       See the help text for the module to change how the id is
       generated.
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            prev = None
            trace_id = ctx_vars['trace_id']
            if trace_id.get() is _SENTINEL_ID:
                prev = trace_id.set(idgen())
            try:
                r = func(*args, **kwargs)
            finally:
                if prev:
                    trace_id.reset(prev)
            return r
        return wrapper
    return decorator


def set_processName(name):
    """Decorator to set the processName used in the LogRecord
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            prev = None
            processName = ctx_vars['processName']
            if processName.get() is _SENTINEL_PROCESSNAME:
                prev = processName.set(name)
            try:
                r = func(*args, **kwargs)
            finally:
                if prev:
                    processName.reset(prev)
            return r
        return wrapper
    return decorator


def store_trace_reason(location="unset", extract=None):
    """Decorator finds and stores a reason trace was started in contextvar.

       Record the url path for a regular web triggered request.
       Record the message id for an email triggered request.
       Record a roundup-admin command/action for roundup-admin request.

       (*) There are multiple entry points to the code. Some entry
       points call through other entry points. As a result this can be
       called multiple times in one request.  Because the reason can
       be stored from multiple locations depending on where this is
       called, it is called with a location hint to identify the
       caller (faster than looking up the stack).

       If a reason has already been stored (and it's not "missing", it
       tries to extract it again and verifies it's the same as the
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

            if extract:
                try:
                    reason = eval(extract,
                                  {"__builtin__": {}},
                                  {"args": args, "kwargs": kwargs})

                except (IndexError, KeyError, TypeError) as e:
                    # extract usually looks something like:
                    #      "args[1]['PATH_INFO']"
                    # report bad index/key/type
                    logger.error(
                        "Eval of extract('%(extract)s')@%(loc)s caused %(e)s" %
                        {"e": repr(e), "extract": extract, "loc": location}
                    )

                    # provide fallback hinting that it is an error
                    reason = "error@call_location:%s" % location

            else:
                # if no extract, use location as reason
                # e.g. file://some_roundup-script
                reason = location

            if reason is None:
                pass
            elif stored_reason is _SENTINEL_REASON:
                # no value stored and reason is not none, update
                prev_trace_reason = trace_reason.set(reason)
            elif reason != stored_reason:   # SANITY CHECK
                # Throw an error we have mismatched REASON's which
                # should never happen. It can happen if multiple
                # functions are decorated and they don't agree on
                # what the reason should be. see (*) above.
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
    """Return dict of context var tuples {"var_name": "var_value", ...}"""
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
