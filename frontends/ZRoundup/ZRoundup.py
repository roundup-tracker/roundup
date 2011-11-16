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
''' ZRoundup module - exposes the roundup web interface to Zope

This frontend works by providing a thin layer that sits between Zope and the
regular CGI interface of roundup, providing the web frontend with the minimum
of effort.

This means that the regular CGI interface does all authentication quite
independently of Zope. The roundup code is kept in memory though, and it
runs in the same server as all your other Zope stuff, so it does have _some_
advantages over regular CGI :)
'''

import urlparse

from Globals import InitializeClass, HTMLFile
from OFS.SimpleItem import Item
from OFS.PropertyManager import PropertyManager
from Acquisition import Explicit, Implicit
from Persistence import Persistent
from AccessControl import ClassSecurityInfo
from AccessControl import ModuleSecurityInfo
modulesecurity = ModuleSecurityInfo()

import roundup.instance
from roundup.cgi import client

modulesecurity.declareProtected('View management screens',
    'manage_addZRoundupForm')
manage_addZRoundupForm = HTMLFile('dtml/manage_addZRoundupForm', globals())

modulesecurity.declareProtected('Add Z Roundups', 'manage_addZRoundup')
def manage_addZRoundup(self, id, instance_home, REQUEST):
    """Add a ZRoundup product """
    # validate the instance_home
    roundup.instance.open(instance_home)
    self._setObject(id, ZRoundup(id, instance_home))
    return self.manage_main(self, REQUEST)

class RequestWrapper:
    '''Make the Zope RESPONSE look like a BaseHTTPServer
    '''
    def __init__(self, RESPONSE):
        self.RESPONSE = RESPONSE
        self.wfile = self.RESPONSE
    def send_response(self, status):
        self.RESPONSE.setStatus(status)
    def send_header(self, header, value):
        self.RESPONSE.addHeader(header, value)
    def end_headers(self):
        # not needed - the RESPONSE object handles this internally on write()
        pass
    def start_response(self, headers, response):
        self.send_response(response)
        for key, value in headers:
            self.send_header(key, value)
        self.end_headers()

class FormItem:
    '''Make a Zope form item look like a cgi.py one
    '''
    def __init__(self, value):
        self.value = value
        if hasattr(self.value, 'filename'):
            self.filename = self.value.filename
            self.value = self.value.read()

class FormWrapper:
    '''Make a Zope form dict look like a cgi.py one
    '''
    def __init__(self, form):
        self.__form = form
    def __getitem__(self, item):
        entry = self.__form[item]
        if isinstance(entry, type([])):
            entry = map(FormItem, entry)
        else:
            entry = FormItem(entry)
        return entry
    def __iter__(self):
        return iter(self.__form)
    def getvalue(self, key, default=None):
        if self.__form.has_key(key):
            return self.__form[key]
        else:
            return default
    def has_key(self, item):
        return self.__form.has_key(item)
    def keys(self):
        return self.__form.keys()

    def __repr__(self):
        return '<ZRoundup.FormWrapper %r>'%self.__form

class ZRoundup(Item, PropertyManager, Implicit, Persistent):
    '''An instance of this class provides an interface between Zope and
       roundup for one roundup instance
    '''
    meta_type =  'Z Roundup'
    security = ClassSecurityInfo()

    def __init__(self, id, instance_home):
        self.id = id
        self.instance_home = instance_home

    # define the properties that define this object
    _properties = (
        {'id':'id', 'type': 'string', 'mode': 'w'},
        {'id':'instance_home', 'type': 'string', 'mode': 'w'},
    )
    property_extensible_schema__ = 0

    # define the tabs for the management interface
    manage_options= PropertyManager.manage_options + (
        {'label': 'View', 'action':'index_html'},
    ) + Item.manage_options

    icon = "misc_/ZRoundup/icon"

    security.declarePrivate('roundup_opendb')
    def roundup_opendb(self):
        '''Open the roundup instance database for a transaction.
        '''
        tracker = roundup.instance.open(self.instance_home)
        request = RequestWrapper(self.REQUEST['RESPONSE'])
        env = self.REQUEST.environ

        # figure out the path components to set
        url = urlparse.urlparse( self.absolute_url() )
        path = url[2]
        path_components = path.split( '/' )

        # special case when roundup is '/' in this virtual host,
        if path == "/" :
            env['SCRIPT_NAME'] = "/"
            env['TRACKER_NAME'] = ''
        else :
            # all but the last element is the path
            env['SCRIPT_NAME'] = '/'.join( path_components[:-1] )
            # the last element is the name
            env['TRACKER_NAME'] = path_components[-1]

        form = FormWrapper(self.REQUEST.form)
        if hasattr(tracker, 'Client'):
            return tracker.Client(tracker, request, env, form)
        return client.Client(tracker, request, env, form)

    security.declareProtected('View', 'index_html')
    def index_html(self):
        '''Alias index_html to roundup's index
        '''
        # Redirect misdirected requests -- bugs 558867 , 565992
        # PATH_INFO, as defined by the CGI spec, has the *real* request path
        orig_path = self.REQUEST.environ['PATH_INFO']
        if orig_path[-1] != '/' : 
            url = urlparse.urlparse( self.absolute_url() )
            url = list( url ) # make mutable
            url[2] = url[2]+'/' # patch
            url = urlparse.urlunparse( url ) # reassemble
            RESPONSE = self.REQUEST.RESPONSE
            RESPONSE.setStatus( "MovedPermanently" ) # 301
            RESPONSE.setHeader( "Location" , url )
            return RESPONSE

        client = self.roundup_opendb()
        # fake the path that roundup should use
        client.split_path = ['index']
        return client.main()

    def __getitem__(self, item):
        '''All other URL accesses are passed throuh to roundup
        '''
        return PathElement(self, item).__of__(self)

class PathElement(Item, Implicit):
    def __init__(self, zr, path):
        self.zr = zr
        self.path = path

    def __getitem__(self, item):
        ''' Get a subitem.
        '''
        return PathElement(self.zr, self.path + '/' + item).__of__(self)

    def index_html(self, REQUEST=None):
        ''' Actually call through to roundup to handle the request.
        '''
        try:
            client = self.zr.roundup_opendb()
            # fake the path that roundup should use
            client.path = self.path
            # and call roundup to do something 
            client.main()
            return ''
        except client.NotFound:
            raise 'NotFound', REQUEST.URL
            pass
        except:
            import traceback
            traceback.print_exc()
            # all other exceptions in roundup are valid
            raise

InitializeClass(ZRoundup)
modulesecurity.apply(globals())


# vim: set filetype=python ts=4 sw=4 et si
