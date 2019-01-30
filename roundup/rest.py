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
from roundup import hyperdb
from roundup.exceptions import *


def _data_decorator(func):
    """Wrap the returned data into an object."""
    def format_object(self, *args, **kwargs):
        # get the data / error from function
        try:
            code, data = func(self, *args, **kwargs)
        except IndexError, msg:
            code = 404
            data = msg
        except Unauthorised, msg:
            code = 403
            data = msg
        except (hyperdb.DesignatorError, UsageError), msg:
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
            # if self.DEBUG_MODE in roundup_server
            # else data = 'An error occurred. Please check...',
            data = val

            # out to the logfile
            print 'EXCEPTION AT', time.ctime()
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


class RestfulInstance(object):
    """The RestfulInstance performs REST request from the client"""

    def __init__(self, client, db):
        self.client = client  # it might be unnecessary to receive the client
        self.db = db

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
        if not self.db.security.hasPermission(
            'View', self.db.getuid(), class_name
        ):
            raise Unauthorised('Permission to view %s denied' % class_name)

        class_obj = self.db.getclass(class_name)
        class_path = self.base_path + class_name
        result = [
            {'id': item_id, 'link': class_path + item_id}
            for item_id in class_obj.list()
            if self.db.security.hasPermission(
                'View', self.db.getuid(), class_name, itemid=item_id
            )
        ]
        self.client.setHeader("X-Count-Total", str(len(result)))
        return 200, result

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
        if not self.db.security.hasPermission(
            'View', self.db.getuid(), class_name, itemid=item_id
        ):
            raise Unauthorised(
                'Permission to view %s%s denied' % (class_name, item_id)
            )

        class_obj = self.db.getclass(class_name)
        props = class_obj.properties.keys()
        props.sort()  # sort properties
        result = [
            (prop_name, class_obj.get(item_id, prop_name))
            for prop_name in props
            if self.db.security.hasPermission(
                'View', self.db.getuid(), class_name, prop_name,
            )
        ]
        result = {
            'id': item_id,
            'type': class_name,
            'link': self.base_path + class_name + item_id,
            'attributes': dict(result)
        }

        return 200, result

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

    @_data_decorator
    def post_element(self, class_name, item_id, input):
        """POST to an object of a class is not allowed"""
        raise Reject('POST to an item is not allowed')

    @_data_decorator
    def post_attribute(self, class_name, item_id, attr_name, input):
        """POST to an attribute of an object is not allowed"""
        raise Reject('POST to an attribute is not allowed')

    @_data_decorator
    def put_collection(self, class_name, input):
        """PUT a class is not allowed"""
        raise Reject('PUT a class is not allowed')

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

    @_data_decorator
    def patch_collection(self, class_name, input):
        """PATCH a class is not allowed"""
        raise Reject('PATCH a class is not allowed')

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
        try:
            op = input['op'].value.lower()
        except KeyError:
            op = "replace"
        class_obj = self.db.getclass(class_name)

        props = self.props_from_args(class_obj, input.value, item_id)

        for prop, value in props.iteritems():
            if not self.db.security.hasPermission(
                'Edit', self.db.getuid(), class_name, prop, item_id
            ):
                raise Unauthorised(
                    'Permission to edit %s of %s%s denied' %
                    (prop, class_name, item_id)
                )

            if op == 'add':
                props[prop] = class_obj.get(item_id, prop) + props[prop]
            elif op == 'replace':
                pass
            elif op == 'remove':
                current_prop = class_obj.get(item_id, prop)
                if isinstance(current_prop, list):
                    props[prop] = []
                else:
                    props[prop] = None
            else:
                raise UsageError('PATCH Operation %s is not allowed' % op)

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
        try:
            op = input['op'].value.lower()
        except KeyError:
            op = "replace"
        class_obj = self.db.getclass(class_name)

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

        if op == 'add':
            props[prop] = class_obj.get(item_id, prop) + props[prop]
        elif op == 'replace':
            pass
        elif op == 'remove':
            current_prop = class_obj.get(item_id, prop)
            if isinstance(current_prop, list):
                props[prop] = []
            else:
                props[prop] = None
        else:
            raise UsageError('PATCH Operation %s is not allowed' % op)

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

    @_data_decorator
    def options_collection(self, class_name, input):
        """OPTION return the HTTP Header for the class uri

        Returns:
            int: http status code 204 (No content)
            body (string): an empty string
        """
        return 204, ""

    @_data_decorator
    def options_element(self, class_name, item_id, input):
        """OPTION return the HTTP Header for the object uri

        Returns:
            int: http status code 204 (No content)
            body (string): an empty string
        """
        self.client.setHeader(
            "Accept-Patch",
            "application/x-www-form-urlencoded, multipart/form-data"
        )
        return 204, ""

    @_data_decorator
    def option_attribute(self, class_name, item_id, attr_name, input):
        """OPTION return the HTTP Header for the attribute uri

        Returns:
            int: http status code 204 (No content)
            body (string): an empty string
        """
        self.client.setHeader(
            "Accept-Patch",
            "application/x-www-form-urlencoded, multipart/form-data"
        )
        return 204, ""

    def dispatch(self, method, uri, input):
        """format and process the request"""
        # PATH is split to multiple pieces
        # 0 - rest
        # 1 - resource
        # 2 - attribute
        uri_split = uri.split("/")
        resource_uri = uri_split[1]

        # if X-HTTP-Method-Override is set, follow the override method
        headers = self.client.request.headers
        method = headers.getheader('X-HTTP-Method-Override') or method

        # get the request format for response
        # priority : extension from uri (/rest/issue.json),
        #            header (Accept: application/json, application/xml)
        #            default (application/json)

        # format_header need a priority parser
        format_ext = os.path.splitext(urlparse.urlparse(uri).path)[1][1:]
        format_header = headers.getheader('Accept')[12:]
        format_output = format_ext or format_header or "json"

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
        if resource_uri in self.db.classes:
            self.client.setHeader(
                "Allow",
                "HEAD, OPTIONS, GET, POST, DELETE"
            )
            self.client.setHeader(
                "Access-Control-Allow-Methods",
                "HEAD, OPTIONS, GET, POST, DELETE"
            )
        else:
            self.client.setHeader(
                "Allow",
                "HEAD, OPTIONS, GET, PUT, DELETE, PATCH"
            )
            self.client.setHeader(
                "Access-Control-Allow-Methods",
                "HEAD, OPTIONS, GET, PUT, DELETE, PATCH"
            )

        # Call the appropriate method
        output = None
        if resource_uri in self.db.classes:
            output = getattr(
                self, "%s_collection" % method.lower()
                )(resource_uri, input)
        else:
            class_name, item_id = hyperdb.splitDesignator(resource_uri)
            if len(uri_split) == 3:
                output = getattr(
                    self, "%s_attribute" % method.lower()
                    )(class_name, item_id, uri_split[2], input)
            else:
                output = getattr(
                    self, "%s_element" % method.lower()
                    )(class_name, item_id, input)

        if format_output.lower() == "json":
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
