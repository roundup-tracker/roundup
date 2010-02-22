#
# Copyright (C) 2009 Stefan Seefeld
# All rights reserved.
# For license terms see the file COPYING.txt.
#

from roundup.exceptions import *
from roundup import hyperdb
from roundup.i18n import _

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


class Retire(Action):

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


    def permission(self, designator):

        classname, itemid = hyperdb.splitDesignator(designator)

        if not self.db.security.hasPermission('Edit', self.db.getuid(),
                                              classname=classname, itemid=itemid):
            raise Unauthorised(self._('You do not have permission to '
                                      'retire the %(classname)s class.')%classname)
            
