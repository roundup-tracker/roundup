"""
Get Mercurial history data and output list of contributors with years.

Public domain work by:

  anatoly techtonik <techtonik@gmail.com>

"""

from __future__ import print_function
from subprocess import check_output

# --- output settings
contributors_by_year = True
years_for_contributors = True
verbose = True
# /--

# --- project specific configuration
ALIASES = {
  'Richard Jones <richard@mechanicalcat.net>':
      ['richard',
       'Richard Jones <richard@users.sourceforge.net>'],
  'Bernhard Reiter <bernhard@intevation.de>':
      ['Bernhard Reiter <ber@users.sourceforge.net>',
       'Bernhard Reiter <Bernhard.Reiter@intevation.de>'],
  'Ralf Schlatterbeck <rsc@runtux.com>':
      ['Ralf Schlatterbeck <schlatterbeck@users.sourceforge.net>'],
  'Stefan Seefeld <stefan@seefeld.name>':
      ['Stefan Seefeld <stefan@users.sourceforge.net>'],
  'John P. Rouillard <rouilj@cs.umb.edu>':
      ['rouilj'],
}
ROBOTS = ['No Author <no-author@users.sourceforge.net>']
# /-- 


def compress(years):
  """
  Given a list of years like [2003, 2004, 2007],
  compress it into string like '2003-2004, 2007'

  >>> compress([2002])
  '2002'
  >>> compress([2003, 2002])
  '2002-2003'
  >>> compress([2009, 2004, 2005, 2006, 2007])
  '2004-2007, 2009'
  >>> compress([2001, 2003, 2004, 2005])
  '2001, 2003-2005'
  >>> compress([2009, 2011])
  '2009, 2011'
  >>> compress([2009, 2010, 2011, 2006, 2007])
  '2006-2007, 2009-2011'
  >>> compress([2002, 2003, 2004, 2005, 2006, 2009, 2012])
  '2002-2006, 2009, 2012'
  """
  years = sorted(years)
  # compress years into string
  comma = ', '
  yearstr = ''
  for i in range(0,len(years)-1):
    if years[i+1]-years[i] == 1:
      if not yearstr or yearstr.endswith(comma):
        yearstr += '%s' % years[i]
      if yearstr.endswith('-'):
        pass
      else:
        yearstr += '-'
    else:
      yearstr += '%s, ' % years[i]

  if len(years) == 1:
    yearstr += str(years[0])
  else:
    yearstr += '%s' % years[-1]
  return yearstr


if __name__ == '__main__':
  if verbose:
    print("Getting HG log...")
  authorship = check_output('hg log --template "{date(date,\\"%Y\\")},{author}\n"')
  # authorship are strings like
  # 2003,Richard Jones <richard@users.sourceforge.net>
  # ...

  if verbose:
    print("Splitting...")
  # transform to a list of tuples
  authorship = [line.split(',', 1) for line in authorship.splitlines()]

  if verbose:
    print("Sorting...")
  years = {}  # year -> set(author1, author2, ...)
  names = {}  # author -> set(years)
  for year, author in authorship:
    if author in ROBOTS:
      continue
    # process aliases
    for name, aliases in ALIASES.items():
      if author in aliases:
        author = name
        break
    author = author.replace('<', '(')
    author = author.replace('>', ')')
    # years
    if not year in years:
      years[year] = set()
    years[year].add(author)
    # names
    if not author in names:
      names[author] = set()
    names[author].add(int(year))


  if contributors_by_year:
    if verbose:
      print("Contributors by year...")
    print('')
    for year in sorted(years, reverse=True):
      print(year)
      for author in sorted(years[year]):
        print("  " + author)
    print('')

  if years_for_contributors:
    if verbose:
      print("Years for each contributor...")
    print('')
    
    def last_year(name):
      """Return year of the latest contribution for a given name"""
      return sorted(list(names[name]))[-1]

    def first_year(name):
      """Return year of the first contribution"""
      return sorted(list(names[name]))[0]

    def year_key(name):
      """
      Year key function. First sort by latest contribution year (desc).
      If it matches, compare first contribution year (asc). This ensures that
      the most recent and long-term contributors are at the top.
      """
      return (last_year(name), -first_year(name))
    
    print("Copyright (c)")
    for author in sorted(list(names), key=year_key, reverse=True):
      years = list(names[author])
      yearstr = compress(years)

      if 0: #DEBUG
        print(years, yearstr, author)
      else:
        print("    %s %s" % (yearstr, author))
    print('')
