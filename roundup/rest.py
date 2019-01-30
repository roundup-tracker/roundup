"""
Restful API for Roundup

This module is free software, you may redistribute it
and/or modify under the same terms as Python.
"""

import json
import pprint
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

class RestfulInstance(object):
    """Dummy Handler for REST
    """

    def __init__(self, db):
        # TODO: database, translator and instance.actions
        self.db = db

    def get_collection(self, class_name, input):
        if not self.db.security.hasPermission('View', self.db.getuid(),
                                              class_name):
            raise Unauthorised('Permission to view %s denied' % class_name)
        class_obj = self.db.getclass(class_name)
        prop_name = class_obj.labelprop()
        result = [{'id': item_id, 'name': class_obj.get(item_id, prop_name)}
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
        result = dict(result)

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

        result = {id: item_id}
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

        result['id'] = item_id
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

        for item_id in class_obj.list():
            self.db.destroynode(class_name, item_id)

        self.db.commit()
        result = {"status": "ok"}

        return result

    def delete_element(self, class_name, item_id, input):
        if not self.db.security.hasPermission('Delete', self.db.getuid(),
                                              class_name, itemid=item_id):
            raise Unauthorised('Permission to delete %s %s denied' %
                               (class_name, item_id))

        self.db.destroynode(class_name, item_id)
        self.db.commit()
        result = {"status": "ok"}

        return result

    def patch_collection(self, class_name, input):
        raise Reject('Invalid request')

    def patch_element(self, class_name, item_id, input):
        raise NotImplementedError

    def dispatch(self, method, uri, input):
        # PATH is split to multiple pieces
        # 0 - rest
        # 1 - resource
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
        except hyperdb.DesignatorError:
            raise NotImplementedError('Invalid URI')
        except AttributeError:
            raise NotImplementedError('Method is invalid')
        finally:
            output = json.JSONEncoder().encode(output)

        print "Length: %s - Content(50 char): %s" % (len(output), output[:50])
        return output
