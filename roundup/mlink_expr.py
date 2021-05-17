#
# Copyright: 2010 Intevation GmbH.
#            2021 Ralf Schlatterbeck, rsc@runtux.com.
# 

# This module is Free Software under the Roundup licensing,
# see the COPYING.txt file coming with Roundup.
#

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

class Empty(Unary):

    def evaluate(self, v):
        return not v

    def visit(self, visitor):
        visitor(self)

class Not(Unary):

    def evaluate(self, v):
        return not self.x.evaluate(v)

    def generate(self, atom):
        return "NOT(%s)" % self.x.generate(atom)

class Or(Binary):

    def evaluate(self, v):
        return self.x.evaluate(v) or self.y.evaluate(v)

    def generate(self, atom):
        return "(%s)OR(%s)" % (
            self.x.generate(atom),
            self.y.generate(atom))

class And(Binary):

    def evaluate(self, v):
        return self.x.evaluate(v) and self.y.evaluate(v)

    def generate(self, atom):
        return "(%s)AND(%s)" % (
            self.x.generate(atom),
            self.y.generate(atom))

def compile_expression(opcodes):

    stack = []
    push, pop = stack.append, stack.pop
    for opcode in opcodes:
        if   opcode == -1: push(Empty(opcode))
        elif opcode == -2: push(Not(pop()))
        elif opcode == -3: push(And(pop(), pop()))
        elif opcode == -4: push(Or(pop(), pop()))
        else:              push(Equals(opcode))

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
                    x and [int(x)] or [])
            else:
                self.evaluate = lambda x: compiled.evaluate([int(y) for y in x])
        except:
            if is_link:
                v = [None if x == '-1' else x for x in v]
                self.evaluate = lambda x: x in v
            elif '-1' in v:
                v = [x for x in v if int(x) > 0]
                self.evaluate = lambda x: bool(set(x) & set(v)) or not x
            else:
                self.evaluate = lambda x: bool(set(x) & set(v))
