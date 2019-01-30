"""
Restful API for Roundup

This module is free software, you may redistribute it
and/or modify under the same terms as Python.
"""

import urlparse
import os
import json
import pprint
import sys
import time
import traceback
import re

from roundup import hyperdb
from roundup import date
from roundup import actions
from roundup.exceptions import *
from roundup.cgi.exceptions import *


def _data_decorator(func):
    """Wrap the returned data into an object."""
    def format_object(self, *args, **kwargs):
        # get the data / error from function
        try:
            code, data = func(self, *args, **kwargs)
        except NotFound, msg:
            code = 404
            data = msg
        except IndexError, msg:
            code = 404
            data = msg
        except Unauthorised, msg:
            code = 403
            data = msg
        except UsageError, msg:
            code = 400
            data = msg
        except (AttributeError, Reject), msg:
            code = 405
            data = msg
        except ValueError, msg:
            code = 409
            data = msg
        except NotImplementedError:
            code = 402  # nothing to pay, just a mark for debugging purpose
            data = 'Method under development'
        except:
            exc, val, tb = sys.exc_info()
            code = 400
            ts = time.ctime()
            if self.client.request.DEBUG_MODE:
                data = val
            else:
                data = '%s: An error occurred. Please check the server log' \
                       ' for more information.' % ts
            # out to the logfile
            print 'EXCEPTION AT', ts
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
        "*/*": "json"
        # "application/xml": "xml"
    }
    __default_accept_type = "json"

    def __init__(self, client, db):
        self.client = client
        self.db = db
        self.translator = client.translator
        self.actions = client.instance.actions.copy()
        self.actions.update({'retire': actions.Retire})

        protocol = 'http'
        host = self.client.env['HTTP_HOST']
        tracker = self.client.env['TRACKER_NAME']
        self.base_path = '%s://%s/%s/rest/' % (protocol, host, tracker)

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
                key = key.encode('ascii')
            except UnicodeEncodeError:
                raise UsageError(
                    'argument %r is no valid ascii keyword' % key
                )
        if isinstance(value, unicode):
            value = value.encode('utf-8')
        if value:
            try:
                prop = hyperdb.rawToHyperdb(
                    self.db, cl, itemid, key, value
                )
            except hyperdb.HyperdbValueError, msg:
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
        class_path = self.base_path + class_name

        # Handle filtering and pagination
        filter_props = {}
        page = {
            'size': None,
            'index': None
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
        result = [
            {'id': item_id, 'link': class_path + item_id}
            for item_id in obj_list
            if self.db.security.hasPermission(
                'View', self.db.getuid(), class_name, itemid=item_id
            )
        ]

        # pagination
        if page['size'] is not None and page['index'] is not None:
            page_start = max(page['index'] * page['size'], 0)
            page_end = min(page_start + page['size'], len(result))
            result = result[page_start:page_end]

        self.client.setHeader("X-Count-Total", str(len(result)))
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
        props = None
        for form_field in input.value:
            key = form_field.name
            value = form_field.value
            if key == "fields":
                props = value.split(",")

        if props is None:
            props = class_obj.properties.keys()

        props.sort()  # sort properties

        try:
            result = [
                (prop_name, class_obj.get(item_id, prop_name))
                for prop_name in props
                if self.db.security.hasPermission(
                    'View', self.db.getuid(), class_name, prop_name,
                )
            ]
        except KeyError, msg:
            raise UsageError("%s field not valid" % msg)
        result = {
            'id': item_id,
            'type': class_name,
            'link': self.base_path + class_name + item_id,
            'attributes': dict(result)
        }

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
        data = class_obj.get(item_id, attr_name)
        result = {
            'id': item_id,
            'type': type(data),
            'link': "%s%s%s/%s" %
                    (self.base_path, class_name, item_id, attr_name),
            'data': data
        }

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
        except (TypeError, IndexError, ValueError), message:
            raise ValueError(message)
        except KeyError, msg:
            raise UsageError("Must provide the %s property." % msg)

        # set the header Location
        link = self.base_path + class_name + item_id
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
        for p in props.iterkeys():
            if not self.db.security.hasPermission(
                'Edit', self.db.getuid(), class_name, p, item_id
            ):
                raise Unauthorised(
                    'Permission to edit %s of %s%s denied' %
                    (p, class_name, item_id)
                )
        try:
            result = class_obj.set(item_id, **props)
            self.db.commit()
        except (TypeError, IndexError, ValueError), message:
            raise ValueError(message)

        result = {
            'id': item_id,
            'type': class_name,
            'link': self.base_path + class_name + item_id,
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
            result = class_obj.set(item_id, **props)
            self.db.commit()
        except (TypeError, IndexError, ValueError), message:
            raise ValueError(message)

        result = {
            'id': item_id,
            'type': class_name,
            'link': self.base_path + class_name + item_id,
            'attribute': result
        }

        return 200, result

    @Routing.route("/data/<:class_name>", 'DELETE')
    @_data_decorator
    def delete_collection(self, class_name, input):
        """DELETE all objects in a class

        Args:
            class_name (string): class name of the resource (Ex: issue, msg)
            input (list): the submitted form of the user

        Returns:
            int: http status code 200 (OK)
            dict:
                status (string): 'ok'
                count (int): number of deleted objects
        """
        if class_name not in self.db.classes:
            raise NotFound('Class %s not found' % class_name)
        if not self.db.security.hasPermission(
            'Delete', self.db.getuid(), class_name
        ):
            raise Unauthorised('Permission to delete %s denied' % class_name)

        class_obj = self.db.getclass(class_name)
        for item_id in class_obj.list():
            if not self.db.security.hasPermission(
                'Delete', self.db.getuid(), class_name, itemid=item_id
            ):
                raise Unauthorised(
                    'Permission to delete %s %s denied' % (class_name, item_id)
                )

        count = len(class_obj.list())
        for item_id in class_obj.list():
            self.db.destroynode(class_name, item_id)

        self.db.commit()
        result = {
            'status': 'ok',
            'count': count
        }

        return 200, result

    @Routing.route("/data/<:class_name>/<:item_id>", 'DELETE')
    @_data_decorator
    def delete_element(self, class_name, item_id, input):
        """DELETE an object in a class

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
        if not self.db.security.hasPermission(
            'Delete', self.db.getuid(), class_name, itemid=item_id
        ):
            raise Unauthorised(
                'Permission to delete %s %s denied' % (class_name, item_id)
            )

        self.db.destroynode(class_name, item_id)
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
            class_obj.set(item_id, **props)
            self.db.commit()
        except (TypeError, IndexError, ValueError), message:
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
                'link': self.base_path + class_name + item_id,
                'result': result
            }
        else:
            # else patch operation is processing data
            props = self.props_from_args(class_obj, input.value, item_id)

            for prop, value in props.iteritems():
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
            except (TypeError, IndexError, ValueError), message:
                raise ValueError(message)

            result = {
                'id': item_id,
                'type': class_name,
                'link': self.base_path + class_name + item_id,
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
        except (TypeError, IndexError, ValueError), message:
            raise ValueError(message)

        result = {
            'id': item_id,
            'type': class_name,
            'link': self.base_path + class_name + item_id,
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
                'link': self.base_path + 'issue' + issue_id,
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
        method = headers.getheader('X-HTTP-Method-Override') or method

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
        ext_type = os.path.splitext(urlparse.urlparse(uri).path)[1][1:]
        data_type = ext_type or accept_type or self.__default_accept_type

        # check for pretty print
        try:
            pretty_output = input['pretty'].value.lower() == "true"
        except KeyError:
            pretty_output = False

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

        # Call the appropriate method
        try:
            output = Routing.execute(self, uri, method, input)
        except NotFound, msg:
            output = self.error_obj(404, msg)
        except Reject, msg:
            output = self.error_obj(405, msg)

        # Format the content type
        if data_type.lower() == "json":
            self.client.setHeader("Content-Type", "application/json")
            if pretty_output:
                indent = 4
            else:
                indent = None
            output = RoundupJSONEncoder(indent=indent).encode(output)
        else:
            self.client.response_code = 406
            output = "Content type is not accepted by client"

        return output


class RoundupJSONEncoder(json.JSONEncoder):
    """RoundupJSONEncoder overrides the default JSONEncoder to handle all
    types of the object without returning any error"""
    def default(self, obj):
        try:
            result = json.JSONEncoder.default(self, obj)
        except TypeError:
            result = str(obj)
        return result
