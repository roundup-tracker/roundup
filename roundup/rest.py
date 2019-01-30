"""
Restful API for Roundup

This module is free software, you may redistribute it
and/or modify under the same terms as Python.
"""

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

        print self.base_path

    def get_collection(self, class_name, input):
        if not self.db.security.hasPermission('View', self.db.getuid(),
                                              class_name):
            raise Unauthorised('Permission to view %s denied' % class_name)
        class_obj = self.db.getclass(class_name)
        prop_name = class_obj.labelprop()
        class_path = self.base_path + class_name
        result = [{'id': item_id, 'link': class_path + item_id}
                  for item_id in class_obj.list()
                  if self.db.security.hasPermission('View', self.db.getuid(),
                                                    class_name,
                                                    itemid=item_id)]
        return result

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

        return result

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
            raise UsageError('Must provide the "%s" property.' % key)

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
            raise UsageError(message)

        result = {
            'id': item_id,
            'link': self.base_path + class_name + item_id
        }
        return result

    def post_element(self, class_name, item_id, input):
        raise Reject('Invalid request')

    def put_collection(self, class_name, input):
        raise Reject('Invalid request')

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
            raise UsageError(message)

        result = {
            'id': item_id,
            'type': class_name,
            'link': self.base_path + class_name + item_id,
            'attribute': result
        }
        return result

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

        return result

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

        return result

    def patch_collection(self, class_name, input):
        raise Reject('Invalid request')

    def patch_element(self, class_name, item_id, input):
        raise NotImplementedError

    def dispatch(self, method, uri, input):
        # PATH is split to multiple pieces
        # 0 - rest
        # 1 - resource
        # 2 - attribute
        resource_uri = uri.split("/")[1]

        output = None
        try:
            if resource_uri in self.db.classes:
                output = getattr(self, "%s_collection" % method.lower())(
                    resource_uri, input)
            else:
                class_name, item_id = hyperdb.splitDesignator(resource_uri)
                output = getattr(self, "%s_element" % method.lower())(
                    class_name, item_id, input)

            output = data_obj(output)
        except IndexError, msg:
            output = error_obj(404, msg)
        except Unauthorised, msg:
            output = error_obj(403, msg)
        except (hyperdb.DesignatorError, UsageError), msg:
            output = error_obj(400, msg)
        except (AttributeError, Reject), msg:
            output = error_obj(405, 'Method Not Allowed. ' + str(msg))
        except NotImplementedError:
            output = error_obj(402, 'Method is under development')
            # nothing to pay, just a mark for debugging purpose
        except:
            # if self.DEBUG_MODE in roundup_server
            # else msg = 'An error occurred. Please check...',
            exc, val, tb = sys.exc_info()
            output = error_obj(400, val)

            # out to the logfile, it would be nice if the server do it for me
            print 'EXCEPTION AT', time.ctime()
            traceback.print_exc()
        finally:
            output = RoundupJSONEncoder().encode(output)

        print "Length: %s - Content(50 char): %s" % (len(output), output[:50])
        return output


class RoundupJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        try:
            result = json.JSONEncoder.default(self, obj)
        except TypeError:
            result = str(obj)
        return result
