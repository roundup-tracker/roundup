import weakref

from roundup import hyperdb

class Permission:
    ''' Defines a Permission with the attributes
        - name
        - description
        - klass (optional)

        The klass may be unset, indicating that this permission is not
        locked to a particular class. That means there may be multiple
        Permissions for the same name for different classes.
    '''
    def __init__(self, name='', description='', klass=None):
        self.name = name
        self.description = description
        self.klass = klass

    def __repr__(self):
        return '<Permission 0x%x %r,%r>'%(id(self), self.name, self.klass)

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
        return '<Role 0x%x %r,%r>'%(id(self), self.name, self.permissions)

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

        ee = self.addPermission(name="Edit",
            description="User may edit everthing")
        self.addPermissionToRole('Admin', ee)
        ae = self.addPermission(name="View",
            description="User may access everything")
        self.addPermissionToRole('Admin', ae)
        reg = self.addPermission(name="Register Web",
            description="User may register through the web")
        reg = self.addPermission(name="Register Email",
            description="User may register through the email")

        # initialise the permissions and roles needed for the UIs
        from roundup.cgi import client
        client.initialiseSecurity(self)
        from roundup import mailgw
        mailgw.initialiseSecurity(self)

    def getPermission(self, permission, classname=None):
        ''' Find the Permission matching the name and for the class, if the
            classname is specified.

            Raise ValueError if there is no exact match.
        '''
        if not self.permission.has_key(permission):
            raise ValueError, 'No permission "%s" defined'%permission

        # look through all the permissions of the given name
        for perm in self.permission[permission]:
            # if we're passed a classname, the permission must match
            if perm.klass is not None and perm.klass == classname:
                return perm
            # otherwise the permission klass must be unset
            elif not perm.klass and not classname:
                return perm
        raise ValueError, 'No permission "%s" defined for "%s"'%(permission,
            classname)

    def hasPermission(self, permission, userid, classname=None):
        ''' Look through all the Roles, and hence Permissions, and see if
            "permission" is there for the specified classname.
        '''
        roles = self.db.user.get(userid, 'roles')
        if roles is None:
            return 0
        for rolename in [x.lower().strip() for x in roles.split(',')]:
            if not rolename or not self.role.has_key(rolename):
                continue
            # for each of the user's Roles, check the permissions
            for perm in self.role[rolename].permissions:
                # permission name match?
                if perm.name == permission:
                    # permission klass match?
                    if perm.klass is None or perm.klass == classname:
                        # we have a winner
                        return 1
        return 0

    def hasNodePermission(self, classname, nodeid, **propspec):
        ''' Check the named properties of the given node to see if the
            userid appears in them. If it does, then the user is granted
            this permission check.

            'propspec' consists of a set of properties and values that
            must be present on the given node for access to be granted.

            If a property is a Link, the value must match the property
            value. If a property is a Multilink, the value must appear
            in the Multilink list.
        '''
        klass = self.db.getclass(classname)
        properties = klass.getprops()
        for k,v in propspec.items():
            value = klass.get(nodeid, k)
            if isinstance(properties[k], hyperdb.Multilink):
                if v not in value:
                    return 0
            else:
                if v != value:
                    return 0
        return 1

    def addPermission(self, **propspec):
        ''' Create a new Permission with the properties defined in
            'propspec'
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

    def addPermissionToRole(self, rolename, permission):
        ''' Add the permission to the role's permission list.

            'rolename' is the name of the role to add the permission to.
        '''
        role = self.role[rolename.lower()]
        role.permissions.append(permission)

# vim: set filetype=python ts=4 sw=4 et si
