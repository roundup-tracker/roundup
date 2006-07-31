"""Implements various support classes and functions used in a number of
places in Roundup code.
"""

__docformat__ = 'restructuredtext'

import os, time, sys, re

from sets import Set

class TruthDict:
    '''Returns True for valid keys, False for others.
    '''
    def __init__(self, keys):
        if keys:
            self.keys = {}
            for col in keys:
                self.keys[col] = 1
        else:
            self.__getitem__ = lambda name: 1

    def __getitem__(self, name):
        return self.keys.has_key(name)

def ensureParentsExist(dest):
    if not os.path.exists(os.path.dirname(dest)):
        os.makedirs(os.path.dirname(dest))

class PrioList:
    '''Manages a sorted list.

    Currently only implements method 'append' and iteration from a
    full list interface.
    Implementation: We manage a "sorted" status and sort on demand.
    Appending to the list will require re-sorting before use.
    >>> p = PrioList()
    >>> for i in 5,7,1,-1:
    ...  p.append(i)
    ...
    >>> for k in p:
    ...  print k
    ...
    -1
    1
    5
    7

    '''
    def __init__(self):
        self.list   = []
        self.sorted = True

    def append(self, item):
        self.list.append(item)
        self.sorted = False

    def __iter__(self):
        if not self.sorted:
            self.list.sort()
            self.sorted = True
        return iter(self.list)

class Progress:
    '''Progress display for console applications.

    See __main__ block at end of file for sample usage.
    '''
    def __init__(self, info, sequence):
        self.info = info
        self.sequence = iter(sequence)
        self.total = len(sequence)
        self.start = self.now = time.time()
        self.num = 0
        self.stepsize = self.total / 100 or 1
        self.steptimes = []
        self.display()

    def __iter__(self): return self

    def next(self):
        self.num += 1

        if self.num > self.total:
            print self.info, 'done', ' '*(75-len(self.info)-6)
            sys.stdout.flush()
            return self.sequence.next()

        if self.num % self.stepsize:
            return self.sequence.next()

        self.display()
        return self.sequence.next()

    def display(self):
        # figure how long we've spent - guess how long to go
        now = time.time()
        steptime = now - self.now
        self.steptimes.insert(0, steptime)
        if len(self.steptimes) > 5:
            self.steptimes.pop()
        steptime = sum(self.steptimes) / len(self.steptimes)
        self.now = now
        eta = steptime * ((self.total - self.num)/self.stepsize)

        # tell it like it is (or might be)
        if now - self.start > 3:
            M = eta / 60
            H = M / 60
            M = M % 60
            S = eta % 60
            if self.total:
                s = '%s %2d%% (ETA %02d:%02d:%02d)'%(self.info,
                    self.num * 100. / self.total, H, M, S)
            else:
                s = '%s 0%% (ETA %02d:%02d:%02d)'%(self.info, H, M, S)
        elif self.total:
            s = '%s %2d%%'%(self.info, self.num * 100. / self.total)
        else:
            s = '%s %d done'%(self.info, self.num)
        sys.stdout.write(s + ' '*(75-len(s)) + '\r')
        sys.stdout.flush()

class Proptree(object):
    ''' Simple tree data structure for optimizing searching of properties
    '''

    def __init__(self, db, cls, name, props, parent = None):
        self.db = db
        self.name = name
        self.props = props
        self.parent = parent
        self._val = None
        self.has_values = False
        self.cls = cls
        self.classname = None
        self.uniqname = None
        self.children = []
        self.propnames = {}
        if parent:
            self.root = parent.root
            self.prcls = self.parent.props [name]
        else:
            self.root = self
            self.seqno = 1
        self.id = self.root.seqno
        self.root.seqno += 1
        if self.cls:
            self.classname = self.cls.classname
            self.uniqname = '%s%s' % (self.cls.classname, self.id)
        if not self.parent:
            self.uniqname = self.cls.classname

    def append(self, name):
        """Append a property to self.children. Will create a new
        propclass for the child.
        """
        import hyperdb
        if name in self.propnames:
            return self.propnames [name]
        propclass = self.props [name]
        cls = None
        props = None
        if isinstance(propclass, (hyperdb.Link, hyperdb.Multilink)):
            cls = self.db.getclass(propclass.classname)
            props = cls.getprops()
        child = self.__class__(self.db, cls, name, props, parent = self)
        self.children.append(child)
        self.propnames [name] = child
        return child

    def _set_val(self, val):
        """Check if self._val is already defined. If yes, we compute the
        intersection of the old and the new value(s)
        """
        if self.has_values:
            v = self._val
            if not isinstance(self._val, type([])):
                v = [self._val]
            vals = Set(v)
            vals.intersection_update(val)
            self._val = [v for v in vals]
        else:
            self._val = val
        self.has_values = True
    
    val = property(lambda self: self._val, _set_val)

    def __iter__(self):
        """ Yield nodes in depth-first order -- visited nodes first """
        for p in self.children:
            yield p
            for c in p:
                yield c

LEFT = 'left'
LEFTN = 'left no strip'
RIGHT = 'right'
CENTER = 'center'

def align(line, width=70, alignment=LEFTN):
    ''' Code from http://www.faqts.com/knowledge_base/view.phtml/aid/4476 '''
    if alignment == CENTER:
        line = line.strip()
        space = width - len(line)
        return ' '*(space/2) + line + ' '*(space/2 + space%2)
    elif alignment == RIGHT:
        line = line.rstrip()
        space = width - len(line)
        return ' '*space + line
    else:
        if alignment == LEFT:
            line = line.lstrip()
        space = width - len(line)
        return line + ' '*space


def format_line(columns, positions, contents, spacer=' | ',
        collapse_whitespace=True, wsre=re.compile(r'\s+')):
    ''' Fill up a single row with data from the contents '''
    l = []
    data = 0
    for i in range(len(columns)):
        width, alignment = columns[i]
        content = contents[i]
        col = ''
        while positions[i] < len(content):
            word = content[positions[i]]
            # if we hit a newline, honor it
            if '\n' in word:
                # chomp
                positions[i] += 1
                break

            # make sure this word fits
            if col and len(word) + len(col) > width:
                break

            # no whitespace at start-of-line
            if collapse_whitespace and wsre.match(word) and not col:
                # chomp
                positions[i] += 1
                continue

            col += word
            # chomp
            positions[i] += 1
        if col:
            data = 1
        col = align(col, width, alignment)
        l.append(col)

    if not data:
        return ''
    return spacer.join(l).rstrip()


def format_columns(columns, contents, spacer=' | ', collapse_whitespace=True,
        splitre=re.compile(r'(\n|\r\n|\r|[ \t]+|\S+)')):
    ''' Format the contents into columns, with 'spacing' between the
        columns
    '''
    assert len(columns) == len(contents), \
        'columns and contents must be same length'

    # split the text into words, spaces/tabs and newlines
    for i in range(len(contents)):
        contents[i] = splitre.findall(contents[i])

    # now process line by line
    l = []
    positions = [0]*len(contents)
    while 1:
        l.append(format_line(columns, positions, contents, spacer,
            collapse_whitespace))

        # are we done?
        for i in range(len(contents)):
            if positions[i] < len(contents[i]):
                break
        else:
            break
    return '\n'.join(l)

def wrap(text, width=75, alignment=LEFTN):
    return format_columns(((width, alignment),), [text],
        collapse_whitespace=False)

# vim: set et sts=4 sw=4 :
