"""Count how many issues use each bpo field and print a report."""
""" sample output: https://github.com/psf/gh-migration/issues/5#issuecomment-935697646"""

import xmlrpc.client

from collections import defaultdict

class SpecialTransport(xmlrpc.client.SafeTransport):
    def send_content(self, connection, request_body):
        connection.putheader("Referer", "https://bugs.python.org/")
        connection.putheader("Origin", "https://bugs.python.org")
        connection.putheader("X-Requested-With", "XMLHttpRequest")
        xmlrpc.client.SafeTransport.send_content(self, connection, request_body)

# connect to bpo
roundup = xmlrpc.client.ServerProxy('https://bugs.python.org/xmlrpc',
                                    transport=SpecialTransport(),
                                    allow_none=True)

# map bpo classes -> propname
# the class is the name of the class (e.g. issue_type, keyword --
# also used in e.g. in https://bugs.python.org/keyword)
# the propname is the name used as attribute on the issue class
# (e.g. issue.type, issue.keywords)
classes = {
    # 'status': 'status',  # skip this
    'issue_type': 'type',
    'stage': 'stage',
    'component': 'components',
    'version': 'versions',
    'resolution': 'resolution',
    'priority': 'priority',
    'keyword': 'keywords',
}

# find the id for the 'open' status
open_id = roundup.lookup('status', 'open')

print(f'* Counting total issues...')
total_issues_num = len(roundup.filter('issue', None, {}))

print(f'* Counting open issues...')
# use this list to filter only the open issues
open_issues = roundup.filter('issue', None, {'status': open_id})
open_issues_num = len(open_issues)

# save the totals in a dict with this structure:
#   totals[propname][open/all][num/perc][name]
# where propname is e.g. 'keyword' and name is e.g. 'easy'
totals = defaultdict(lambda: {'all': {'perc': {}, 'num': {}},
                              'open': {'perc': {}, 'num': {}}})
for cls, propname in classes.items():
    print(f'* Counting <{cls}>...')
    # get the list of ids/names for the given class (e.g. 'easy' is 6)
    ids = roundup.list(cls, 'id')
    names = roundup.list(cls, 'name')
    for id, name in zip(ids, names):
        # filter and count on *all* issues with the given propname
        tot_all = len(roundup.filter('issue', None, {propname: id}))
        totals[propname]['all']['num'][name] = tot_all
        totals[propname]['all']['perc'][name] = tot_all / total_issues_num
        # filter and count on *open* issues with the given propname
        tot_open = len(roundup.filter('issue', open_issues, {propname: id}))
        totals[propname]['open']['num'][name] = tot_open
        totals[propname]['open']['perc'][name] = tot_open / open_issues_num


print(f'Issues (open/all): {open_issues_num}/{total_issues_num}')

# print a list of markdown tables for each bpo class name
for propname in classes.values():
    print(f'### {propname}')
    print('| bpo field | open | all |')
    print('| :--- | ---: | ---: |')
    # pick the dict for the given propname (e.g. keywords)
    proptots = totals[propname]
    names = proptots['open']['num']
    # sort the names (e.g. 'easy') in reverse order
    # based on the number of open issues
    for name in sorted(names, key=names.get, reverse=True):
        # get and print num/perc for all/open issues
        issues_all = proptots['all']['num'][name]
        issues_open = proptots['open']['num'][name]
        perc_all = proptots['all']['perc'][name]
        perc_open = proptots['open']['perc'][name]
        print(f'| {name:20} | {issues_open:>5} ({perc_open:5.1%}) |'
              f' {issues_all:>5} ({perc_all:5.1%}) |')
    # calc and print num/perc for all/open issues
    tot_issues_all = sum(proptots['all']['num'].values())
    tot_issues_open = sum(proptots['open']['num'].values())
    tot_perc_all = sum(proptots['all']['perc'].values())
    tot_perc_open = sum(proptots['open']['perc'].values())
    print(f'| **Total**            | {tot_issues_open:>5} ({tot_perc_open:5.1%}) |'
            f' {tot_issues_all:>5} ({tot_perc_all:5.1%}) |')

