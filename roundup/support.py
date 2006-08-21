"""Implements various support classes and functions used in a number of
places in Roundup code.
"""

__docformat__ = 'restructuredtext'

import os, time, sys, re

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

# Python2.3 backwards-compatibility-hack. Should be removed (and clients
# fixed to use built-in reversed/sorted) when we abandon support for
# python2.3
try:
    reversed = reversed
except NameError:
    def reversed(x):
        x = list(x)
        x.reverse()
        return x

try:
    sorted = sorted
except NameError:
    def sorted(iter, cmp=None, key=None, reverse=False):
        if key:
            l = []
            cnt = 0 # cnt preserves original sort-order
            inc = [1, -1][bool(reverse)] # count down on reverse
            for x in iter:
                l.append ((key(x), cnt, x))
                cnt += inc
        else:
            l = list(iter)
        if cmp:
            l.sort(cmp = cmp)
        else:
            l.sort()
        if reverse:
            l.reverse()
        if key:
            return [x[-1] for x in l]
        return l

# vim: set et sts=4 sw=4 :
