from roundup import hyperdb, roundupdb
from roundup.mailer import Mailer


def indentChangeNoteValue(text):
    # copied from roundupdb.IssueClass.indentChangeNoteValue()
    lines = text.rstrip('\n').split('\n')
    lines = [ '  '+line for line in lines ]
    return '\n'.join(lines)

def generateCreateNote(db, cl, nodeid):
    # copied from roundupdb.IssueClass.generateCreateNote()
    cn = cl.classname
    props = cl.getprops(protected=0)

    # list the values
    m = []
    prop_items = sorted(props.items())
    for propname, prop in prop_items:
        value = cl.get(nodeid, propname, None)
        # skip boring entries
        if not value:
            continue
        if isinstance(prop, hyperdb.Link):
            link = db.classes[prop.classname]
            if value:
                key = link.labelprop(default_to_id=1)
                if key:
                    value = link.get(value, key)
            else:
                value = ''
        elif isinstance(prop, hyperdb.Multilink):
            if value is None: value = []
            l = []
            link = db.classes[prop.classname]
            key = link.labelprop(default_to_id=1)
            if key:
                value = [link.get(entry, key) for entry in value]
            value.sort()
            value = ', '.join(value)
        else:
            value = str(value)
            if '\n' in value:
                value = '\n'+indentChangeNoteValue(value)
        m.append('%s: %s'%(propname, value))
    m.insert(0, '----------')
    m.insert(0, '')
    return '\n'.join(m)

def newitemcopy(db, cl, nodeid, oldvalues):
    ''' Copy a message about new items to the dispatcher address.
    '''
    try:
        create_note = cl.generateCreateNote(nodeid)
    except AttributeError:
        create_note = generateCreateNote(db, cl, nodeid)

    try:
        dispatcher_email = getattr(db.config, 'DISPATCHER_EMAIL')
    except AttributeError:
        return

    try:
        msgids = cl.get(nodeid, 'messages')
    except KeyError:
        msgids = None

    if msgids:
        # send a copy to the dispatcher
        for msgid in msgids:
            try:
                cl.send_message(nodeid, msgid, create_note, [dispatcher_email])
            except roundupdb.MessageSendError as message:
                raise roundupdb.DetectorError(message)
    else:
        mailer = Mailer(db.config)
        subject = 'New %s%s' % (cl.classname, nodeid)
        mailer.standard_message([dispatcher_email], subject, create_note)

def init(db):
    for classname in db.getclasses():
        cl = db.getclass(classname)
        cl.react('create', newitemcopy)
