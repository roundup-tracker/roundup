import htmllib, formatter

class Require:
    ''' Encapsulates a parsed <require attributes>...[<else>...]</require>
    '''
    def __init__(self, attributes):
        self.attributes = attributes
        self.current = self.ok = []
        self.fail = []
    def __len__(self):
        return len(self.current)
    def __getitem__(self, n):
        return self.current[n]
    def __setitem__(self, n, data):
        self.current[n] = data
    def append(self, data):
        self.current.append(data)
    def elseMode(self):
        self.current = self.fail
    def __repr__(self):
        return '<Require %r ok:%r fail:%r>'%(self.attributes, self.ok,
            self.fail)

class Display:
    ''' Encapsulates a parsed <display attributes>
    '''
    def __init__(self, attributes):
        self.attributes = attributes
    def __repr__(self):
        return '<Display %r>'%self.attributes

class Property:
    ''' Encapsulates a parsed <property attributes>
    '''
    def __init__(self, attributes):
        self.attributes = attributes
        self.current = self.structure = []
    def __len__(self):
        return len(self.current)
    def __getitem__(self, n):
        return self.current[n]
    def __setitem__(self, n, data):
        self.current[n] = data
    def append(self, data):
        self.current.append(data)
    def __repr__(self):
        return '<Property %r %r>'%(self.attributes, self.structure)

class RoundupTemplate(htmllib.HTMLParser):
    ''' Parse Roundup's HTML template structure into a list of components:

        'string': this is just plain data to be displayed
        Display : instances indicate that display functions are to be called
        Require : if/else style check using the conditions in the attributes,
                  displaying the "ok" list of components or "fail" list

    '''
    def __init__(self):
        htmllib.HTMLParser.__init__(self, formatter.NullFormatter())
        self.current = self.structure = []
        self.stack = []

    def handle_data(self, data):
        self.append_data(data)

    def append_data(self, data):
        if self.current and isinstance(self.current[-1], type('')):
            self.current[-1] = self.current[-1] + data
        else:
            self.current.append(data)

    def unknown_starttag(self, tag, attributes):
        s = ''
        s = s + '<%s' % tag
        for name, value in attributes:
            s = s + ' %s="%s"' % (name, value)
        s = s + '>'
        self.append_data(s)

    def handle_starttag(self, tag, method, attributes):
        if tag in ('require', 'else', 'display', 'property'):
            method(attributes)
        else:
            self.unknown_starttag(tag, attributes)

    def unknown_endtag(self, tag):
        if tag in ('require','property'):
            self.current = self.stack.pop()
        else:
            self.append_data('</%s>'%tag)

    def handle_endtag(self, tag, method):
        self.unknown_endtag(tag)

    def close(self):
        htmllib.HTMLParser.close(self)

    def do_display(self, attributes):
        self.current.append(Display(attributes))

    def do_property(self, attributes):
        p = Property(attributes)
        self.current.append(p)
        self.stack.append(self.current)
        self.current = p

    def do_require(self, attributes):
        r = Require(attributes)
        self.current.append(r)
        self.stack.append(self.current)
        self.current = r

    def do_else(self, attributes):
        self.current.elseMode()

    def __repr__(self):
        return '<RoundupTemplate %r>'%self.structure

def display(structure, indent=''):
    ''' Pretty-print the parsed structure for debugging
    '''
    l = []
    for entry in structure:
        if isinstance(entry, type('')):
            l.append("%s%s"%(indent, entry))
        elif isinstance(entry, Require):
            l.append('%sTEST: %r\n'%(indent, entry.attributes))
            l.append('%sOK...'%indent)
            l.append(display(entry.ok, indent+' '))
            if entry.fail:
                l.append('%sFAIL...'%indent)
                l.append(display(entry.fail, indent+' '))
        elif isinstance(entry, Display):
            l.append('%sDISPLAY: %r'%(indent, entry.attributes))
        elif isinstance(entry, Property):
            l.append('%sPROPERTY: %r'%(indent, entry.attributes))
            l.append(display(entry.structure, indent+' '))
    return ''.join(l)

if __name__ == '__main__':
    import sys
    parser = RoundupTemplate()
    parser.feed(open(sys.argv[1], 'r').read())
    print display(parser.structure)

