import logging
logger = logging.getLogger('extension')

import sys
from roundup import __version__ as roundup_version
def AboutPage(db):
    "report useful info about this tracker"

    def is_module_loaded(module):
        modules = sys.modules.keys()
        return module in modules

    def get_status_of_module(module, prefix=None, version=True):
        modules = sys.modules.keys()
        is_enabled = module in modules
        if is_enabled:
            if module == 'pyme':
                from pyme import version
                version="version %s"%version.versionstr
            elif module == 'pychart':
                from pychart import version
                version="version %s"%version.version
            elif module == 'sqlite3':
                from sqlite3 import version
                version="version %s"%version
            else:
                if version:
                    m = __import__(module)
                    try:
                        version="version %s"%m.__version__
                    except AttributeError:
                        version="version unavailable - exception thrown"
                else:
                    version="version unavailable"

            if prefix:
                return "%s %s %s enabled: %s"%(prefix, module, version, is_enabled)
            else:
                return "Module: %s %s enabled: %s"%(module, version, is_enabled)
        else:
            if prefix:
                return "%s %s enabled: %s"%(prefix, module, is_enabled)
            else:
                return "Module: %s enabled: %s"%(module, is_enabled)

    info = []

    info.append("Tracker name: %s<br>"%db.config['TRACKER_NAME'])

    info.append("<h2>Operating environment</h2>")
    info.append('<a href="http://roundup.sourceforge.net/">Roundup</a> version: %s<br>'%roundup_version)
    info.append("Python Version: %s<br>"%sys.version)

    info.append("<h2>Configuration</h2>")

    backend = db.config['RDBMS_BACKEND']
    info.append("Roundup backend: %s<br>"%backend)
    if backend != 'anydbm':
        info.append("Roundup db cache: %s<br>"%db.config['RDBMS_CACHE_SIZE'])
        info.append("Roundup isolation_level: %s<br>"%db.config['RDBMS_ISOLATION_LEVEL'])

    info.append("Roundup template: %s<br>"%db.config['TEMPLATE_ENGINE'])

    info.append("<h2>Database modules</h2>")
    info.append(get_status_of_module('anydbm', version=False) + "<br>")
    info.append(get_status_of_module('sqlite3') + "<br>")
    info.append(get_status_of_module('MySQLdb') + "<br>")
    info.append(get_status_of_module('psycopg2') + "<br>")

    info.append("<h2>Other modules</h2>")

    info.append(get_status_of_module('pytz') + "<br>")
    if is_module_loaded('xapian'):
        info.append(get_status_of_module('xapian', prefix="Test indexer:") +
                    "<br>")
    elif is_module_loaded('whoosh'):
        info.append(get_status_of_module('whoosh', prefix="Test indexer:") +
                    "<br>")
    else:
        info.append("Text indexer: Native enabled: True<br>")

    info.append(get_status_of_module('pyme') + "<br>")
    info.append(get_status_of_module('OpenSSL') + "<br>")
    info.append(get_status_of_module('pychart') + "<br>")

    info.append(get_status_of_module('jinja2') + "<br>")

    if db._db.getuid() == "1":
        #may leak sensitive info about system, directory paths etc.
        #and keys so require admin user access. Consider expanding
        #to Admin rights for tracker.
        info.append("")
        info.append("Module Path: %r"%sys.path)

        info.append("<h2>Environment Variables</h2>")
        info.append("<pre>") # include pre to prevent wrapping of values
        for key in db._client.env.keys():
            info.append("%s=%s"%(key,db._client.env[key]) + "<br>")
        info.append("</pre>")
    return "\n".join(info)

def init(instance):
    instance.registerUtil('AboutPage', AboutPage)
 
