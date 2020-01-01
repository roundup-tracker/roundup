"""Handle the security declarations used in Roundup trackers.
"""
__docformat__ = 'restructuredtext'

import weakref

from roundup import hyperdb, support

import logging
logger = logging.getLogger('roundup.security')


class Permission:
    ''' Defines a Permission with the attributes
        - name
        - description
        - klass (optional)
        - properties (optional)
        - check function (optional)
        - props_only (optional, internal field is limit_perm_to_props_only)

        The klass may be unset, indicating that this permission is not
        locked to a particular class. That means there may be multiple
        Permissions for the same name for different classes.

        If property names are set, permission is restricted to those
        properties only.

        If check function is set, permission is granted only when
        the function returns value interpreted as boolean true.
        The function is called with arguments db, userid, itemid.

        When the system checks klass permission rather than the klass
        property permission (i.e. properties=None and item=None), it
        will apply any permission that matches on permission name and
        class. If the permission has a check function, the check
        function will be run. By making the permission valid only for
        properties using props_only=True the permission will be
        skipped. You can set the default value for props_only for all
        properties by calling:

           db.security.set_props_only_default()

        with a True or False value.
    '''

    limit_perm_to_props_only = False

    def __init__(self, name='', description='', klass=None,
                 properties=None, check=None, props_only=None):
        from roundup.anypy import findargspec
        self.name = name
        self.description = description
        self.klass = klass
        self.properties = properties
        self._properties_dict = support.TruthDict(properties)
        self.check = check
        if properties is not None:
            # Set to None unless properties are defined.
            # This means that:
            # a=Property(name="Edit", klass="issue", check=dummy,
            #     props_only=True)
            # b=Property(name="Edit", klass="issue", check=dummy,
            #     props_only=False)
            # a == b will be true.
            if props_only is None:
                self.limit_perm_to_props_only = \
                                Permission.limit_perm_to_props_only
            else:
                # see note on use of bool() in set_props_only_default()
                self.limit_perm_to_props_only = bool(props_only)
        else:
            self.limit_perm_to_props_only = None

        if check is None:
            self.check_version = 0
        else:
            args = findargspec.findargspec(check)
            # args[2] is the keywords argument. Leave it as a subscript and
            # do not use named tuple reference as names change in python 3.
            # If there is a **parameter defined in the function spec, the
            # value of the 3rd argument (2nd index) in the tuple is not None.
            if args[2] is None:
                # function definition is function(db, userid, itemid)
                self.check_version = 1
            else:
                # function definition is function(db, userid, itemid, **other)
                self.check_version = 2

    def test(self, db, permission, classname, property, userid, itemid):
        ''' Test permissions 5 args:
            permission - string like Edit, Register etc. Required, no wildcard.
            classname - string like issue, msg etc. Can be None to match any
                        class.
            property - array of strings that are property names. Optional.
                   if None this is an item or klass access check.
            userid - number that is id for user.
            itemid - id for classname. e.g. 3 in issue3. If missing this is
                 a class access check, otherwies it's a object access check.
        '''

        if permission != self.name:
            return 0

        # are we checking the correct class
        if self.klass is not None and self.klass != classname:
            return 0

        # what about property?
        if property is not None and not self._properties_dict[property]:
            return 0

        # is this a props_only permission and permissions are set
        if property is None and self.properties is not None and \
                self.limit_perm_to_props_only:
            return 0

        # check code
        if itemid is not None and self.check is not None:
            if self.check_version == 1:
                if not self.check(db, userid, itemid):
                    return 0
            elif self.check_version == 2:
                if not self.check(db, userid, itemid, property=property,
                                  permission=permission, classname=classname):
                    return 0

        # we have a winner
        return 1

    def searchable(self, classname, property):
        """ A Permission is searchable for the given permission if it
            doesn't include a check method and otherwise matches the
            given parameters.
        """
        if self.name not in ('View', 'Search'):
            return 0

        # are we checking the correct class
        if self.klass is not None and self.klass != classname:
            return 0

        # what about property?
        if not self._properties_dict[property]:
            return 0

        if self.check:
            return 0

        return 1

    def __repr__(self):
        return '<Permission 0x%x %r,%r,%r,%r,%r>' % (id(self), self.name,
            self.klass, self.properties, self.check,
            self.limit_perm_to_props_only)

    def __eq__(self, other):
        if self.name != other.name:
            return False

        if self.klass != other.klass: return False
        if self.properties != other.properties: return False
        if self.check != other.check: return False
        if self.limit_perm_to_props_only != \
           other.limit_perm_to_props_only: return False

        # match
        return True

    def __ne__(self, other):
        return not self.__eq__(other)

    def __getitem__(self, index):
        return (self.name, self.klass, self.properties, self.check,
                self.limit_perm_to_props_only)[index]


class Role:
    ''' Defines a Role with the attributes
        - name
        - description
        - permissions
    '''
    def __init__(self, name='', description='', permissions=None):
        self.name = name.lower()
        self.description = description
        if permissions is None:
            permissions = []
        self.permissions = permissions

    def __repr__(self):
        return '<Role 0x%x %r,%r>' % (id(self), self.name, self.permissions)


class Security:
    def __init__(self, db):
        ''' Initialise the permission and role classes, and add in the
            base roles (for admin user).
        '''
        self.db = weakref.proxy(db)       # use a weak ref to avoid circularity

        # permssions are mapped by name to a list of Permissions by class
        self.permission = {}

        # roles are mapped by name to the Role
        self.role = {}

        # the default Roles
        self.addRole(name="User", description="A regular user, no privs")
        self.addRole(name="Admin", description="An admin user, full privs")
        self.addRole(name="Anonymous", description="An anonymous user")

        # default permissions - Admin may do anything
        for p in 'create edit restore retire view'.split():
            p = self.addPermission(name=p.title(),
                                   description="User may %s everything" % p)
            self.addPermissionToRole('Admin', p)

        # initialise the permissions and roles needed for the UIs
        from roundup.cgi import client
        client.initialiseSecurity(self)
        from roundup import mailgw
        mailgw.initialiseSecurity(self)

    def getPermission(self, permission, classname=None, properties=None,
                      check=None, props_only=None):
        ''' Find the Permission matching the name and for the class, if the
            classname is specified.

            Raise ValueError if there is no exact match.
        '''
        if permission not in self.permission:
            raise ValueError('No permission "%s" defined' % permission)

        if classname:
            try:
                self.db.getclass(classname)
            except KeyError:
                raise ValueError('No class "%s" defined' % classname)

        # look through all the permissions of the given name
        tester = Permission(permission, klass=classname, properties=properties,
                            check=check,
                            props_only=props_only)
        for perm in self.permission[permission]:
            if perm == tester:
                return perm
        raise ValueError('No permission "%s" defined for "%s"' % (permission,
                                                                  classname))

    def hasPermission(self, permission, userid, classname=None,
                      property=None, itemid=None):
        '''Look through all the Roles, and hence Permissions, and
           see if "permission" exists given the constraints of
           classname, property, itemid, and props_only.

           If classname is specified (and only classname) the
           search will match:

              if there is *any* Permission for that classname, and
              that Permission was not created with props_only = True

           *NOTE* the Permission will match even if there are
           additional constraints like a check or properties and
           props_only is False. This can be unexpected. Using
           props_only = True or setting the default value to True can
           help prevent surprises.

           If property is specified, the Permission matched must have
           either no properties listed or the property must appear in
           the list.

           If itemid is specified, the Permission matched must have
           either no check function defined or the check function,
           when invoked, must return a True value.

           Note that this functionality is actually implemented by the
           Permission.test() method.

        '''
        if itemid and classname is None:
            raise ValueError('classname must accompany itemid')
        for rolename in self.db.user.get_roles(userid):
            if not rolename or (rolename not in self.role):
                continue
            # for each of the user's Roles, check the permissions
            for perm in self.role[rolename].permissions:
                # permission match?
                if perm.test(self.db, permission, classname, property,
                             userid, itemid):
                    return 1
        return 0

    def roleHasSearchPermission(self, classname, property, *rolenames):
        """ For each of the given roles, check the permissions.
            Property can be a transitive property.
        """
        perms = []
        # pre-compute permissions
        for rn in rolenames:
            for perm in self.role[rn].permissions:
                perms.append(perm)
        # Note: break from inner loop means "found"
        #       break from outer loop means "not found"
        cn = classname
        prev = None
        prop = None
        Link = hyperdb.Link
        Multilink = hyperdb.Multilink
        for propname in property.split('.'):
            if prev:
                try:
                    cn = prop.classname
                except AttributeError:
                    break
            prev = propname
            try:
                cls = self.db.getclass(cn)
                prop = cls.getprops()[propname]
            except KeyError:
                break
            for perm in perms:
                if perm.searchable(cn, propname):
                    break
            else:
                break
        else:
            # for Link and Multilink require search permission on label-
            # and order-properties and on ID
            if isinstance(prop, Multilink) or isinstance(prop, Link):
                try:
                    cls = self.db.getclass(prop.classname)
                except KeyError:
                    return 0
                props = dict.fromkeys(('id', cls.labelprop(), cls.orderprop()))
                for p in props.keys():
                    for perm in perms:
                        if perm.searchable(prop.classname, p):
                            break
                    else:
                        return 0
            return 1
        return 0

    def hasSearchPermission(self, userid, classname, property):
        '''Look through all the Roles, and hence Permissions, and
           see if "permission" exists given the constraints of
           classname and property.

           A search permission is granted if we find a 'View' or
           'Search' permission for the user which does *not* include
           a check function. If such a permission is found, the user may
           search for the given property in the given class.

           Note that classname *and* property are mandatory arguments.

           Contrary to hasPermission, the search will *not* match if
           there are additional constraints (namely a search function)
           on a Permission found.

           Concerning property, the Permission matched must have
           either no properties listed or the property must appear in
           the list.
        '''
        roles = [r for r in self.db.user.get_roles(userid)
                 if r and (r in self.role)]
        return self.roleHasSearchPermission(classname, property, *roles)

    def addPermission(self, **propspec):
        ''' Create a new Permission with the properties defined in
            'propspec'. See the Permission class for the possible
            keyword args.
        '''
        perm = Permission(**propspec)
        self.permission.setdefault(perm.name, []).append(perm)
        return perm

    def addRole(self, **propspec):
        ''' Create a new Role with the properties defined in 'propspec'
        '''
        role = Role(**propspec)
        self.role[role.name] = role
        return role

    def set_props_only_default(self, props_only=None):
        if props_only is not None:
            # NOTE: only valid values are True and False because these
            # will be compared as part of tuple == tuple and
            # (3,) == (True,) is False even though 3 is a True value
            # in a boolean context. So use bool() to coerce value.
            Permission.limit_perm_to_props_only = \
                                    bool(props_only)

    def get_props_only_default(self):
        return Permission.limit_perm_to_props_only

    def addPermissionToRole(self, rolename, permission, classname=None,
                            properties=None, check=None, props_only=None):
        ''' Add the permission to the role's permission list.

            'rolename' is the name of the role to add the permission to.

            'permission' is either a Permission *or* a permission name
            accompanied by 'classname' (thus in the second case a Permission
            is obtained by passing 'permission' and 'classname' to
            self.getPermission)
        '''
        if not isinstance(permission, Permission):
            permission = self.getPermission(permission, classname,
                                            properties, check, props_only)
        role = self.role[rolename.lower()]
        role.permissions.append(permission)

    # Convenience methods for removing non-allowed properties from a
    # filterspec or sort/group list

    def filterFilterspec(self, userid, classname, filterspec):
        """ Return a filterspec that has all non-allowed properties removed.
        """
        return dict([(k, v) for k, v in filterspec.items()
                     if self.hasSearchPermission(userid, classname, k)])

    def filterSortspec(self, userid, classname, sort):
        """ Return a sort- or group-list that has all non-allowed properties
            removed.
        """
        if isinstance(sort, tuple) and sort[0] in '+-':
            sort = [sort]
        return [(d, p) for d, p in sort
                if self.hasSearchPermission(userid, classname, p)]

# vim: set filetype=python sts=4 sw=4 et si :
