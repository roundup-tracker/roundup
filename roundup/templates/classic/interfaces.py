# $Id: interfaces.py,v 1.1 2001-07-23 23:28:43 richard Exp $

import instance_config
from roundup import cgi_client, mailgw 

class Client(cgi_client.Client): 
    ''' derives basic mail gateway implementation from the standard module, 
        with any specific extensions 
    ''' 
    TEMPLATES = instance_config.TEMPLATES
    pass 
 
class MailGW(mailgw.MailGW): 
    ''' derives basic mail gateway implementation from the standard module, 
        with any specific extensions 
    ''' 
    ISSUE_TRACKER_EMAIL = instance_config.ISSUE_TRACKER_EMAIL
    ADMIN_EMAIL = instance_config.ADMIN_EMAIL
    MAILHOST = instance_config.MAILHOST

#
# $Log: not supported by cvs2svn $
# Revision 1.1  2001/07/23 23:16:01  richard
# Split off the interfaces (CGI, mailgw) into a separate file from the DB stuff.
#
#


