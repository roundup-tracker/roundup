#
# Copyright (c) 2001 Bizar Software Pty Ltd (http://www.bizarsoftware.com.au/)
# This module is free software, and you may redistribute it and/or modify
# under the same terms as Python, so long as this copyright message and
# disclaimer are retained in their original form.
#
# IN NO EVENT SHALL BIZAR SOFTWARE PTY LTD BE LIABLE TO ANY PARTY FOR
# DIRECT, INDIRECT, SPECIAL, INCIDENTAL, OR CONSEQUENTIAL DAMAGES ARISING
# OUT OF THE USE OF THIS CODE, EVEN IF THE AUTHOR HAS BEEN ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.
#
# BIZAR SOFTWARE PTY LTD SPECIFICALLY DISCLAIMS ANY WARRANTIES, INCLUDING,
# BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS
# FOR A PARTICULAR PURPOSE.  THE CODE PROVIDED HEREUNDER IS ON AN "AS IS"
# BASIS, AND THERE IS NO OBLIGATION WHATSOEVER TO PROVIDE MAINTENANCE,
# SUPPORT, UPDATES, ENHANCEMENTS, OR MODIFICATIONS.
# 
#$Id: __init__.py,v 1.4 2002-05-29 01:16:17 richard Exp $

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
#Revision 1.3  2001/08/07 00:24:43  richard
#stupid typo
#
#Revision 1.2  2001/08/07 00:15:51  richard
#Added the copyright/license notice to (nearly) all files at request of
#Bizar Software.
#
#Revision 1.1  2001/07/23 23:29:10  richard
#Adding the classic template
#
#Revision 1.1  2001/07/23 03:50:47  anthonybaxter
#moved templates to proper location
#
#Revision 1.1  2001/07/22 12:09:32  richard
#Final commit of Grande Splite
#
#
