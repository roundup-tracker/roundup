import logging
logger = logging.getLogger('extension')

import sys
from roundup import __version__ as roundup_version
def AboutPage(db):
    "report useful info about this tracker"

    def is_module_loaded(module):
        modules = list(sys.modules.keys())
        return module in modules

    def get_status_of_module(module, prefix=None, version=True):
        modules = list(sys.modules.keys())
        is_enabled = module in modules
        if is_enabled:
            if module == 'pyme':
                from pyme import version
                version="version %s"%version.versionstr
            elif module == 'MySQLdb':
                from MySQLdb import version_info
                version="version %s"%".".join([str(v) for v in version_info])
            elif module == 'pychart':
                from pychart import version
                version="version %s"%version.version
            elif module == 'sqlite3':
                from sqlite3 import version
                version="version %s"%version
            elif module == "whoosh":
                from whoosh import versionstring
                version="version %s"%versionstring()
            elif module == 'xapian':
                from xapian import version_string
                version="version %s"%version_string()
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
    info.append(get_status_of_module('dbm', version=False) + "<br>")
    info.append(get_status_of_module('sqlite3') + "<br>")
    info.append(get_status_of_module('MySQLdb') + "<br>")
    info.append(get_status_of_module('psycopg2') + "<br>")

    info.append("<h2>Other modules</h2>")

    indexer = db.config['INDEXER']
    if not indexer:
        if is_module_loaded('xapian'):
            indexer="unset using xapian"
        elif is_module_loaded('whoosh'):
            indexer="unset using woosh"
        else:
            indexer="unset using native"
    else:
        indexer="set to " + indexer

    info.append("Indexer used for full-text: %s<br>"%indexer)

    info.append("Available indexers:<br><ul>")
    if is_module_loaded('xapian'):
        info.append("<li>%s</li>"%get_status_of_module('xapian', prefix="Indexer loaded:"))
    if is_module_loaded('whoosh'):
        info.append("<li>%s</li>"%get_status_of_module('whoosh', prefix="Indexer loaded:"))
    info.append("<li>Indexer loaded: native: True</li>")
    info.append("</ul>")
    info.append(get_status_of_module('pytz') + "<br>")
    info.append(get_status_of_module('pyme') + "<br>")
    info.append(get_status_of_module('OpenSSL') + "<br>")
    info.append(get_status_of_module('pychart') + "<br>")
    info.append(get_status_of_module('pygal') + "<br>")

    info.append(get_status_of_module('jinja2') + "<br>")

    uid = db._db.getuid()
    if uid == "1" or db._db.user.has_role(uid,"Admin"):
        #may leak sensitive info about system, directory paths etc.
        #and keys so require admin user access. Consider expanding
        #to Admin rights for tracker.
        info.append("")
        info.append("Module Path: %r"%sys.path)

        info.append("<h2>Environment Variables</h2>")
        info.append("<pre>") # include pre to prevent wrapping of values
        for key in list(db._client.env.keys()):
            info.append("%s=%s"%(key,db._client.env[key]) + "<br>")
        info.append("</pre>")
    return "\n".join(info)

def init(instance):
    instance.registerUtil('AboutPage', AboutPage)
 
