''' Import tracker data from Sourceforge.NET

This script needs four steps to work:

1. Export the project XML data using the admin web interface at sf.net
2. Run the file fetching (these are not included in the XML):

    import_sf.py files <path to XML> <path to files dir>

   this will place all the downloaded files in the files dir by file id.
3. Convert the sf.net XML to Roundup "export" format:

    import_sf.py import <tracker home> <path to XML> <path to files dir>

   this will generate a directory "/tmp/imported" which contains the
   data to be imported into a Roundup tracker.
4. Import the data:

    roundup-admin -i <tracker home> import /tmp/imported

And you're done!
'''

import sys, sets, os, csv, time, urllib2, httplib, mimetypes, urlparse

try:
    import cElementTree as ElementTree
except ImportError:
    from elementtree import ElementTree

from roundup import instance, hyperdb, date, support, password

today = date.Date('.')

DL_URL = 'http://sourceforge.net/tracker/download.php?group_id=%(group_id)s&atid=%(atid)s&aid=%(aid)s'

def get_url(aid):
    """ so basically we have to jump through hoops, given an artifact id, to
    figure what the URL should be to access that artifact, and hence any
    attached files."""
    # first we hit this URL...
    conn = httplib.HTTPConnection("sourceforge.net")
    conn.request("GET", "/support/tracker.php?aid=%s"%aid)
    response = conn.getresponse()
    # which should respond with a redirect to the correct url which has the
    # magic "group_id" and "atid" values in it that we need
    assert response.status == 302, 'response code was %s'%response.status
    location = response.getheader('location')
    query = urlparse.urlparse(response.getheader('location'))[-2]
    info = dict([param.split('=') for param in query.split('&')])
    return DL_URL%info

def fetch_files(xml_file, file_dir):
    """ Fetch files referenced in the xml_file into the dir file_dir. """
    root = ElementTree.parse(xml_file).getroot()
    to_fetch = sets.Set()
    deleted = sets.Set()
    for artifact in root.find('artifacts'):
        for field in artifact.findall('field'):
            if field.get('name') == 'artifact_id':
                aid = field.text
        for field in artifact.findall('field'):
            if field.get('name') != 'artifact_history': continue
            for event in field.findall('history'):
                d = {}
                for field in event.findall('field'):
                    d[field.get('name')] = field.text
                if d['field_name'] == 'File Added':
                    fid = d['old_value'].split(':')[0]
                    to_fetch.add((aid, fid))
                if d['field_name'] == 'File Deleted':
                    fid = d['old_value'].split(':')[0]
                    deleted.add((aid, fid))
    to_fetch = to_fetch - deleted

    got = sets.Set(os.listdir(file_dir))
    to_fetch = to_fetch - got

    # load cached urls (sigh)
    urls = {}
    if os.path.exists(os.path.join(file_dir, 'urls.txt')):
        for line in open(os.path.join(file_dir, 'urls.txt')):
            aid, url = line.strip().split()
            urls[aid] = url

    for aid, fid in support.Progress('Fetching files', list(to_fetch)):
        if fid in got: continue
        if not urls.has_key(aid):
            urls[aid] = get_url(aid)
            f = open(os.path.join(file_dir, 'urls.txt'), 'a')
            f.write('%s %s\n'%(aid, urls[aid]))
            f.close()
        url = urls[aid] + '&file_id=' + fid
        f = urllib2.urlopen(url)
        data = f.read()
        n = open(os.path.join(file_dir, fid), 'w')
        n.write(data)
        f.close()
        n.close()

def import_xml(tracker_home, xml_file, file_dir):
    """ Generate Roundup tracker import files based on the tracker schema,
    sf.net xml export and downloaded files from sf.net. """
    tracker = instance.open(tracker_home)
    db = tracker.open('admin')

    resolved = db.status.lookup('resolved')
    unread = db.status.lookup('unread')
    chatting = db.status.lookup('unread')
    critical = db.priority.lookup('critical')
    urgent = db.priority.lookup('urgent')
    bug = db.priority.lookup('bug')
    feature = db.priority.lookup('feature')
    wish = db.priority.lookup('wish')
    adminuid = db.user.lookup('admin')
    anonuid = db.user.lookup('anonymous')

    root = ElementTree.parse(xml_file).getroot()

    def to_date(ts):
        return date.Date(time.gmtime(float(ts)))

    # parse out the XML
    artifacts = []
    categories = sets.Set()
    users = sets.Set()
    add_files = sets.Set()
    remove_files = sets.Set()
    for artifact in root.find('artifacts'):
        d = {}
        op = {}
        artifacts.append(d)
        for field in artifact.findall('field'):
            name = field.get('name')
            if name == 'artifact_messages':
                for message in field.findall('message'):
                    l = d.setdefault('messages', [])
                    m = {}
                    l.append(m)
                    for field in message.findall('field'):
                        name = field.get('name')
                        if name == 'adddate':
                            m[name] = to_date(field.text)
                        else:
                            m[name] = field.text
                        if name == 'user_name': users.add(field.text)
            elif name == 'artifact_history':
                for event in field.findall('history'):
                    l = d.setdefault('history', [])
                    e = {}
                    l.append(e)
                    for field in event.findall('field'):
                        name = field.get('name')
                        if name == 'entrydate':
                            e[name] = to_date(field.text)
                        else:
                            e[name] = field.text
                        if name == 'mod_by': users.add(field.text)
                    if e['field_name'] == 'File Added':
                        add_files.add(e['old_value'].split(':')[0])
                    elif e['field_name'] == 'File Deleted':
                        remove_files.add(e['old_value'].split(':')[0])
            elif name == 'details':
                op['body'] = field.text
            elif name == 'submitted_by':
                op['user_name'] = field.text
                d[name] = field.text
                users.add(field.text)
            elif name == 'open_date':
                thedate = to_date(field.text)
                op['adddate'] = thedate
                d[name] = thedate
            else:
                d[name] = field.text

        categories.add(d['category'])

        if op.has_key('body'):
            l = d.setdefault('messages', [])
            l.insert(0, op)

    add_files -= remove_files

    # create users
    userd = {'nobody': '2'}
    users.remove('nobody')
    data = [
        {'id': '1', 'username': 'admin', 'password': password.Password('admin'),
            'roles': 'Admin', 'address': 'richard@python.org'},
        {'id': '2', 'username': 'anonymous', 'roles': 'Anonymous'},
    ]
    for n, user in enumerate(list(users)):
        userd[user] = n+3
        data.append({'id': str(n+3), 'username': user, 'roles': 'User',
            'address': '%s@users.sourceforge.net'%user})
    write_csv(db.user, data)
    users=userd

    # create categories
    categoryd = {'None': None}
    categories.remove('None')
    data = []
    for n, category in enumerate(list(categories)):
        categoryd[category] = n
        data.append({'id': str(n), 'name': category})
    write_csv(db.keyword, data)
    categories = categoryd

    # create issues
    issue_data = []
    file_data = []
    message_data = []
    issue_journal = []
    message_id = 0
    for artifact in artifacts:
        d = {}
        d['id'] = artifact['artifact_id']
        d['title'] = artifact['summary']
        d['assignedto'] = users[artifact['assigned_to']]
        if d['assignedto'] == '2':
            d['assignedto'] = None
        d['creation'] = artifact['open_date']
        activity = artifact['open_date']
        d['creator'] = users[artifact['submitted_by']]
        actor = d['creator']
        if categories[artifact['category']]:
            d['topic'] = [categories[artifact['category']]]
        issue_journal.append((
            d['id'], d['creation'].get_tuple(), d['creator'], "'create'", {}
        ))

        p = int(artifact['priority'])
        if artifact['artifact_type'] == 'Feature Requests':
            if p > 3:
                d['priority'] = feature
            else:
                d['priority'] = wish
        else:
            if p > 7:
                d['priority'] = critical
            elif p > 5:
                d['priority'] = urgent
            elif p > 3:
                d['priority'] = bug
            else:
                d['priority'] = feature

        s = artifact['status']
        if s == 'Closed':
            d['status'] = resolved
        elif s == 'Deleted':
            d['status'] = resolved
            d['is retired'] = True
        else:
            d['status'] = unread

        nosy = sets.Set()
        for message in artifact.get('messages', []):
            authid = users[message['user_name']]
            if not message['body']: continue
            body = convert_message(message['body'], message_id)
            if not body: continue
            m = {'content': body, 'author': authid,
                'date': message['adddate'],
                'creation': message['adddate'], }
            message_data.append(m)
            if authid not in (None, '2'):
                nosy.add(authid)
            activity = message['adddate']
            actor = authid
            if d['status'] == unread:
                d['status'] = chatting

        # add import message
        m = {'content': 'IMPORT FROM SOURCEFORGE', 'author': '1',
            'date': today, 'creation': today}
        message_data.append(m)

        # sort messages and assign ids
        d['messages'] = []
        message_data.sort(lambda a,b:cmp(a['date'],b['date']))
        for message in message_data:
            message_id += 1
            message['id'] = str(message_id)
            d['messages'].append(message_id)

        d['nosy'] = list(nosy)

        files = []
        for event in artifact.get('history', []):
            if event['field_name'] == 'File Added':
                fid, name = event['old_value'].split(':', 1)
                if fid in add_files:
                    files.append(fid)
                    name = name.strip()
                    try:
                        f = open(os.path.join(file_dir, fid))
                        content = f.read()
                        f.close()
                    except:
                        content = 'content missing'
                    file_data.append({
                        'id': fid,
                        'creation': event['entrydate'],
                        'creator': users[event['mod_by']],
                        'name': name,
                        'type': mimetypes.guess_type(name)[0],
                        'content': content,
                    })
                continue
            elif event['field_name'] == 'close_date':
                action = "'set'"
                info = { 'status': unread }
            elif event['field_name'] == 'summary':
                action = "'set'"
                info = { 'title': event['old_value'] }
            else:
                # not an interesting / translatable event
                continue
            row = [ d['id'], event['entrydate'].get_tuple(),
                users[event['mod_by']], action, info ]
            if event['entrydate'] > activity:
                activity = event['entrydate']
            issue_journal.append(row)
        d['files'] = files

        d['activity'] = activity
        d['actor'] = actor
        issue_data.append(d)

    write_csv(db.issue, issue_data)
    write_csv(db.msg, message_data)
    write_csv(db.file, file_data)

    f = open('/tmp/imported/issue-journals.csv', 'w')
    writer = csv.writer(f, colon_separated)
    writer.writerows(issue_journal)
    f.close()

def convert_message(content, id):
    ''' Strip off the useless sf message header crap '''
    if content[:14] == 'Logged In: YES':
        return '\n'.join(content.splitlines()[3:]).strip()
    return content

class colon_separated(csv.excel):
    delimiter = ':'

def write_csv(klass, data):
    props = klass.getprops()
    if not os.path.exists('/tmp/imported'):
        os.mkdir('/tmp/imported')
    f = open('/tmp/imported/%s.csv'%klass.classname, 'w')
    writer = csv.writer(f, colon_separated)
    propnames = klass.export_propnames()
    propnames.append('is retired')
    writer.writerow(propnames)
    for entry in data:
        row = []
        for name in propnames:
            if name == 'is retired':
                continue
            prop = props[name]
            if entry.has_key(name):
                if isinstance(prop, hyperdb.Date) or \
                        isinstance(prop, hyperdb.Interval):
                    row.append(repr(entry[name].get_tuple()))
                elif isinstance(prop, hyperdb.Password):
                    row.append(repr(str(entry[name])))
                else:
                    row.append(repr(entry[name]))
            elif isinstance(prop, hyperdb.Multilink):
                row.append('[]')
            elif name in ('creator', 'actor'):
                row.append("'1'")
            elif name in ('created', 'activity'):
                row.append(repr(today.get_tuple()))
            else:
                row.append('None')
        row.append(entry.get('is retired', False))
        writer.writerow(row)

        if isinstance(klass, hyperdb.FileClass) and entry.get('content'):
            fname = klass.exportFilename('/tmp/imported/', entry['id'])
            support.ensureParentsExist(fname)
            c = open(fname, 'w')
            if isinstance(entry['content'], unicode):
                c.write(entry['content'].encode('utf8'))
            else:
                c.write(entry['content'])
            c.close()

    f.close()
    f = open('/tmp/imported/%s-journals.csv'%klass.classname, 'w')
    f.close()

if __name__ == '__main__':
    if sys.argv[1] == 'import':
        import_xml(*sys.argv[2:])
    elif sys.argv[1] == 'files':
        fetch_files(*sys.argv[2:])

