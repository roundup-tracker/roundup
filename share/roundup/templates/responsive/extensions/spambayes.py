import re, math
from roundup.cgi.actions import Action
from roundup.cgi.exceptions import *

import xmlrpclib, socket

REVPAT = re.compile(r'(r[0-9]+\b|rev(ision)? [0-9]+\b)')

def extract_classinfo(db, classname, nodeid):
    node = db.getnode(classname, nodeid)

    authorage = node['creation'].timestamp() - \
                db.getnode('user', node.get('author', node.get('creator')))['creation'].timestamp()

    authorid = node.get('author', node.get('creator'))

    content = db.getclass(classname).get(nodeid, 'content')

    tokens = ["klass:%s" % classname,
              "author:%s" % authorid,
              "authorage:%d" % int(math.log(authorage)),
              "hasrev:%s" % (REVPAT.search(content) is not None)]

    return (content, tokens)

def train_spambayes(db, content, tokens, is_spam):
    spambayes_uri = db.config.detectors['SPAMBAYES_URI']

    server = xmlrpclib.ServerProxy(spambayes_uri, verbose=False)
    try:
        server.train({'content':content}, tokens, {}, is_spam)
        return (True, None)
    except (socket.error, xmlrpclib.Error), e:
        return (False, str(e))


class SpambayesClassify(Action):
    permissionType = 'SB: May Classify'
    
    def handle(self):
        (content, tokens) = extract_classinfo(self.db,
                                              self.classname, self.nodeid)

        if self.form.has_key("trainspam"):
            is_spam = True
        elif self.form.has_key("trainham"):
            is_spam = False

        (status, errmsg) = train_spambayes(self.db, content, tokens,
                                           is_spam)

        node = self.db.getnode(self.classname, self.nodeid)
        props = {}

        if status:
            if node.get('spambayes_misclassified', False):
                props['spambayes_misclassified'] = True

            props['spambayes_score'] = 1.0
            
            s = " SPAM"
            if not is_spam:
                props['spambayes_score'] = 0.0
                s = " HAM"
            self.client.add_ok_message(self._('Message classified as') + s)
        else:
            self.client.add_error_message(self._('Unable to classify message, got error:') + errmsg)

        klass = self.db.getclass(self.classname)
        klass.set(self.nodeid, **props)
        self.db.commit()

def sb_is_spam(obj):
    cutoff_score = float(obj._db.config.detectors['SPAMBAYES_SPAM_CUTOFF'])
    try:
        score = obj['spambayes_score']
    except KeyError:
        return False
    return score >= cutoff_score

def init(instance):
    instance.registerAction("spambayes_classify", SpambayesClassify)
    instance.registerUtil('sb_is_spam', sb_is_spam)
    
