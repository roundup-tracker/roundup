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

if years_for_contributors:
  if verbose:
    print("Years for each contributor...")
  print('')
  for author in sorted(names):
    years = sorted(names[author])
    print(years, author)
  print('')
