import re, os, smtplib, socket

import config, hyperdb, date

def splitDesignator(designator, dre=re.compile(r'([^\d]+)(\d+)')):
    ''' Take a foo123 and return ('foo', 123)
    '''
    m = dre.match(designator)
    return m.group(1), m.group(2)

class Database(hyperdb.Database):
    def getuid(self):
        """Return the id of the "user" node associated with the user
        that owns this connection to the hyperdatabase."""
        return self.user.lookup(self.journaltag)

    def uidFromAddress(self, address):
        ''' address is from the rfc822 module, and therefore is (name, addr)
        '''
        (realname, address) = address
        users = self.user.stringFind(address=address)
        if users: return users[0]
        return self.user.create(username=address, address=address,
            realname=realname)

class Class(hyperdb.Class):
    # Overridden methods:
    def __init__(self, db, classname, **properties):
        hyperdb.Class.__init__(self, db, classname, **properties)
        self.auditors = {'create': [], 'set': [], 'retire': []}
        self.reactors = {'create': [], 'set': [], 'retire': []}

    def create(self, **propvalues):
        """These operations trigger detectors and can be vetoed.  Attempts
        to modify the "creation" or "activity" properties cause a KeyError.
        """
        if propvalues.has_key('creation') or propvalues.has_key('activity'):
            raise KeyError, '"creation" and "activity" are reserved'
        for audit in self.auditors['create']:
            audit(self.db, self, None, propvalues)
        nodeid = hyperdb.Class.create(self, **propvalues)
        for react in self.reactors['create']:
            react(self.db, self, nodeid, None)
        return nodeid

    def set(self, nodeid, **propvalues):
        """These operations trigger detectors and can be vetoed.  Attempts
        to modify the "creation" or "activity" properties cause a KeyError.
        """
        if propvalues.has_key('creation') or propvalues.has_key('activity'):
            raise KeyError, '"creation" and "activity" are reserved'
        for audit in self.auditors['set']:
            audit(self.db, self, nodeid, propvalues)
        oldvalues = self.db.getnode(self.classname, nodeid)
        hyperdb.Class.set(self, nodeid, **propvalues)
        for react in self.reactors['set']:
            react(self.db, self, nodeid, oldvalues)

    def retire(self, nodeid):
        """These operations trigger detectors and can be vetoed.  Attempts
        to modify the "creation" or "activity" properties cause a KeyError.
        """
        for audit in self.auditors['retire']:
            audit(self.db, self, nodeid, None)
        hyperdb.Class.retire(self, nodeid)
        for react in self.reactors['retire']:
            react(self.db, self, nodeid, None)

    # New methods:

    def audit(self, event, detector):
        """Register a detector
        """
        self.auditors[event].append(detector)

    def react(self, event, detector):
        """Register a detector
        """
        self.reactors[event].append(detector)

class FileClass(Class):
    def create(self, **propvalues):
        ''' snaffle the file propvalue and store in a file
        '''
        content = propvalues['content']
        del propvalues['content']
        newid = Class.create(self, **propvalues)
        self.setcontent(self.classname, newid, content)
        return newid

    def filename(self, classname, nodeid):
        # TODO: split into multiple files directories
        return os.path.join(self.db.dir, 'files', '%s%s'%(classname, nodeid))

    def setcontent(self, classname, nodeid, content):
        ''' set the content file for this file
        '''
        open(self.filename(classname, nodeid), 'wb').write(content)

    def getcontent(self, classname, nodeid):
        ''' get the content file for this file
        '''
        return open(self.filename(classname, nodeid), 'rb').read()

    def get(self, nodeid, propname):
        ''' trap the content propname and get it from the file
        '''
        if propname == 'content':
            return self.getcontent(self.classname, nodeid)
        return Class.get(self, nodeid, propname)

    def getprops(self):
        ''' In addition to the actual properties on the node, these methods
            provide the "content" property.
        '''
        d = Class.getprops(self).copy()
        d['content'] = hyperdb.String()
        return d

# XXX deviation from spec
class IssueClass(Class):
    # Overridden methods:

    def __init__(self, db, classname, **properties):
        """The newly-created class automatically includes the "messages",
        "files", "nosy", and "superseder" properties.  If the 'properties'
        dictionary attempts to specify any of these properties or a
        "creation" or "activity" property, a ValueError is raised."""
        if not properties.has_key('title'):
            properties['title'] = hyperdb.String()
        if not properties.has_key('messages'):
            properties['messages'] = hyperdb.Multilink("msg")
        if not properties.has_key('files'):
            properties['files'] = hyperdb.Multilink("file")
        if not properties.has_key('nosy'):
            properties['nosy'] = hyperdb.Multilink("user")
        if not properties.has_key('superseder'):
            properties['superseder'] = hyperdb.Multilink("issue")
        if (properties.has_key('creation') or properties.has_key('activity')
                or properties.has_key('creator')):
            raise ValueError, '"creation", "activity" and "creator" are reserved'
        Class.__init__(self, db, classname, **properties)

    def get(self, nodeid, propname):
        if propname == 'creation':
            return self.db.getjournal(self.classname, nodeid)[0][1]
        if propname == 'activity':
            return self.db.getjournal(self.classname, nodeid)[-1][1]
        if propname == 'creator':
            name = self.db.getjournal(self.classname, nodeid)[0][2]
            return self.db.user.lookup(name)
        return Class.get(self, nodeid, propname)

    def getprops(self):
        """In addition to the actual properties on the node, these
        methods provide the "creation" and "activity" properties."""
        d = Class.getprops(self).copy()
        d['creation'] = hyperdb.Date()
        d['activity'] = hyperdb.Date()
        d['creator'] = hyperdb.Link("user")
        return d

    # New methods:

    def addmessage(self, nodeid, summary, text):
        """Add a message to an issue's mail spool.

        A new "msg" node is constructed using the current date, the user that
        owns the database connection as the author, and the specified summary
        text.

        The "files" and "recipients" fields are left empty.

        The given text is saved as the body of the message and the node is
        appended to the "messages" field of the specified issue.
        """

    def sendmessage(self, nodeid, msgid):
        """Send a message to the members of an issue's nosy list.

        The message is sent only to users on the nosy list who are not
        already on the "recipients" list for the message.
        
        These users are then added to the message's "recipients" list.
        """
        # figure the recipient ids
        recipients = self.db.msg.get(msgid, 'recipients')
        r = {}
        for recipid in recipients:
            r[recipid] = 1
        authid = self.db.msg.get(msgid, 'author')
        r[authid] = 1

        # now figure the nosy people who weren't recipients
        sendto = []
        nosy = self.get(nodeid, 'nosy')
        for nosyid in nosy:
            if not r.has_key(nosyid):
                sendto.append(nosyid)
                recipients.append(nosyid)

        if sendto:
            # update the message's recipients list
            self.db.msg.set(msgid, recipients=recipients)

            # send an email to the people who missed out
            sendto = [self.db.user.get(i, 'address') for i in recipients]
            cn = self.classname
            title = self.get(nodeid, 'title') or '%s message copy'%cn
            m = ['Subject: [%s%s] %s'%(cn, nodeid, title)]
            m.append('To: %s'%', '.join(sendto))
            m.append('Reply-To: %s'%config.ISSUE_TRACKER_EMAIL)
            m.append('')
            m.append(self.db.msg.get(msgid, 'content'))
            # TODO attachments
            try:
                smtp = smtplib.SMTP(config.MAILHOST)
                smtp.sendmail(config.ISSUE_TRACKER_EMAIL, sendto, '\n'.join(m))
            except socket.error, value:
                return "Couldn't send confirmation email: mailhost %s"%value
            except smtplib.SMTPException, value:
                return "Couldn't send confirmation email: %s"%value

def nosyreaction(db, cl, nodeid, oldvalues):
    ''' A standard detector is provided that watches for additions to the
        "messages" property.
        
        When a new message is added, the detector sends it to all the users on
        the "nosy" list for the issue that are not already on the "recipients"
        list of the message.
        
        Those users are then appended to the "recipients" property on the
        message, so multiple copies of a message are never sent to the same
        user.
        
        The journal recorded by the hyperdatabase on the "recipients" property
        then provides a log of when the message was sent to whom. 
    '''
    messages = []
    if oldvalues is None:
        # the action was a create, so use all the messages in the create
        messages = cl.get(nodeid, 'messages')
    elif oldvalues.has_key('messages'):
        # the action was a set (so adding new messages to an existing issue)
        m = {}
        for msgid in oldvalues['messages']:
            m[msgid] = 1
        messages = []
        # figure which of the messages now on the issue weren't there before
        for msgid in cl.get(nodeid, 'messages'):
            if not m.has_key(msgid):
                messages.append(msgid)
    if not messages:
        return

    # send a copy to the nosy list
    for msgid in messages:
        cl.sendmessage(nodeid, msgid)

    # update the nosy list with the recipients from the new messages
    nosy = cl.get(nodeid, 'nosy')
    n = {}
    for nosyid in nosy: n[nosyid] = 1
    change = 0
    # but don't add admin to the nosy list
    for msgid in messages:
        for recipid in db.msg.get(msgid, 'recipients'):
            if recipid != '1' and not n.has_key(recipid):
                change = 1
                nosy.append(recipid)
        authid = db.msg.get(msgid, 'author')
        if authid != '1' and not n.has_key(authid):
            change = 1
            nosy.append(authid)
    if change:
        cl.set(nodeid, nosy=nosy)

def openDB(storagelocator, name=None, password=None):
    ''' Open the Roundup DB

        ... configs up all the classes etc
    '''
    db = Database(storagelocator, name)
    pri = Class(db, "priority", name=hyperdb.String(), order=hyperdb.String())
    pri.setkey("name")
    stat = Class(db, "status", name=hyperdb.String(), order=hyperdb.String())
    stat.setkey("name")
    Class(db, "keyword", name=hyperdb.String())
    user = Class(db, "user", username=hyperdb.String(),
        password=hyperdb.String(), address=hyperdb.String(),
        realname=hyperdb.String(), phone=hyperdb.String(),
        organisation=hyperdb.String())
    user.setkey("username")
    msg = FileClass(db, "msg", author=hyperdb.Link("user"),
        recipients=hyperdb.Multilink("user"), date=hyperdb.Date(),
        summary=hyperdb.String(), files=hyperdb.Multilink("file"))
    file = FileClass(db, "file", name=hyperdb.String(), type=hyperdb.String())

    # bugs and support calls etc
    rate = Class(db, "rate", name=hyperdb.String(), order=hyperdb.String())
    rate.setkey("name")
    source = Class(db, "source", name=hyperdb.String(), order=hyperdb.String())
    source.setkey("name")
    platform = Class(db, "platform", name=hyperdb.String(), order=hyperdb.String())
    platform.setkey("name")
    product = Class(db, "product", name=hyperdb.String(), order=hyperdb.String())
    product.setkey("name")
    Class(db, "timelog", date=hyperdb.Date(), time=hyperdb.String(),
        performedby=hyperdb.Link("user"), description=hyperdb.String())
    issue = IssueClass(db, "issue", assignedto=hyperdb.Link("user"),
        priority=hyperdb.Link("priority"), status=hyperdb.Link("status"),
        rate=hyperdb.Link("rate"), source=hyperdb.Link("source"),
        product=hyperdb.Link("product"), platform=hyperdb.Multilink("platform"),
        version=hyperdb.String(),
        timelog=hyperdb.Multilink("timelog"), customername=hyperdb.String())
    issue.setkey('title')
    issue.react('create', nosyreaction)
    issue.react('set', nosyreaction)
    return db

def initDB(storagelocator, password):
    ''' Initialise the Roundup DB for use
    '''
    dbdir = os.path.join(storagelocator, 'files')
    if not os.path.isdir(dbdir):
        os.makedirs(dbdir)
    db = openDB(storagelocator, "admin")
    db.clear()
    pri = db.getclass('priority')
    pri.create(name="fatal-bug", order="1")
    pri.create(name="bug", order="2")
    pri.create(name="usability", order="3")
    pri.create(name="feature", order="4")

    stat = db.getclass('status')
    stat.create(name="unread", order="1")
    stat.create(name="deferred", order="2")
    stat.create(name="chatting", order="3")
    stat.create(name="need-eg", order="4")
    stat.create(name="in-progress", order="5")
    stat.create(name="testing", order="6")
    stat.create(name="done-cbb", order="7")
    stat.create(name="resolved", order="8")

    rate = db.getclass("rate")
    rate.create(name='basic', order="1")
    rate.create(name='premium', order="2")
    rate.create(name='internal', order="3")

    source = db.getclass("source")
    source.create(name='phone', order="1")
    source.create(name='e-mail', order="2")
    source.create(name='internal', order="3")
    source.create(name='internal-qa', order="4")

    platform = db.getclass("platform")
    platform.create(name='linux', order="1")
    platform.create(name='windows', order="2")
    platform.create(name='mac', order="3")

    product = db.getclass("product")
    product.create(name='Bizar Shop', order="1")
    product.create(name='Bizar Shop Developer', order="2")
    product.create(name='Bizar Shop Manual', order="3")
    product.create(name='Bizar Shop Developer Manual', order="4")

    user = db.getclass('user')
    user.create(username="admin", password=password, address=config.ADMIN_EMAIL)

    db.close()

