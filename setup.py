from distutils.core import setup, Extension
from distutils.util import get_platform

from glob import glob
import os

templates = 'classic', 'extended'
packagelist = [ 'roundup', 'roundup.backends', 'roundup.templates' ]
installdatafiles = []

for t in templates:
    packagelist.append('roundup.templates.%s'%t)
    packagelist.append('roundup.templates.%s.detectors'%t)
    tfiles = glob(os.path.join('roundup','templates', t, 'html', '*'))
    tfiles = filter(os.path.isfile, tfiles)


setup ( name = "roundup", 
	version = "0.1.4",
	description = "roundup tracking system",
	author = "Richard Jones",
	url = 'http://sourceforge.net/projects/roundup/',
	packages = packagelist,
)

# now install the bin programs, and the cgi-bin programs
# not sure how, yet.
