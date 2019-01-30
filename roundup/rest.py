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


def props_from_args(db, cl, args, itemid=None):
    props = {}
    for arg in args:
        try:
            key = arg.name
            value = arg.value
        except ValueError:
            raise UsageError('argument "%s" not propname=value' % arg)
        if isinstance(key, unicode):
            try:
                key = key.encode('ascii')
            except UnicodeEncodeError:
                raise UsageError('argument %r is no valid ascii keyword' % key)
        if isinstance(value, unicode):
            value = value.encode('utf-8')
        if value:
            try:
                props[key] = hyperdb.rawToHyperdb(db, cl, itemid, key, value)
            except hyperdb.HyperdbValueError:
                pass  # pass if a parameter is not a property of the class
        else:
            props[key] = None

    return props


def error_obj(status, msg, source=None):
    result = {
        'error': {
            'status': status,
            'msg': msg
        }
    }
    if source is not None:
        result['error']['source'] = source

    return result


def data_obj(data):
    result = {
        'data': data
    }
    return result


class RestfulInstance(object):
    """Dummy Handler for REST
    """

    def __init__(self, client, db):
        self.client = client  # it might be unnecessary to receive the client
        self.db = db

        protocol = 'http'
        host = self.client.env['HTTP_HOST']
        tracker = self.client.env['TRACKER_NAME']
        self.base_path = '%s://%s/%s/rest/' % (protocol, host, tracker)

    def get_collection(self, class_name, input):
        if not self.db.security.hasPermission('View', self.db.getuid(),
                                              class_name):
            raise Unauthorised('Permission to view %s denied' % class_name)
        class_obj = self.db.getclass(class_name)
        class_path = self.base_path + class_name
        result = [{'id': item_id, 'link': class_path + item_id}
                  for item_id in class_obj.list()
                  if self.db.security.hasPermission('View', self.db.getuid(),
                                                    class_name,
                                                    itemid=item_id)]
        self.client.setHeader("X-Count-Total", str(len(result)))
        return 200, result

    def get_element(self, class_name, item_id, input):
        if not self.db.security.hasPermission('View', self.db.getuid(),
                                              class_name, itemid=item_id):
            raise Unauthorised('Permission to view %s item %d denied' %
                               (class_name, item_id))
        class_obj = self.db.getclass(class_name)
        props = class_obj.properties.keys()
        props.sort()  # sort properties
        result = [(prop_name, class_obj.get(item_id, prop_name))
                  for prop_name in props
                  if self.db.security.hasPermission('View', self.db.getuid(),
                                                    class_name, prop_name,
                                                    item_id)]
        result = {
            'id': item_id,
            'type': class_name,
            'link': self.base_path + class_name + item_id,
            'attributes': dict(result)
        }

        return 200, result

    def post_collection(self, class_name, input):
        if not self.db.security.hasPermission('Create', self.db.getuid(),
                                              class_name):
            raise Unauthorised('Permission to create %s denied' % class_name)

        class_obj = self.db.getclass(class_name)

        # convert types
        props = props_from_args(self.db, class_obj, input.value)

        # check for the key property
        key = class_obj.getkey()
        if key and key not in props:
            raise UsageError("Must provide the '%s' property." % key)

        for key in props:
            if not self.db.security.hasPermission('Create', self.db.getuid(),
                                                  class_name, property=key):
                raise Unauthorised('Permission to create %s.%s denied' %
                                   (class_name, key))

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
        raise Reject('POST to an item is not allowed')

    def put_collection(self, class_name, input):
        raise Reject('PUT a class is not allowed')

    def put_element(self, class_name, item_id, input):
        class_obj = self.db.getclass(class_name)

        props = props_from_args(self.db, class_obj, input.value, item_id)
        for p in props.iterkeys():
            if not self.db.security.hasPermission('Edit', self.db.getuid(),
                                                  class_name, p, item_id):
                raise Unauthorised('Permission to edit %s of %s%s denied' %
                                   (p, class_name, item_id))
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
        if not self.db.security.hasPermission('Delete', self.db.getuid(),
                                              class_name):
            raise Unauthorised('Permission to delete %s denied' % class_name)

        class_obj = self.db.getclass(class_name)
        for item_id in class_obj.list():
            if not self.db.security.hasPermission('Delete', self.db.getuid(),
                                                  class_name, itemid=item_id):
                raise Unauthorised('Permission to delete %s %s denied' %
                                   (class_name, item_id))

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
        if not self.db.security.hasPermission('Delete', self.db.getuid(),
                                              class_name, itemid=item_id):
            raise Unauthorised('Permission to delete %s %s denied' %
                               (class_name, item_id))

        self.db.destroynode(class_name, item_id)
        self.db.commit()
        result = {
            'status': 'ok'
        }

        return 200, result

    def patch_collection(self, class_name, input):
        raise Reject('PATCH a class is not allowed')

    def patch_element(self, class_name, item_id, input):
        raise NotImplementedError

    def options_collection(self, class_name, input):
        return 204, ""

    def options_element(self, class_name, item_id, input):
        self.client.setHeader("Accept-Patch",
                              "application/x-www-form-urlencoded, "
                              "multipart/form-data")
        return 204, ""

    def dispatch(self, method, uri, input):
        # PATH is split to multiple pieces
        # 0 - rest
        # 1 - resource
        # 2 - attribute
        resource_uri = uri.split("/")[1]

        # if X-HTTP-Method-Override is set, follow the override method
        method = self.client.request.headers.getheader('X-HTTP-Method-Override') or method

        # get the request format for response
        # priority : extension from uri (/rest/issue.json),
        #            header (Accept: application/json, application/xml)
        #            default (application/json)

        # format_header need a priority parser
        format_ext = os.path.splitext(urlparse.urlparse(uri).path)[1][1:]
        format_header = self.client.request.headers.getheader('Accept')[12:]
        format_output = format_ext or format_header or "json"

        # check for pretty print
        try:
            pretty_output = input['pretty'].value.lower() == "true"
        except KeyError:
            pretty_output = False

        self.client.setHeader("Access-Control-Allow-Origin", "*")
        self.client.setHeader("Access-Control-Allow-Headers",
                              "Content-Type, Authorization, "
                              "X-HTTP-Method-Override")

        output = None
        try:
            if resource_uri in self.db.classes:
                self.client.setHeader("Allow",
                                      "HEAD, OPTIONS, GET, POST, DELETE")
                self.client.setHeader("Access-Control-Allow-Methods",
                                      "HEAD, OPTIONS, GET, POST, DELETE")
                response_code, output = getattr(self, "%s_collection" % method.lower())(
                    resource_uri, input)
            else:
                class_name, item_id = hyperdb.splitDesignator(resource_uri)
                self.client.setHeader("Allow",
                                      "HEAD, OPTIONS, GET, PUT, DELETE, PATCH")
                self.client.setHeader("Access-Control-Allow-Methods",
                                      "HEAD, OPTIONS, GET, PUT, DELETE, PATCH")
                response_code, output = getattr(self, "%s_element" % method.lower())(
                    class_name, item_id, input)

            output = data_obj(output)
            self.client.response_code = response_code
        except IndexError, msg:
            output = error_obj(404, msg)
            self.client.response_code = 404
        except Unauthorised, msg:
            output = error_obj(403, msg)
            self.client.response_code = 403
        except (hyperdb.DesignatorError, UsageError), msg:
            output = error_obj(400, msg)
            self.client.response_code = 400
        except (AttributeError, Reject), msg:
            output = error_obj(405, msg)
            self.client.response_code = 405
        except ValueError, msg:
            output = error_obj(409, msg)
            self.client.response_code = 409
        except NotImplementedError:
            output = error_obj(402, 'Method is under development')
            self.client.response_code = 402
            # nothing to pay, just a mark for debugging purpose
        except:
            # if self.DEBUG_MODE in roundup_server
            # else msg = 'An error occurred. Please check...',
            exc, val, tb = sys.exc_info()
            output = error_obj(400, val)
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
                output = ""

        return output


class RoundupJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        try:
            result = json.JSONEncoder.default(self, obj)
        except TypeError:
            result = str(obj)
        return result
