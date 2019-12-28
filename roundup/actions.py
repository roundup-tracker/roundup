#
# Copyright (C) 2009 Stefan Seefeld
# All rights reserved.
# For license terms see the file COPYING.txt.
# Actions used in REST and XMLRPC APIs
#

from roundup.exceptions import Unauthorised
from roundup import hyperdb


class Action:
    def __init__(self, db, translator):
        self.db = db
        self.translator = translator

    def handle(self, *args):
        """Action handler procedure"""
        raise NotImplementedError

    def execute(self, *args):
        """Execute the action specified by this object."""

        self.permission(*args)
        return self.handle(*args)

    def permission(self, *args):
        """Check whether the user has permission to execute this action.

        If not, raise Unauthorised."""

        pass

    def gettext(self, msgid):
        """Return the localized translation of msgid"""
        return self.translator.gettext(msgid)

    _ = gettext


class PermCheck(Action):
    def permission(self, designator):

        classname, itemid = hyperdb.splitDesignator(designator)
        perm = self.db.security.hasPermission

        if not perm('Retire', self.db.getuid(), classname=classname,
                    itemid=itemid):
            raise Unauthorised(self._('You do not have permission to retire '
                                      'or restore the %(classname)s class.')
                               % locals())


class Retire(PermCheck):

    def handle(self, designator):

        classname, itemid = hyperdb.splitDesignator(designator)

        # make sure we don't try to retire admin or anonymous
        if (classname == 'user' and
               self.db.user.get(itemid, 'username') in ('admin', 'anonymous')):
            raise ValueError(self._(
                'You may not retire the admin or anonymous user'))

        # do the retire
        self.db.getclass(classname).retire(itemid)
        self.db.commit()


class Restore(PermCheck):

    def handle(self, designator):

        classname, itemid = hyperdb.splitDesignator(designator)

        # do the restore
        self.db.getclass(classname).restore(itemid)
        self.db.commit()
