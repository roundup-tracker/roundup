class Explicit:
    pass

def aq_base(obj):
    return obj
aq_inner = aq_base
def aq_parent(obj):
    return None
