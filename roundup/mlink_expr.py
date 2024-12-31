#
# Copyright: 2010 Intevation GmbH.
#            2021 Ralf Schlatterbeck, rsc@runtux.com.
#

# This module is Free Software under the Roundup licensing,
# see the COPYING.txt file coming with Roundup.
#

from roundup.exceptions import RoundupException
from roundup.i18n import _

opcode_names = {
    -2: "not",
    -3: "and",
    -4: "or",
}


class ExpressionError(RoundupException):
    """Takes two arguments.

        ExpressionError(template, context={})

    The repr of ExpressionError is:

        template % context

    """

    # only works on python 3
    #def __init__(self, *args, context=None):
    #    super().__init__(*args)
    #    self.context = context if isinstance(context, dict) else {}

    # works python 2 and 3
    def __init__(self, *args, **kwargs):
        super(RoundupException, self).__init__(*args)
        self.context = {}
        if 'context' in kwargs and isinstance(kwargs['context'], dict):
            self.context = kwargs['context']

        # Skip testing for a bad call to ExpressionError
        # keywords = [x for x in list(kwargs) if x != "context"]
        #if len(keywords) != 0:
        #        raise ValueError("unknown keyword argument(s) passed to ExpressionError: %s" % keywords)

    def __str__(self):
        try:
            return self.args[0] % self.context
        except KeyError:
            return "%s: context=%s" % (self.args[0], self.context)

    def __repr__(self):
        try:
            return self.args[0] % self.context
        except KeyError:
            return "%s: context=%s" % (self.args[0], self.context)


class Binary:

    def __init__(self, x, y):
        self.x = x
        self.y = y

    def visit(self, visitor):
        self.x.visit(visitor)
        self.y.visit(visitor)


class Unary:

    def __init__(self, x):
        self.x = x

    def generate(self, atom):
        return atom(self)

    def visit(self, visitor):
        self.x.visit(visitor)


class Equals(Unary):

    def evaluate(self, v):
        return self.x in v

    def visit(self, visitor):
        visitor(self)

    def __repr__(self):
        return "Value %s" % self.x


class Empty(Unary):

    def evaluate(self, v):
        return not v

    def visit(self, visitor):
        visitor(self)

    def __repr__(self):
        return "ISEMPTY(-1)"


class Not(Unary):

    def evaluate(self, v):
        return not self.x.evaluate(v)

    def generate(self, atom):
        return "NOT(%s)" % self.x.generate(atom)

    def __repr__(self):
        return "NOT(%s)" % self.x


class Or(Binary):

    def evaluate(self, v):
        return self.x.evaluate(v) or self.y.evaluate(v)

    def generate(self, atom):
        return "(%s)OR(%s)" % (
            self.x.generate(atom),
            self.y.generate(atom))

    def __repr__(self):
        return "(%s OR %s)" % (self.y, self.x)


class And(Binary):

    def evaluate(self, v):
        return self.x.evaluate(v) and self.y.evaluate(v)

    def generate(self, atom):
        return "(%s)AND(%s)" % (
            self.x.generate(atom),
            self.y.generate(atom))

    def __repr__(self):
        return "(%s AND %s)" % (self.y, self.x)


def compile_expression(opcodes):

    stack = []
    push, pop = stack.append, stack.pop
    try:
        for position, opcode in enumerate(opcodes):     # noqa: B007
            if   opcode == -1: push(Empty(opcode))      # noqa: E271,E701
            elif opcode == -2: push(Not(pop()))         # noqa: E701
            elif opcode == -3: push(And(pop(), pop()))  # noqa: E701
            elif opcode == -4: push(Or(pop(), pop()))   # noqa: E701
            else:              push(Equals(opcode))     # noqa: E701
    except IndexError:
        raise ExpressionError(
            _("There was an error searching %(class)s by %(attr)s using: "
              "%(opcodes)s. "
              "The operator %(opcode)s (%(opcodename)s) at position "
              "%(position)d has too few arguments."),
            context={
                "opcode": opcode,
                "opcodename": opcode_names[opcode],
                "position": position + 1,
                "opcodes": opcodes,
            })
    if len(stack) != 1:
        # Too many arguments - I don't think stack can be zero length
        raise ExpressionError(
            _("There was an error searching %(class)s by %(attr)s using: "
              "%(opcodes)s. "
              "There are too many arguments for the existing operators. The "
              "values on the stack are: %(stack)s"),
            context={
                "opcodes": opcodes,
                "stack": stack,
            })

    return pop()


class Expression:

    def __init__(self, v, is_link=False):
        try:
            opcodes = [int(x) for x in v]
            if min(opcodes) >= -1:
                raise ValueError()

            compiled = compile_expression(opcodes)
            if is_link:
                self.evaluate = lambda x: compiled.evaluate(
                    (x and [int(x)]) or [])
            else:
                self.evaluate = lambda x: compiled.evaluate([int(y) for y in x])
        except (ValueError, TypeError):
            if is_link:
                v = [None if x == '-1' else x for x in v]
                self.evaluate = lambda x: x in v
            elif '-1' in v:
                v = [x for x in v if int(x) > 0]
                self.evaluate = lambda x: bool(set(x) & set(v)) or not x
            else:
                self.evaluate = lambda x: bool(set(x) & set(v))
        except BaseException:
            raise
