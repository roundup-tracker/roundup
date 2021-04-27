# If you installed roundup to the system locations
# using pip you don't need to change this
# section. If you installed roundup in a custom
# location, uncomment these lines and change the
# path in the append() method to your custom path.
#import sys
#sys.path.append('/custom/location/where/roundup/is/installed')

# Obtain the WSGI request dispatcher
from roundup.cgi.wsgi_handler import RequestDispatcher

# Set the path to tracker home.
tracker_home = '/path/to/tracker'

# Definition signature for app: app(environ, start_response):
app =  RequestDispatcher(tracker_home)
