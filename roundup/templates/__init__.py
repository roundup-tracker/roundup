import os

def listTemplates():
    t_dir = os.path.split(__file__)[0]
    l = []
    for entry in os.listdir(t_dir):
        # this isn't strictly necessary - the CVS dir won't be distributed
        if entry == 'CVS': continue
        if os.path.isdir(os.path.join(t_dir, entry)):
            l.append(entry)
    return l

