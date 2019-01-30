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
from roundup import xmlrpc


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
                    props[key] = hyperdb.rawToHyperdb(
                        self.db, cl, itemid, key, value
                    )
                except hyperdb.HyperdbValueError, msg:
                    raise UsageError(msg)
            else:
                props[key] = None

        return props

    @staticmethod
    def error_obj(status, msg, source=None):
        """Wrap the error data into an object. This function is temporally and
        will be changed to a decorator later."""
        result = {
            'error': {
                'status': status,
                'msg': msg
            }
        }
        if source is not None:
            result['error']['source'] = source

        return result

    @staticmethod
    def data_obj(data):
        """Wrap the returned data into an object. This function is temporally
        and will be changed to a decorator later."""
        result = {
            'data': data
        }
        return result

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
                'Permission to view %s item %d denied' % (class_name, item_id)
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

    def post_element(self, class_name, item_id, input):
        """POST to an object of a class is not allowed"""
        raise Reject('POST to an item is not allowed')

    def put_collection(self, class_name, input):
        """PUT a class is not allowed"""
        raise Reject('PUT a class is not allowed')

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

    def patch_collection(self, class_name, input):
        """PATCH a class is not allowed"""
        raise Reject('PATCH a class is not allowed')

    def patch_element(self, class_name, item_id, input):
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

    def options_collection(self, class_name, input):
        """OPTION return the HTTP Header for the class uri

        Returns:
            int: http status code 204 (No content)
            body (string): an empty string
        """
        return 204, ""

    def options_element(self, class_name, item_id, input):
        """OPTION return the HTTP Header for the object uri

        Returns:
            int: http status code 204 (No content)
            body (string): an empty string
        """
        self.client.setHeader(
            "Accept-Patch",
            "application/x-www-form-urlencoded, "
            "multipart/form-data"
        )
        return 204, ""

    def dispatch(self, method, uri, input):
        """format and process the request"""
        # PATH is split to multiple pieces
        # 0 - rest
        # 1 - resource
        # 2 - attribute
        resource_uri = uri.split("/")[1]

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
        try:
            if resource_uri in self.db.classes:
                response_code, output = getattr(
                    self, "%s_collection" % method.lower()
                    )(resource_uri, input)
            else:
                class_name, item_id = hyperdb.splitDesignator(resource_uri)
                response_code, output = getattr(
                    self, "%s_element" % method.lower()
                    )(class_name, item_id, input)
            output = RestfulInstance.data_obj(output)
            self.client.response_code = response_code
        except IndexError, msg:
            output = RestfulInstance.error_obj(404, msg)
            self.client.response_code = 404
        except Unauthorised, msg:
            output = RestfulInstance.error_obj(403, msg)
            self.client.response_code = 403
        except (hyperdb.DesignatorError, UsageError), msg:
            output = RestfulInstance.error_obj(400, msg)
            self.client.response_code = 400
        except (AttributeError, Reject), msg:
            output = RestfulInstance.error_obj(405, msg)
            self.client.response_code = 405
        except ValueError, msg:
            output = RestfulInstance.error_obj(409, msg)
            self.client.response_code = 409
        except NotImplementedError:
            output = RestfulInstance.error_obj(402, 'Method under development')
            self.client.response_code = 402
            # nothing to pay, just a mark for debugging purpose
        except:
            # if self.DEBUG_MODE in roundup_server
            # else msg = 'An error occurred. Please check...',
            exc, val, tb = sys.exc_info()
            output = RestfulInstance.error_obj(400, val)
            self.client.response_code = 400

            # out to the logfile, it would be nice if the server do it for me
            print 'EXCEPTION AT', time.ctime()
            traceback.print_exc()
        finally:
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
