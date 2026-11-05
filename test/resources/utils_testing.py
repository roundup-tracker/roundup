class CallableUtilObject:

    def __call__(self, *args, **kwargs):
        return "__call__() CallableUtilObject %s" % (args or "")

    def __str__(self):
        return "__str__() CallableUtilObject %s" % self

class UtilObject:
    def __init__(self, name=""):
        self.name = name
        
    def __str__(self):
        return "__str__() string named='%s'" % self.name

def init(instance):
    instance.registerUtil('dict_val', {"a": "b", "c": "d"})
    instance.registerUtil('int_val', 1)
    instance.registerUtil('list_val', ["this", "is", "a", " util.list", 1])
    instance.registerUtil('string_val', "this is a util.string")
    instance.registerUtil('tuple_val', ("this", "is", "a", " util.tuple", 1))

    instance.registerUtil('callable_instance_val', CallableUtilObject())
    instance.registerUtil('instance_val', UtilObject('foo'))

    instance.registerUtil('class_val', UtilObject)
