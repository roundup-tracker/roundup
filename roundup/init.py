import os, shutil, sys

def copytree(src, dst, symlinks=0):
    """Recursively copy a directory tree using copy2().

    The destination directory os allowed to exist.

    If the optional symlinks flag is true, symbolic links in the
    source tree result in symbolic links in the destination tree; if
    it is false, the contents of the files pointed to by symbolic
    links are copied.

    XXX copied from shutil.py in std lib

    """
    names = os.listdir(src)
    try:
        os.mkdir(dst)
    except OSError, error:
        if error.errno != 17: raise
    for name in names:
        srcname = os.path.join(src, name)
        dstname = os.path.join(dst, name)
        if symlinks and os.path.islink(srcname):
            linkto = os.readlink(srcname)
            os.symlink(linkto, dstname)
        elif os.path.isdir(srcname):
            copytree(srcname, dstname, symlinks)
        else:
            shutil.copy2(srcname, dstname)

def init(instance, template, adminpw):
    ''' initialise an instance using the named template
    '''
    # first, copy the template dir over
    template_dir = os.path.split(__file__)[0]
    template = os.path.join(template_dir, 'templates', template)
    copytree(template, instance)

    # now import the instance and call its init
    path, instance = os.path.split(instance)
    sys.path.insert(0, path)
    instance = __import__(instance)
    instance.init(adminpw)

