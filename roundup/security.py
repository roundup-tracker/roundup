import weakref

from roundup import hyperdb, volatiledb

class PermissionClass(volatiledb.VolatileClass):
    ''' Include the default attributes:
        - name (String)
        - classname (String)
        - description (String)

        The classname may be unset, indicating that this permission is not
        locked to a particular class. That means there may be multiple
        Permissions for the same name for different classes.
    '''
    def __init__(self, db, classname, **properties):
        """ set up the default properties
        """
        if not properties.has_key('name'):
            properties['name'] = hyperdb.String()
        if not properties.has_key('klass'):
            properties['klass'] = hyperdb.String()
        if not properties.has_key('description'):
            properties['description'] = hyperdb.String()
        volatiledb.VolatileClass.__init__(self, db, classname, **properties)

class RoleClass(volatiledb.VolatileClass):
    ''' Include the default attributes:
        - name (String, key)
        - description (String)
        - permissions (PermissionClass Multilink)
    '''
    def __init__(self, db, classname, **properties):
        """ set up the default properties
        """
        if not properties.has_key('name'):
            properties['name'] = hyperdb.String()
        if not properties.has_key('description'):
            properties['description'] = hyperdb.String()
        if not properties.has_key('permissions'):
            properties['permissions'] = hyperdb.Multilink('permission')
        volatiledb.VolatileClass.__init__(self, db, classname, **properties)
        self.setkey('name')

class Security:
    def __init__(self, db):
        ''' Initialise the permission and role classes, and add in the
            base roles (for admin user).
        '''
        # use a weak ref to avoid circularity
        self.db = weakref.proxy(db)

        # create the permission class instance (we only need one))
        self.permission = PermissionClass(db, "permission")

        # create the role class instance (we only need one)
        self.role = RoleClass(db, "role")

        # the default Roles
        self.addRole(name="User", description="A regular user, no privs")
        self.addRole(name="Admin", description="An admin user, full privs")
        self.addRole(name="Anonymous", description="An anonymous user")

        ee = self.addPermission(name="Edit",
            description="User may edit everthing")
        self.addPermissionToRole('Admin', ee)
        ae = self.addPermission(name="Access",
            description="User may access everything")
        self.addPermissionToRole('Admin', ae)
        ae = self.addPermission(name="Assign",
            description="User may be assigned to anything")
        self.addPermissionToRole('Admin', ae)
        reg = self.addPermission(name="Register Web",
            description="User may register through the web")
        self.addPermissionToRole('Anonymous', reg)
        reg = self.addPermission(name="Register Email",
            description="User may register through the email")
        self.addPermissionToRole('Anonymous', reg)

        # initialise the permissions and roles needed for the UIs
        from roundup import cgi_client, mailgw
        cgi_client.initialiseSecurity(self)
        mailgw.initialiseSecurity(self)

    def hasClassPermission(self, classname, permission, userid):
        ''' Look through all the Roles, and hence Permissions, and see if
            "permission" is there for the specified classname.

        '''
        roles = self.db.user.get(userid, 'roles')
        for roleid in roles:
            for permissionid in self.db.role.get(roleid, 'permissions'):
                if self.db.permission.get(permissionid, 'name') != permission:
                    continue
                klass = self.db.permission.get(permissionid, 'klass')
                if klass is None or klass == classname:
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
        return self.db.permission.create(**propspec)

    def addRole(self, **propspec):
        ''' Create a new Role with the properties defined in 'propspec'
        '''
        return self.db.role.create(**propspec)

    def addPermissionToRole(self, rolename, permissionid):
        ''' Add the permission to the role's permission list.

            'rolename' is the name of the role to add 'permissionid'.
        '''
        roleid = self.db.role.lookup(rolename)
        permissions = self.db.role.get(roleid, 'permissions')
        permissions.append(permissionid)
        self.db.role.set(roleid, permissions=permissions)

