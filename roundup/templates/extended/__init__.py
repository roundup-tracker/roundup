# $Id: __init__.py,v 1.5 2001-07-29 07:01:39 richard Exp $

from instance_config import *
try:
    from dbinit import *
except ImportError:
    pass # in installdir (probably :)
    
from interfaces import *

# 
# $Log: not supported by cvs2svn $
# Revision 1.4  2001/07/24 10:46:22  anthonybaxter
# Added templatebuilder module. two functions - one to pack up the html base,
# one to unpack it. Packed up the two standard templates into htmlbases.
# Modified __init__ to install them.
#
# __init__.py magic was needed for the rather high levels of wierd import magic.
# Reducing level of import magic == (good, future)
#
# Revision 1.3  2001/07/23 23:16:01  richard
# Split off the interfaces (CGI, mailgw) into a separate file from the DB stuff.
#
# Revision 1.2  2001/07/23 04:33:21  anthonybaxter
# split __init__.py into 2. dbinit and instance_config.
#
#
# vim: set filetype=python ts=4 sw=4 et si
