import sys

from roundup import admin

class AdminTool(admin.AdminTool):
    def __init__(self):
        self.commands = admin.CommandDict()
        for k in AdminTool.__dict__.keys():
            if k[:3] == 'do_':
                self.commands[k[3:]] = getattr(self, k)
        self.help = {}
        for k in AdminTool.__dict__.keys():
            if k[:5] == 'help_':
                self.help[k[5:]] = getattr(self, k)
        self.instance_home = ''
        self.db = None

    def do_fixroles(self, args):
        '''Usage: fixroles
        Set the roles property for all users to reasonable defaults.

        The admin user gets "Admin", the anonymous user gets "Anonymous"
        and all other users get "User".
        '''
        # get the user class
        cl = self.get_class('user')
        for userid in cl.list():
            username = cl.get(userid, 'username')
            if username == 'admin':
                roles = 'Admin'
            elif username == 'anonymous':
                roles = 'Anonymous'
            else:
                roles = 'User'
            cl.set(userid, roles=roles)
        return 0

if __name__ == '__main__':
    tool = AdminTool()
    sys.exit(tool.main())
