#$Id: __init__.py,v 1.1 2001-07-23 23:29:10 richard Exp $

def init(db):
    ''' execute the init functions of all the modules in this directory
    '''
    import os, sys
    this_dir = os.path.split(__file__)[0]
    try:
        sys.path.insert(0, this_dir)
        for file in os.listdir(this_dir):
            file, ext = os.path.splitext(file)
            if file == '__init__': continue
            if ext in ('.py', '.pyc'):
                module = __import__(file)
                module.init(db)
    finally:
        del sys.path[0]

#
#$Log: not supported by cvs2svn $
#Revision 1.1  2001/07/23 03:50:47  anthonybaxter
#moved templates to proper location
#
#Revision 1.1  2001/07/22 12:09:32  richard
#Final commit of Grande Splite
#
#
