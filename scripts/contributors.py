"""
Get Mercurial history data and output list of contributors with years.

Public domain work by:

  anatoly techtonik <techtonik@gmail.com>

"""

from subprocess import check_output

# --- output settings
contributors_by_year = True
years_for_contributors = True
verbose = True
# /--


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
for year,author in authorship:
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


def compress_years(years):
  """
  Given a list of years like [2003, 2004, 2007],
  compress it into string like '2003-2004, 2007'
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


if years_for_contributors:
  if verbose:
    print("Years for each contributor...")
  print('')
  for author in sorted(names):
    years = list(names[author])
    yearstr = compress_years(years)
    
    if 1: #DEBUG
      print(years, yearstr, author)
    else:
      print(yearstr, author)
  print('')
