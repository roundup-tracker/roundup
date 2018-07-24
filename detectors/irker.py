# This detector sends notification on IRC through an irker daemon
# (http://www.catb.org/esr/irker/) when issues are created or messages
#  are added.
#
# Written by Ezio Melotti
#
# Requires a running irkerd daemon to work.  See the irker documentation
# for more information about installing, configuring, and running irker.
#
# Add the IRC channel(s) that should receive notifications in
# detectors/config.ini as a comma-separated list, using this format:
#
#   [irker]
#   channels = irc://chat.freenode.net/channelname
#

from __future__ import print_function
import re
import json
import socket

IRKER_HOST = 'localhost'
IRKER_PORT = 6659

max_content = 120

TEMPLATE = ('%(green)s%(author)s%(reset)s '
            '%(bluish)s#%(nodeid)s%(reset)s/%(title)s%(bold)s:%(bold)s '
            '%(log)s %(url)s')


def sendmsg(msg):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.connect((IRKER_HOST, IRKER_PORT))
        sock.sendall(msg + "\n")
    finally:
        sock.close()


def notify_irker(db, cl, nodeid, oldvalues):
    messages = set(cl.get(nodeid, 'messages'))
    if oldvalues:
        messages -= set(oldvalues.get('messages', ()))
    if not messages:
        return
    messages = list(messages)

    if oldvalues:
        oldstatus = oldvalues['status']
    else:
        oldstatus = None
    newstatus = db.issue.get(nodeid, 'status')
    if oldstatus != newstatus:
        if oldvalues:
            status = db.status.get(newstatus, 'name')
        else:
            status = 'new'
        log = '[' + status + '] '
    else:
        log = ''
    for msg in messages:
        log += db.msg.get(msg, 'content')
    if len(log) > max_content:
        log = log[:max_content-3] + '...'
    log = re.sub('\s+', ' ', log)

    # include irc colors
    params = {
        'bold': '\x02',
        'green': '\x0303',
        'blue': '\x0302',
        'bluish': '\x0310',
        'yellow': '\x0307',
        'brown': '\x0305',
        'reset': '\x0F'
    }
    # extend with values used in the template
    params['author'] = db.user.get(db.getuid(), 'username')
    params['nodeid'] = nodeid
    params['title'] = db.issue.get(nodeid, 'title')
    params['log'] = log
    params['url'] = '%sissue%s' % (db.config.TRACKER_WEB, nodeid)

    # create the message and use the list of channels defined in
    # detectors/config.ini
    msg = json.dumps({
        'to': db.config.detectors.IRKER_CHANNELS.split(','),
        'privmsg': TEMPLATE % params,
    })

    try:
        sendmsg(msg)
    except Exception as e:
        # Ignore any errors in sending the irker;
        # if the server is down, that's just bad luck
        # XXX might want to do some logging here
        print('* Sending message to irker failed', str(e))

def init(db):
    db.issue.react('create', notify_irker)
    db.issue.react('set', notify_irker)
