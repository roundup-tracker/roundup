# $Id: interfaces.py,v 1.5 2001-08-01 05:15:09 richard Exp $

import instance_config, urlparse, os
from roundup import cgi_client, mailgw 

class Client(cgi_client.Client): 
    ''' derives basic mail gateway implementation from the standard module, 
        with any specific extensions 
    ''' 
    TEMPLATES = instance_config.TEMPLATES
    showsupport = cgi_client.Client.shownode
    showtimelog = cgi_client.Client.shownode
    newsupport = cgi_client.Client.newnode
    newtimelog = cgi_client.Client.newnode

    default_index_sort = ['-activity']
    default_index_group = ['priority']
    default_index_filter = []
    default_index_columns = ['activity','status','title','assignedto']
    default_index_filterspec = {'status': ['1', '2', '3', '4', '5', '6', '7']}

    def pagehead(self, title, message=None):
        url = self.env['SCRIPT_NAME'] + '/' #self.env.get('PATH_INFO', '/')
        machine = self.env['SERVER_NAME']
        port = self.env['SERVER_PORT']
        if port != '80': machine = machine + ':' + port
        base = urlparse.urlunparse(('http', machine, url, None, None, None))
        if message is not None:
            message = '<div class="system-msg">%s</div>'%message
        else:
            message = ''
        style = open(os.path.join(self.TEMPLATES, 'style.css')).read()
        userid = self.db.user.lookup(self.user)
        if self.user == 'admin':
            extras = ' | <a href="list_classes">Class List</a>'
        else:
            extras = ''
        self.write('''<html><head>
<title>%s</title>
<style type="text/css">%s</style>
</head>
<body bgcolor=#ffffff>
%s
<table width=100%% border=0 cellspacing=0 cellpadding=2>
<tr class="location-bar"><td><big><strong>%s</strong></big></td>
<td align=right valign=bottom>%s</td></tr>
<tr class="location-bar">
<td align=left><a href="issue?status=unread,deferred,chatting,need-eg,in-progress,testing,done-cbb&:sort=activity&:columns=id,activity,status,title,assignedto&:group=priority">All issues</a> | 
<a href="issue?status=unread,deferred,chatting,need-eg,in-progress,testing,done-cbb&:sort=activity&:columns=id,activity,status,title,assignedto&priority=fatal-bug,bug">Bugs</a> | 
<a href="issue?status=unread,deferred,chatting,need-eg,in-progress,testing,done-cbb&:sort=activity&:columns=id,activity,status,title,assignedto&priority=usability,feature">Wishlist</a> | 
<a href="support?status=unread,deferred,chatting,need-eg,in-progress,testing,done-cbb&:sort=activity&:columns=id,activity,status,title,assignedto&:group=customername">Support</a> | 
<a href="newissue">New Issue</a> |
<a href="newsupport">New Support</a> |
<a href="newuser">New User</a>
%s</td>
<td align=right>
<a href="issue?assignedto=%s&status=unread,deferred,chatting,need-eg,in-progress,testing,done-cbb&:sort=activity&:columns=id,activity,status,title,assignedto&:group=priority">My Issues</a> |
<a href="support?assignedto=%s&status=unread,deferred,chatting,need-eg,in-progress,testing,done-cbb&:sort=activity&:columns=id,activity,status,title,assignedto&:group=customername">My Support</a> |
<a href="user%s">Your Details</a></td>
</table>
'''%(title, style, message, title, self.user, extras, userid, userid, userid))
 
class MailGW(mailgw.MailGW): 
    ''' derives basic mail gateway implementation from the standard module, 
        with any specific extensions 
    ''' 
    ISSUE_TRACKER_EMAIL = instance_config.ISSUE_TRACKER_EMAIL
    ADMIN_EMAIL = instance_config.ADMIN_EMAIL
    MAILHOST = instance_config.MAILHOST

#
# $Log: not supported by cvs2svn $
# Revision 1.4  2001/07/30 08:12:17  richard
# Added time logging and file uploading to the templates.
#
# Revision 1.3  2001/07/30 01:26:59  richard
# Big changes:
#  . split off the support priority into its own class
#  . added "new support, new user" to the page head
#  . fixed the display options for the heading links
#
# Revision 1.2  2001/07/29 07:01:39  richard
# Added vim command to all source so that we don't get no steenkin' tabs :)
#
# Revision 1.1  2001/07/23 23:16:01  richard
# Split off the interfaces (CGI, mailgw) into a separate file from the DB stuff.
#
#
# vim: set filetype=python ts=4 sw=4 et si
