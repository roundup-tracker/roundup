"""
Restful API for Roundup

This module is free software, you may redistribute it
and/or modify under the same terms as Python.
"""

from __future__ import print_function

try:
    from urllib.parse import urlparse
except ImportError:
    from urlparse import urlparse
import os
import json
import pprint
import sys
import time
import traceback
import re

try:
    from dicttoxml import dicttoxml
except ImportError:
    dicttoxml = None

from roundup import hyperdb
from roundup import date
from roundup import actions
from roundup.exceptions import *
from roundup.cgi.exceptions import *

from hashlib import md5

# Py3 compatible basestring
try:
    basestring
except NameError:
    basestring = str
    unicode = str

import logging
logger = logging.getLogger('roundup.rest')

def _data_decorator(func):
    """Wrap the returned data into an object."""
    def format_object(self, *args, **kwargs):
        # get the data / error from function
        try:
            code, data = func(self, *args, **kwargs)
        except NotFound as msg:
            code = 404
            data = msg
        except IndexError as msg:
            code = 404
            data = msg
        except Unauthorised as msg:
            code = 403
            data = msg
        except UsageError as msg:
            code = 400
            data = msg
        except (AttributeError, Reject) as msg:
            code = 405
            data = msg
        except ValueError as msg:
            code = 409
            data = msg
        except PreconditionFailed as msg:
            code = 412
            data = msg
        except NotImplementedError:
            code = 402  # nothing to pay, just a mark for debugging purpose
            data = 'Method under development'
        except:
            exc, val, tb = sys.exc_info()
            code = 400
            ts = time.ctime()
            if getattr (self.client.request, 'DEBUG_MODE', None):
                data = val
            else:
                data = '%s: An error occurred. Please check the server log' \
                       ' for more information.' % ts
            # out to the logfile
            print ('EXCEPTION AT', ts)
            traceback.print_exc()

        # decorate it
        self.client.response_code = code
        if code >= 400:  # any error require error format
            result = {
                'error': {
                    'status': code,
                    'msg': data
                }
            }
        else:
            result = {
                'data': data
            }
        return result
    return format_object

def calculate_etag (node, classname="Missing", id="0"):
    '''given a hyperdb node generate a hashed representation of it to be
    used as an etag.

    This code needs a __repr__ function in the Password class. This
    replaces the repr(items) which would be:

      <roundup.password.Password instance at 0x7f3442406170>

    with the string representation:

       {PBKDF2}10000$k4d74EDgxlbH...A

    This makes the representation repeatable as the location of the
    password instance is not static and we need a constant value to
    calculate the etag.

    Note that repr() is chosen for the node rather than str() since
    repr is meant to be an unambiguous representation.

    classname and id are used for logging only.
    '''

    items = node.items(protected=True) # include every item
    etag = md5(repr(items)).hexdigest()
    logger.debug("object=%s%s; tag=%s; repr=%s", classname, id,
                 etag, repr(node.items(protected=True)))
    return etag

def check_etag (node, etags, classname="Missing", id="0"):
    '''Take a list of etags and compare to the etag for the given node.

    Iterate over all supplied etags,
       If a tag fails to match, return False.
       If at least one etag matches, return True.
       If all etags are None, return False.

    '''
    have_etag_match=False

    node_etag = calculate_etag(node, classname, id)

    for etag in etags:
        if etag != None:
            if etag != node_etag:
                return False
            have_etag_match=True

    if have_etag_match:
        return True
    else:
        return False

def obtain_etags(headers,input):
    '''Get ETags value from headers or payload data'''
    etags = []
    if '@etag' in input:
        etags.append(input['@etag'].value);
    etags.append(headers.getheader("ETag", None))
    return etags

def parse_accept_header(accept):
    """
    Parse the Accept header *accept*, returning a list with 3-tuples of
    [(str(media_type), dict(params), float(q_value)),] ordered by q values.

    If the accept header includes vendor-specific types like::
        application/vnd.yourcompany.yourproduct-v1.1+json

    It will actually convert the vendor and version into parameters and
    convert the content type into `application/json` so appropriate content
    negotiation decisions can be made.

    Default `q` for values that are not specified is 1.0

    # Based on https://gist.github.com/samuraisam/2714195
    # Also, based on a snipped found in this project:
    #   https://github.com/martinblech/mimerender
    """
    result = []
    for media_range in accept.split(","):
        parts = media_range.split(";")
        media_type = parts.pop(0).strip()
        media_params = []
        # convert vendor-specific content types into something useful (see
        # docstring)
        typ, subtyp = media_type.split('/')
        # check for a + in the sub-type
        if '+' in subtyp:
            # if it exists, determine if the subtype is a vendor-specific type
            vnd, sep, extra = subtyp.partition('+')
            if vnd.startswith('vnd'):
                # and then... if it ends in something like "-v1.1" parse the
                # version out
                if '-v' in vnd:
                    vnd, sep, rest = vnd.rpartition('-v')
                    if len(rest):
                        # add the version as a media param
                        try:
                            version = media_params.append(('version',
                                                           float(rest)))
                        except ValueError:
                            version = 1.0  # could not be parsed
                # add the vendor code as a media param
                media_params.append(('vendor', vnd))
                # and re-write media_type to something like application/json so
                # it can be used usefully when looking up emitters
                media_type = '{}/{}'.format(typ, extra)
        q = 1.0
        for part in parts:
            (key, value) = part.lstrip().split("=", 1)
            key = key.strip()
            value = value.strip()
            if key == "q":
                q = float(value)
            else:
                media_params.append((key, value))
        result.append((media_type, dict(media_params), q))
    result.sort(lambda x, y: -cmp(x[2], y[2]))
    return result


class Routing(object):
    __route_map = {}
    __var_to_regex = re.compile(r"<:(\w+)>")
    url_to_regex = r"([\w.\-~!$&'()*+,;=:@\%%]+)"

    @classmethod
    def route(cls, rule, methods='GET'):
        """A decorator that is used to register a view function for a
        given URL rule:
            @self.route('/')
            def index():
                return 'Hello World'

        rest/ will be added to the beginning of the url string

        Args:
            rule (string): the URL rule
            methods (string or tuple or list): the http method
        """
        # strip the '/' character from rule string
        rule = rule.strip('/')

        # add 'rest/' to the rule string
        if not rule.startswith('rest/'):
            rule = '^rest/' + rule + '$'

        if isinstance(methods, basestring):  # convert string to tuple
            methods = (methods,)
        methods = set(item.upper() for item in methods)

        # convert a rule to a compiled regex object
        # so /data/<:class>/<:id> will become
        #    /data/([charset]+)/([charset]+)
        # and extract the variable names to a list [(class), (id)]
        func_vars = cls.__var_to_regex.findall(rule)
        rule = re.compile(cls.__var_to_regex.sub(cls.url_to_regex, rule))

        # then we decorate it:
        # route_map[regex][method] = func
        def decorator(func):
            rule_route = cls.__route_map.get(rule, {})
            func_obj = {
                'func': func,
                'vars': func_vars
            }
            for method in methods:
                rule_route[method] = func_obj
            cls.__route_map[rule] = rule_route
            return func
        return decorator

    @classmethod
    def execute(cls, instance, path, method, input):
        # format the input
        path = path.strip('/').lower()
        if path == 'rest':
            # allow handler to be called for /rest/
            path = 'rest/'
        method = method.upper()

        # find the rule match the path
        # then get handler match the method
        for path_regex in cls.__route_map:
            match_obj = path_regex.match(path)
            if match_obj:
                try:
                    func_obj = cls.__route_map[path_regex][method]
                except KeyError:
                    raise Reject('Method %s not allowed' % method)

                # retrieve the vars list and the function caller
                list_vars = func_obj['vars']
                func = func_obj['func']

                # zip the varlist into a dictionary, and pass it to the caller
                args = dict(zip(list_vars, match_obj.groups()))
                args['input'] = input
                return func(instance, **args)
        raise NotFound('Nothing matches the given URI')


class RestfulInstance(object):
    """The RestfulInstance performs REST request from the client"""

    __default_patch_op = "replace"  # default operator for PATCH method
    __accepted_content_type = {
        "application/json": "json",
        "*/*": "json",
        "application/xml": "xml"
    }
    __default_accept_type = "json"

    def __init__(self, client, db):
        self.client = client
        self.db = db
        self.translator = client.translator
        # This used to be initialized from client.instance.actions which
        # would include too many actions that do not make sense in the
        # REST-API context, so for now we only permit the retire and
        # restore actions.
        self.actions = dict (retire = actions.Retire, restore = actions.Restore)

        # note TRACKER_WEB ends in a /
        self.base_path = '%srest' % (self.db.config.TRACKER_WEB)
        self.data_path = self.base_path + '/data'

    def props_from_args(self, cl, args, itemid=None):
        """Construct a list of properties from the given arguments,
        and return them after validation.

        Args:
            cl (string): class object of the resource
            args (list): the submitted form of the user
            itemid (string, optional): itemid of the object

        Returns:
            dict: dictionary of validated properties

        """
        class_props = cl.properties.keys()
        props = {}
        # props = dict.fromkeys(class_props, None)

        for arg in args:
            key = arg.name
            value = arg.value
            if key not in class_props:
                continue
            props[key] = self.prop_from_arg(cl, key, value, itemid)

        return props

    def prop_from_arg(self, cl, key, value, itemid=None):
        """Construct a property from the given argument,
        and return them after validation.

        Args:
            cl (string): class object of the resource
            key (string): attribute key
            value (string): attribute value
            itemid (string, optional): itemid of the object

        Returns:
            value: value of validated properties

        """
        prop = None
        if isinstance(key, unicode):
            try:
                x = key.encode('ascii')
            except UnicodeEncodeError:
                raise UsageError(
                    'argument %r is no valid ascii keyword' % key
                )
        if value:
            try:
                prop = hyperdb.rawToHyperdb(self.db, cl, itemid, key, value)
            except hyperdb.HyperdbValueError as msg:
                raise UsageError(msg)

        return prop

    def error_obj(self, status, msg, source=None):
        """Return an error object"""
        self.client.response_code = status
        result = {
            'error': {
                'status': status,
                'msg': msg
            }
        }
        if source is not None:
            result['error']['source'] = source

        return result

    def patch_data(self, op, old_val, new_val):
        """Perform patch operation based on old_val and new_val

        Args:
            op (string): PATCH operation: add, replace, remove
            old_val: old value of the property
            new_val: new value of the property

        Returns:
            result (string): value after performed the operation
        """
        # add operation: If neither of the value is None, use the other one
        #                Otherwise, concat those 2 value
        if op == 'add':
            if old_val is None:
                result = new_val
            elif new_val is None:
                result = old_val
            else:
                result = old_val + new_val
        # Replace operation: new value is returned
        elif op == 'replace':
            result = new_val
        # Remove operation:
        #   if old_val is not a list/dict, change it to None
        #   if old_val is a list/dict, but the parameter is empty,
        #       change it to none
        #   if old_val is a list/dict, and parameter is not empty
        #       proceed to remove the values from parameter from the list/dict
        elif op == 'remove':
            if isinstance(old_val, list):
                if new_val is None:
                    result = []
                elif isinstance(new_val, list):
                    result = [x for x in old_val if x not in new_val]
                else:
                    if new_val in old_val:
                        old_val.remove(new_val)
            elif isinstance(old_val, dict):
                if new_val is None:
                    result = {}
                elif isinstance(new_val, dict):
                    for x in new_val:
                        old_val.pop(x, None)
                else:
                    old_val.pop(new_val, None)
            else:
                result = None
        else:
            raise UsageError('PATCH Operation %s is not allowed' % op)

        return result

    @Routing.route("/data/<:class_name>", 'GET')
    @_data_decorator
    def get_collection(self, class_name, input):
        """GET resource from class URI.

        This function returns only items have View permission
        class_name should be valid already

        Args:
            class_name (string): class name of the resource (Ex: issue, msg)
            input (list): the submitted form of the user

        Returns:
            int: http status code 200 (OK)
            list: list of reference item in the class
                id: id of the object
                link: path to the object
        """
        if class_name not in self.db.classes:
            raise NotFound('Class %s not found' % class_name)
        if not self.db.security.hasPermission(
            'View', self.db.getuid(), class_name
        ):
            raise Unauthorised('Permission to view %s denied' % class_name)

        class_obj = self.db.getclass(class_name)
        class_path = '%s/%s/' % (self.data_path, class_name)

        # Handle filtering and pagination
        filter_props = {}
        page = {
            'size': None,
            'index': 1   # setting just size starts at page 1
        }
        for form_field in input.value:
            key = form_field.name
            value = form_field.value
            if key.startswith("where_"):  # serve the filter purpose
                key = key[6:]
                filter_props[key] = [
                    getattr(self.db, key).lookup(p)
                    for p in value.split(",")
                ]
            elif key.startswith("page_"):  # serve the paging purpose
                key = key[5:]
                value = int(value)
                page[key] = value

        if not filter_props:
            obj_list = class_obj.list()
        else:
            obj_list = class_obj.filter(None, filter_props)

        # extract result from data
        result={}
        result['collection'] = [
            {'id': item_id, 'link': class_path + item_id}
            for item_id in obj_list
            if self.db.security.hasPermission(
                'View', self.db.getuid(), class_name, itemid=item_id
            )
        ]
        result_len = len(result['collection'])

        # pagination - page_index from 1...N
        if page['size'] is not None:
            page_start = max((page['index']-1) * page['size'], 0)
            page_end = min(page_start + page['size'], result_len)
            result['collection'] = result['collection'][page_start:page_end]
            result['@links'] = {}
            for rel in ('next', 'prev', 'self'):
                if rel == 'next':
                    # if current index includes all data, continue
                    if page['index']*page['size'] > result_len: continue
                    index=page['index']+1
                if rel == 'prev':
                    if page['index'] <= 1: continue
                    index=page['index']-1
                if rel == 'self': index=page['index']

                result['@links'][rel] = []
                result['@links'][rel].append({
                    'rel': rel,
                    'uri': "%s/%s?page_index=%s&"%(self.data_path,
                                                   class_name,index) \
                       + '&'.join([ "%s=%s"%(field.name,field.value) \
                         for field in input.value \
                           if field.name != "page_index"]) })

        result['@total_size'] = result_len
        self.client.setHeader("X-Count-Total", str(result_len))
        return 200, result

    @Routing.route("/data/<:class_name>/<:item_id>", 'GET')
    @_data_decorator
    def get_element(self, class_name, item_id, input):
        """GET resource from object URI.

        This function returns only properties have View permission
        class_name and item_id should be valid already

        Args:
            class_name (string): class name of the resource (Ex: issue, msg)
            item_id (string): id of the resource (Ex: 12, 15)
            input (list): the submitted form of the user

        Returns:
            int: http status code 200 (OK)
            dict: a dictionary represents the object
                id: id of the object
                type: class name of the object
                link: link to the object
                attributes: a dictionary represent the attributes of the object
        """
        if class_name not in self.db.classes:
            raise NotFound('Class %s not found' % class_name)
        if not self.db.security.hasPermission(
            'View', self.db.getuid(), class_name, itemid=item_id
        ):
            raise Unauthorised(
                'Permission to view %s%s denied' % (class_name, item_id)
            )

        class_obj = self.db.getclass(class_name)
        node = class_obj.getnode(item_id)
        etag = calculate_etag(node, class_name, item_id)
        props = None
        protected=False
        for form_field in input.value:
            key = form_field.name
            value = form_field.value
            if key == "fields":
                props = value.split(",")
            if key == "@protected":
                # allow client to request read only
                # properties like creator, activity etc.
                protected = value.lower() == "true"

        if props is None:
            props = list(sorted(class_obj.getprops(protected=protected)))

        try:
            result = [
                (prop_name, node.__getattr__(prop_name))
                for prop_name in props
                if self.db.security.hasPermission(
                    'View', self.db.getuid(), class_name, prop_name,
                        item_id )
            ]
        except KeyError as msg:
            raise UsageError("%s field not valid" % msg)
        result = {
            'id': item_id,
            'type': class_name,
            'link': '%s/%s/%s' % (self.data_path, class_name, item_id),
            'attributes': dict(result),
            '@etag': etag
        }

        self.client.setHeader("ETag", '"%s"'%etag)
        return 200, result

    @Routing.route("/data/<:class_name>/<:item_id>/<:attr_name>", 'GET')
    @_data_decorator
    def get_attribute(self, class_name, item_id, attr_name, input):
        """GET resource from attribute URI.

        This function returns only attribute has View permission
        class_name should be valid already

        Args:
            class_name (string): class name of the resource (Ex: issue, msg)
            item_id (string): id of the resource (Ex: 12, 15)
            attr_name (string): attribute of the resource (Ex: title, nosy)
            input (list): the submitted form of the user

        Returns:
            int: http status code 200 (OK)
            list: a dictionary represents the attribute
                id: id of the object
                type: class name of the attribute
                link: link to the attribute
                data: data of the requested attribute
        """
        if class_name not in self.db.classes:
            raise NotFound('Class %s not found' % class_name)
        if not self.db.security.hasPermission(
            'View', self.db.getuid(), class_name, attr_name, item_id
        ):
            raise Unauthorised(
                'Permission to view %s%s %s denied' %
                (class_name, item_id, attr_name)
            )

        class_obj = self.db.getclass(class_name)
        node = class_obj.getnode(item_id)
        etag = calculate_etag(node, class_name, item_id)
        data = node.__getattr__(attr_name)
        result = {
            'id': item_id,
            'type': str(type(data)),
            'link': "%s/%s/%s/%s" %
                    (self.data_path, class_name, item_id, attr_name),
            'data': data,
            '@etag': etag
        }

        self.client.setHeader("ETag", '"%s"'%etag )
        return 200, result

    @Routing.route("/data/<:class_name>", 'POST')
    @_data_decorator
    def post_collection(self, class_name, input):
        """POST a new object to a class

        If the item is successfully created, the "Location" header will also
        contain the link to the created object

        Args:
            class_name (string): class name of the resource (Ex: issue, msg)
            input (list): the submitted form of the user

        Returns:
            int: http status code 201 (Created)
            dict: a reference item to the created object
                id: id of the object
                link: path to the object
        """
        if class_name not in self.db.classes:
            raise NotFound('Class %s not found' % class_name)
        if not self.db.security.hasPermission(
            'Create', self.db.getuid(), class_name
        ):
            raise Unauthorised('Permission to create %s denied' % class_name)

        class_obj = self.db.getclass(class_name)

        # convert types
        props = self.props_from_args(class_obj, input.value)

        # check for the key property
        key = class_obj.getkey()
        if key and key not in props:
            raise UsageError("Must provide the '%s' property." % key)

        for key in props:
            if not self.db.security.hasPermission(
                'Create', self.db.getuid(), class_name, property=key
            ):
                raise Unauthorised(
                    'Permission to create %s.%s denied' % (class_name, key)
                )

        # do the actual create
        try:
            item_id = class_obj.create(**props)
            self.db.commit()
        except (TypeError, IndexError, ValueError) as message:
            raise ValueError(message)
        except KeyError as msg:
            raise UsageError("Must provide the %s property." % msg)

        # set the header Location
        link = '%s/%s/%s' % (self.data_path, class_name, item_id)
        self.client.setHeader("Location", link)

        # set the response body
        result = {
            'id': item_id,
            'link': link
        }
        return 201, result

    @Routing.route("/data/<:class_name>/<:item_id>", 'PUT')
    @_data_decorator
    def put_element(self, class_name, item_id, input):
        """PUT a new content to an object

        Replace the content of the existing object

        Args:
            class_name (string): class name of the resource (Ex: issue, msg)
            item_id (string): id of the resource (Ex: 12, 15)
            input (list): the submitted form of the user

        Returns:
            int: http status code 200 (OK)
            dict: a dictionary represents the modified object
                id: id of the object
                type: class name of the object
                link: link to the object
                attributes: a dictionary represent only changed attributes of
                            the object
        """
        if class_name not in self.db.classes:
            raise NotFound('Class %s not found' % class_name)
        class_obj = self.db.getclass(class_name)

        props = self.props_from_args(class_obj, input.value, item_id)
        for p in props:
            if not self.db.security.hasPermission(
                'Edit', self.db.getuid(), class_name, p, item_id
            ):
                raise Unauthorised(
                    'Permission to edit %s of %s%s denied' %
                    (p, class_name, item_id)
                )
        try:
            if not check_etag(class_obj.getnode(item_id),
                       obtain_etags(self.client.request.headers, input),
                       class_name,
                       item_id):
                raise PreconditionFailed("Etag is missing or does not match."
                        "Retreive asset and retry modification if valid.")
            result = class_obj.set(item_id, **props)
            self.db.commit()
        except (TypeError, IndexError, ValueError) as message:
            raise ValueError(message)

        result = {
            'id': item_id,
            'type': class_name,
            'link': '%s/%s/%s' % (self.data_path, class_name, item_id),
            'attribute': result
        }
        return 200, result

    @Routing.route("/data/<:class_name>/<:item_id>/<:attr_name>", 'PUT')
    @_data_decorator
    def put_attribute(self, class_name, item_id, attr_name, input):
        """PUT an attribute to an object

        Args:
            class_name (string): class name of the resource (Ex: issue, msg)
            item_id (string): id of the resource (Ex: 12, 15)
            attr_name (string): attribute of the resource (Ex: title, nosy)
            input (list): the submitted form of the user

        Returns:
            int: http status code 200 (OK)
            dict:a dictionary represents the modified object
                id: id of the object
                type: class name of the object
                link: link to the object
                attributes: a dictionary represent only changed attributes of
                            the object
        """
        if class_name not in self.db.classes:
            raise NotFound('Class %s not found' % class_name)
        if not self.db.security.hasPermission(
            'Edit', self.db.getuid(), class_name, attr_name, item_id
        ):
            raise Unauthorised(
                'Permission to edit %s%s %s denied' %
                (class_name, item_id, attr_name)
            )
        class_obj = self.db.getclass(class_name)
        props = {
            attr_name: self.prop_from_arg(
                class_obj, attr_name, input['data'].value, item_id
            )
        }

        try:
            if not check_etag(class_obj.getnode(item_id),
                        obtain_etags(self.client.request.headers, input),
                        class_name, item_id):
                raise PreconditionFailed("Etag is missing or does not match."
                        "Retreive asset and retry modification if valid.")
            result = class_obj.set(item_id, **props)
            self.db.commit()
        except (TypeError, IndexError, ValueError) as message:
            raise ValueError(message)

        result = {
            'id': item_id,
            'type': class_name,
            'link': '%s/%s/%s' % (self.data_path, class_name, item_id),
            'attribute': result
        }

        return 200, result

    @Routing.route("/data/<:class_name>", 'DELETE')
    @_data_decorator
    def delete_collection(self, class_name, input):
        """DELETE (retire) all objects in a class
           There is currently no use-case, so this is disabled and
           always returns Unauthorised.

        Args:
            class_name (string): class name of the resource (Ex: issue, msg)
            input (list): the submitted form of the user

        Returns:
            int: http status code 200 (OK)
            dict:
                status (string): 'ok'
                count (int): number of deleted objects
        """
        raise Unauthorised('Deletion of a whole class disabled')
        if class_name not in self.db.classes:
            raise NotFound('Class %s not found' % class_name)
        if not self.db.security.hasPermission(
            'Retire', self.db.getuid(), class_name
        ):
            raise Unauthorised('Permission to delete %s denied' % class_name)

        class_obj = self.db.getclass(class_name)
        for item_id in class_obj.list():
            if not self.db.security.hasPermission(
                'Retire', self.db.getuid(), class_name, itemid=item_id
            ):
                raise Unauthorised(
                    'Permission to retire %s %s denied' % (class_name, item_id)
                )

        count = len(class_obj.list())
        for item_id in class_obj.list():
            class_obj.retire (item_id)

        self.db.commit()
        result = {
            'status': 'ok',
            'count': count
        }

        return 200, result

    @Routing.route("/data/<:class_name>/<:item_id>", 'DELETE')
    @_data_decorator
    def delete_element(self, class_name, item_id, input):
        """DELETE (retire) an object in a class

        Args:
            class_name (string): class name of the resource (Ex: issue, msg)
            item_id (string): id of the resource (Ex: 12, 15)
            input (list): the submitted form of the user

        Returns:
            int: http status code 200 (OK)
            dict:
                status (string): 'ok'
        """
        if class_name not in self.db.classes:
            raise NotFound('Class %s not found' % class_name)
        class_obj = self.db.classes [class_name]
        if not self.db.security.hasPermission(
            'Retire', self.db.getuid(), class_name, itemid=item_id
        ):
            raise Unauthorised(
                'Permission to retire %s %s denied' % (class_name, item_id)
            )

        if not check_etag(class_obj.getnode(item_id),
                obtain_etags(self.client.request.headers, input),
                class_name,
                item_id):
            raise PreconditionFailed("Etag is missing or does not match."
                        "Retreive asset and retry modification if valid.")

        class_obj.retire (item_id)
        self.db.commit()
        result = {
            'status': 'ok'
        }

        return 200, result

    @Routing.route("/data/<:class_name>/<:item_id>/<:attr_name>", 'DELETE')
    @_data_decorator
    def delete_attribute(self, class_name, item_id, attr_name, input):
        """DELETE an attribute in a object by setting it to None or empty

        Args:
            class_name (string): class name of the resource (Ex: issue, msg)
            item_id (string): id of the resource (Ex: 12, 15)
            attr_name (string): attribute of the resource (Ex: title, nosy)
            input (list): the submitted form of the user

        Returns:
            int: http status code 200 (OK)
            dict:
                status (string): 'ok'
        """
        if class_name not in self.db.classes:
            raise NotFound('Class %s not found' % class_name)
        if not self.db.security.hasPermission(
            'Edit', self.db.getuid(), class_name, attr_name, item_id
        ):
            raise Unauthorised(
                'Permission to delete %s%s %s denied' %
                (class_name, item_id, attr_name)
            )

        class_obj = self.db.getclass(class_name)
        props = {}
        prop_obj = class_obj.get(item_id, attr_name)
        if isinstance(prop_obj, list):
            props[attr_name] = []
        else:
            props[attr_name] = None

        try:
            if not check_etag(class_obj.getnode(item_id),
                       obtain_etags(self.client.request.headers, input),
                       class_name,
                       item_id):
                raise PreconditionFailed("Etag is missing or does not match."
                        "Retreive asset and retry modification if valid.")

            class_obj.set(item_id, **props)
            self.db.commit()
        except (TypeError, IndexError, ValueError) as message:
            raise ValueError(message)

        result = {
            'status': 'ok'
        }

        return 200, result

    @Routing.route("/data/<:class_name>/<:item_id>", 'PATCH')
    @_data_decorator
    def patch_element(self, class_name, item_id, input):
        """PATCH an object

        Patch an element using 3 operators
        ADD : Append new value to the object's attribute
        REPLACE: Replace object's attribute
        REMOVE: Clear object's attribute

        Args:
            class_name (string): class name of the resource (Ex: issue, msg)
            item_id (string): id of the resource (Ex: 12, 15)
            input (list): the submitted form of the user

        Returns:
            int: http status code 200 (OK)
            dict: a dictionary represents the modified object
                id: id of the object
                type: class name of the object
                link: link to the object
                attributes: a dictionary represent only changed attributes of
                            the object
        """
        if class_name not in self.db.classes:
            raise NotFound('Class %s not found' % class_name)
        try:
            op = input['op'].value.lower()
        except KeyError:
            op = self.__default_patch_op
        class_obj = self.db.getclass(class_name)

        if not check_etag(class_obj.getnode(item_id),
                obtain_etags(self.client.request.headers, input),
                class_name,
                item_id):
            raise PreconditionFailed("Etag is missing or does not match."
                        "Retreive asset and retry modification if valid.")

        # if patch operation is action, call the action handler
        action_args = [class_name + item_id]
        if op == 'action':
            # extract action_name and action_args from form fields
            for form_field in input.value:
                key = form_field.name
                value = form_field.value
                if key == "action_name":
                    name = value
                elif key.startswith('action_args'):
                    action_args.append(value)

            if name in self.actions:
                action_type = self.actions[name]
            else:
                raise UsageError(
                    'action "%s" is not supported %s' %
                    (name, ','.join(self.actions.keys()))
                )
            action = action_type(self.db, self.translator)
            result = action.execute(*action_args)

            result = {
                'id': item_id,
                'type': class_name,
                'link': '%s/%s/%s' % (self.data_path, class_name, item_id),
                'result': result
            }
        else:
            # else patch operation is processing data
            props = self.props_from_args(class_obj, input.value, item_id)

            for prop in props:
                if not self.db.security.hasPermission(
                    'Edit', self.db.getuid(), class_name, prop, item_id
                ):
                    raise Unauthorised(
                        'Permission to edit %s of %s%s denied' %
                        (prop, class_name, item_id)
                    )

                props[prop] = self.patch_data(
                    op, class_obj.get(item_id, prop), props[prop]
                )

            try:
                result = class_obj.set(item_id, **props)
                self.db.commit()
            except (TypeError, IndexError, ValueError) as message:
                raise ValueError(message)

            result = {
                'id': item_id,
                'type': class_name,
                'link': '%s/%s/%s' % (self.data_path, class_name, item_id),
                'attribute': result
            }
        return 200, result

    @Routing.route("/data/<:class_name>/<:item_id>/<:attr_name>", 'PATCH')
    @_data_decorator
    def patch_attribute(self, class_name, item_id, attr_name, input):
        """PATCH an attribute of an object

        Patch an element using 3 operators
        ADD : Append new value to the attribute
        REPLACE: Replace attribute
        REMOVE: Clear attribute

        Args:
            class_name (string): class name of the resource (Ex: issue, msg)
            item_id (string): id of the resource (Ex: 12, 15)
            attr_name (string): attribute of the resource (Ex: title, nosy)
            input (list): the submitted form of the user

        Returns:
            int: http status code 200 (OK)
            dict: a dictionary represents the modified object
                id: id of the object
                type: class name of the object
                link: link to the object
                attributes: a dictionary represent only changed attributes of
                            the object
        """
        if class_name not in self.db.classes:
            raise NotFound('Class %s not found' % class_name)
        try:
            op = input['op'].value.lower()
        except KeyError:
            op = self.__default_patch_op

        if not self.db.security.hasPermission(
            'Edit', self.db.getuid(), class_name, attr_name, item_id
        ):
            raise Unauthorised(
                'Permission to edit %s%s %s denied' %
                (class_name, item_id, attr_name)
            )

        prop = attr_name
        class_obj = self.db.getclass(class_name)

        if not check_etag(class_obj.getnode(item_id),
                obtain_etags(self.client.request.headers, input),
                class_name,
                item_id):
            raise PreconditionFailed("Etag is missing or does not match."
                        "Retreive asset and retry modification if valid.")

        props = {
            prop: self.prop_from_arg(
                class_obj, prop, input['data'].value, item_id
            )
        }

        props[prop] = self.patch_data(
            op, class_obj.get(item_id, prop), props[prop]
        )

        try:
            result = class_obj.set(item_id, **props)
            self.db.commit()
        except (TypeError, IndexError, ValueError) as message:
            raise ValueError(message)

        result = {
            'id': item_id,
            'type': class_name,
            'link': '%s/%s/%s' % (self.data_path, class_name, item_id),
            'attribute': result
        }
        return 200, result

    @Routing.route("/data/<:class_name>", 'OPTIONS')
    @_data_decorator
    def options_collection(self, class_name, input):
        """OPTION return the HTTP Header for the class uri

        Returns:
            int: http status code 204 (No content)
            body (string): an empty string
        """
        if class_name not in self.db.classes:
            raise NotFound('Class %s not found' % class_name)
        return 204, ""

    @Routing.route("/data/<:class_name>/<:item_id>", 'OPTIONS')
    @_data_decorator
    def options_element(self, class_name, item_id, input):
        """OPTION return the HTTP Header for the object uri

        Returns:
            int: http status code 204 (No content)
            body (string): an empty string
        """
        if class_name not in self.db.classes:
            raise NotFound('Class %s not found' % class_name)
        self.client.setHeader(
            "Accept-Patch",
            "application/x-www-form-urlencoded, multipart/form-data"
        )
        return 204, ""

    @Routing.route("/data/<:class_name>/<:item_id>/<:attr_name>", 'OPTIONS')
    @_data_decorator
    def option_attribute(self, class_name, item_id, attr_name, input):
        """OPTION return the HTTP Header for the attribute uri

        Returns:
            int: http status code 204 (No content)
            body (string): an empty string
        """
        if class_name not in self.db.classes:
            raise NotFound('Class %s not found' % class_name)
        self.client.setHeader(
            "Accept-Patch",
            "application/x-www-form-urlencoded, multipart/form-data"
        )
        return 204, ""

    @Routing.route("/")
    @_data_decorator
    def describe(self, input):
        """Describe the rest endpoint"""
        result = {
            "default_version": "1",
            "supported_versions": [ "1" ],
            "links": [ { "uri": self.base_path +"/summary",
                        "rel": "summary"},
                       { "uri": self.base_path,
                         "rel": "self"},
                       { "uri": self.base_path + "/data",
                         "rel": "data"}
                   ]
        }

        return 200, result

    @Routing.route("/data")
    @_data_decorator
    def data(self, input):
        """Describe the sublements of data

           FIXME: should have a key for every element under data in
                  the schema the user can access.
           This is just an example.
        """
        result = {
            "issue": { "link": self.base_path + "/data/" + "issue" },
            "status": { "link": self.base_path + "/data/" + "status" },
            "keyword": { "link": self.base_path + "/data/" + "keyword" },
            "user": { "link": self.base_path + "/data/" + "user" }
        }

        return 200, result

    @Routing.route("/summary")
    @_data_decorator
    def summary(self, input):
        """Get a summary of resource from class URI.

        This function returns only items have View permission
        class_name should be valid already

        Args:
            class_name (string): class name of the resource (Ex: issue, msg)
            input (list): the submitted form of the user

        Returns:
            int: http status code 200 (OK)
            list:
        """
        if not self.db.security.hasPermission(
            'View', self.db.getuid(), 'issue'
        ) and not self.db.security.hasPermission(
            'View', self.db.getuid(), 'status'
        ) and not self.db.security.hasPermission(
            'View', self.db.getuid(), 'issue'
        ):
            raise Unauthorised('Permission to view summary denied')

        old = date.Date('-1w')

        created = []
        summary = {}
        messages = []

        # loop through all the recently-active issues
        for issue_id in self.db.issue.filter(None, {'activity': '-1w;'}):
            num = 0
            status_name = self.db.status.get(
                self.db.issue.get(issue_id, 'status'),
                'name'
            )
            issue_object = {
                'id': issue_id,
                'link': self.base_path + '/data/issue/' + issue_id,
                'title': self.db.issue.get(issue_id, 'title')
            }
            for x, ts, uid, action, data in self.db.issue.history(issue_id):
                if ts < old:
                    continue
                if action == 'create':
                    created.append(issue_object)
                elif action == 'set' and 'messages' in data:
                    num += 1
            summary.setdefault(status_name, []).append(issue_object)
            messages.append((num, issue_object))

        messages.sort(reverse=True)

        result = {
            'created': created,
            'summary': summary,
            'most_discussed': messages[:10]
        }

        return 200, result

    def dispatch(self, method, uri, input):
        """format and process the request"""
        # if X-HTTP-Method-Override is set, follow the override method
        headers = self.client.request.headers
        # Never allow GET to be an unsafe operation (i.e. data changing).
        # User must use POST to "tunnel" DELETE, PUT, OPTIONS etc.
        override = headers.getheader('X-HTTP-Method-Override')
        output = None
        if override:
            if method.upper() != 'GET':
                logger.debug(
                    'Method overridden from %s to %s', method, override)
                method = override
            else:
                output = self.error_obj(400,
                               "X-HTTP-Method-Override: %s can not be used with GET method. Use Post instead." % override)
                logger.info(
                    'Ignoring X-HTTP-Method-Override for GET request on %s',
                    uri)

        # parse Accept header and get the content type
        accept_header = parse_accept_header(headers.getheader('Accept'))
        accept_type = "invalid"
        for part in accept_header:
            if part[0] in self.__accepted_content_type:
                accept_type = self.__accepted_content_type[part[0]]

        # get the request format for response
        # priority : extension from uri (/rest/issue.json),
        #            header (Accept: application/json, application/xml)
        #            default (application/json)
        ext_type = os.path.splitext(urlparse(uri).path)[1][1:]
        data_type = ext_type or accept_type or self.__default_accept_type

        if ( ext_type ):
            # strip extension so uri make sense
            # .../issue.json -> .../issue
            uri = uri[:-( len(ext_type) + 1 )]

        # add access-control-allow-* to support CORS
        self.client.setHeader("Access-Control-Allow-Origin", "*")
        self.client.setHeader(
            "Access-Control-Allow-Headers",
            "Content-Type, Authorization, X-HTTP-Method-Override"
        )
        self.client.setHeader(
            "Allow",
            "HEAD, OPTIONS, GET, POST, PUT, DELETE, PATCH"
        )
        self.client.setHeader(
            "Access-Control-Allow-Methods",
            "HEAD, OPTIONS, GET, PUT, DELETE, PATCH"
        )

        # Is there an input.value with format json data?
        # If so turn it into an object that emulates enough
        # of the FieldStorge methods/props to allow a response.
        content_type_header = headers.getheader('Content-Type', None)
        if type(input.value) == str and content_type_header:
            parsed_content_type_header = content_type_header
            # the structure of a content-type header
            # is complex: mime-type; options(charset ...)
            # for now we just accept application/json.
            # FIXME there should be a function:
            #   parse_content_type_header(content_type_header)
            # that returns a tuple like the Accept header parser.
            # Then the test below could use:
            #   parsed_content_type_header[0].lower() == 'json'
            # That way we could handle stuff like:
            #  application/vnd.roundup-foo+json; charset=UTF8
            # for example.
            if content_type_header.lower() == "application/json":
                try:
                    input = SimulateFieldStorageFromJson(input.value)
                except ValueError as msg:
                    output = self.error_obj(400, msg)

        # check for pretty print
        try:
            pretty_output = not input['pretty'].value.lower() == "false"
        except KeyError:
            pretty_output = True

        # Call the appropriate method
        try:
            # If output was defined by a prior error
            # condition skip call
            if not output:
                output = Routing.execute(self, uri, method, input)
        except NotFound as msg:
            output = self.error_obj(404, msg)
        except Reject as msg:
            output = self.error_obj(405, msg)

        # Format the content type
        if data_type.lower() == "json":
            self.client.setHeader("Content-Type", "application/json")
            if pretty_output:
                indent = 4
            else:
                indent = None
            output = RoundupJSONEncoder(indent=indent).encode(output)
        elif data_type.lower() == "xml" and dicttoxml:
            self.client.setHeader("Content-Type", "application/xml")
            output = dicttoxml(output, root=False)
        else:
            self.client.response_code = 406
            output = "Content type is not accepted by client"

        # Make output json end in a newline to
        # separate from following text in logs etc..
        return output + "\n"


class RoundupJSONEncoder(json.JSONEncoder):
    """RoundupJSONEncoder overrides the default JSONEncoder to handle all
    types of the object without returning any error"""
    def default(self, obj):
        try:
            result = json.JSONEncoder.default(self, obj)
        except TypeError:
            result = str(obj)
        return result

class SimulateFieldStorageFromJson():
    '''
    The internals of the rest interface assume the data was sent as 
    application/x-www-form-urlencoded. So we should have a 
    FieldStorage and MiniFieldStorage structure.

    However if we want to handle json data, we need to:
      1) create the Fieldstorage/MiniFieldStorage structure
    or
      2) simultate the interface parts of FieldStorage structure

    To do 2, create a object that emulates the:

          object['prop'].value

    references used when accessing a FieldStorage structure.

    That's what this class does.

    '''
    def __init__(self, json_string):
        ''' Parse the json string into an internal dict. '''
        def raise_error_on_constant(x):
            raise ValueError, "Unacceptable number: %s"%x

        self.json_dict = json.loads(json_string,
                                    parse_constant = raise_error_on_constant)
        self.value = [ self.FsValue(index, self.json_dict[index]) for index in self.json_dict.keys() ]

    class FsValue:
        '''Class that does nothing but response to a .value property '''
        def __init__(self, name, val):
            self.name=name
            self.value=val

    def __getitem__(self, index):
        '''Return an FsValue created from the value of self.json_dict[index]
        '''
        return self.FsValue(index, self.json_dict[index])

    def __contains__(self, index):
        ''' implement: 'foo' in DICT '''
        return index in self.json_dict

