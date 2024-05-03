#! /usr/bin/env python
#
# Copyright 2004 Richard Jones (richard@mechanicalcat.net)
#

import argparse
import sys

# --- patch sys.path to make sure 'import roundup' finds correct version
import os.path as osp

thisdir = osp.dirname(osp.abspath(__file__))
rootdir = osp.dirname(osp.dirname(thisdir))
if (osp.exists(thisdir + '/__init__.py') and
        osp.exists(rootdir + '/roundup/__init__.py')):
    # the script is located inside roundup source code
    sys.path.insert(0, rootdir)
# --/

# import also verifies python version as side effect
from roundup import version_check                         # noqa: F401 E402
from roundup import admin, configuration, demo, instance  # noqa: E402
from roundup import __version__ as roundup_version        # noqa: E402
from roundup.anypy.my_input import my_input               # noqa: E402
from roundup.backends import list_backends                # noqa: E402
from roundup.i18n import _                                # noqa: E402


DEFAULT_HOME = './demo'
DEFAULT_TEMPLATE = 'classic'
DEFAULT_BACKEND = 'sqlite'
DEFAULT_PORT = 8917


def usage(home, cli, msg=''):

    # massage the help. I want [directory [backend]] but there is no way to
    # specify that in argparse, so replace the three positional args with
    # the proper syntax.
    usage = cli.format_help() % dict(locals())
    usage = usage.replace('[directory] [backend] [nuke]',
                          '[[directory] [backend]] [nuke]')

    print("%s\n" % usage)

    if msg:
        print(msg)

def run():
    templates = admin.AdminTool().listTemplates().keys()
    backends = list_backends()

    cli = argparse.ArgumentParser(
        description= """
Instant gratification demo - Roundup Issue Tracker

  Run a demo server. Config and database files are created in
  'directory' (current setting/default '%(home)s') which should
  not exist or should exist and already be a tracker home
  directory (usually used with nuke).

  'nuke' will re-initialize the tracker instance, deleting the old data.

  The tracker that is created will have email notifications turned off.
""" % {"home": DEFAULT_HOME},
        epilog=("\nIf items marked with (*) are missing, they will be "
                "asked for interactively when setting up the tracker."),
        formatter_class=argparse.RawTextHelpFormatter,
        add_help=True)

    cli.add_argument('-B', '--bind_address',
                     default="127.0.0.1",
                     help=( "Choose address for server to listen at.\n"
                            "Use 0.0.0.0 to bind to all addreses. Use\n"
                            "the external name of the computer to bind to\n"
                            "the external host interface.\n"
                            "Default: %(default)s.\n\n"))
    cli.add_argument('-b', '--backend_db',
                     choices=backends,
                     help=( "Choose backend database. Default: %s.\n\n" %
                            DEFAULT_BACKEND))
    cli.add_argument('-H', '--hostname',
                     default="localhost",
                     help=( "Choose hostname for the server.\n"
                            "Default: %(default)s.\n\n"
                            ))
    cli.add_argument('-t', '--template',
                     choices=templates,
                     help="Use specified template. (*)\n\n")
    cli.add_argument('-p', '--port',
                     type=int,
                     help=( "Listen at this port. Default: search for\n"
                            "open port starting at %s\n\n" % DEFAULT_PORT))
    cli.add_argument('-P', '--urlport',
                     type=int,
                     help=( "Set docker external port. If using\n"
                            "   docker ... -p 9090:8917 ...\n"
                            "this should be set to 9090.\n"
                            "Default: as selected by --port\n\n"))
    cli.add_argument('-V', '--version', action='version',
                     version='Roundup version %s'%roundup_version,
                     help=(
                         "Show program's version number: %s and exit\n" %
                         roundup_version))

    cli.add_argument('directory', nargs='?',
                     help="Create home for tracker in directory. (*)\n")

    # add 'nuke' to choices so backend will accept nuke if only 2 args.
    choices = backends + ['nuke']
    cli.add_argument('backend', nargs='?', metavar='backend', choices=choices,
                     help=( "Choose backend database. "
                            "Depricated, use -b instead.\n"
           "If it is used, you *must* specify directory.\n\n"))

    cli.add_argument('nuke', nargs='?', metavar='nuke', choices=['nuke'],
                     help=( "The word 'nuke' will delete tracker and reset.\n"
                            "E.G. %(prog)s -b sqlite \\ \n"
                            "-t classic ./mytracker nuke\n") % {"prog": sys.argv[0]})

    cli_args = cli.parse_args()

    # collect all positional args in order in array to parse
    # strip all None.
    cli_args.cmd = [ x for x in [cli_args.directory, cli_args.backend, cli_args.nuke] if x != None ]

    try:
        nuke = cli_args.cmd[-1] == 'nuke'
        if nuke:
            _ignore = cli_args.cmd.pop()  # remove nuke
    except IndexError:
        nuke = False

    try:
        tracker_home = cli_args.cmd[0]
    except IndexError:
        tracker_home = None

    # invoked as demo tracker_dir sqlite [nuke]
    try:
        cli_backend = cli_args.cmd[1]
    except IndexError:
        cli_backend = None

    home = tracker_home or DEFAULT_HOME
    template = cli_args.template or DEFAULT_TEMPLATE
    backend = cli_args.backend_db or cli_backend or DEFAULT_BACKEND

    if not tracker_home:
        home = my_input(
            _('Enter directory path to create demo tracker [%s]: ') % home)
        if not home:
            home = DEFAULT_HOME

    # if there is no tracker in home, force nuke
    try:
        instance.open(home)
        valid_home = True
    except configuration.NoConfigError:
        nuke = True
        valid_home = False

    # if we are to create the tracker, prompt for settings
    if nuke:
        # FIXME: i'd like to have an option to abort the tracker creation
        #   say, by entering a single dot.  but i cannot think of
        #   appropriate prompt for that.
        if not cli_args.template in templates:
            template = my_input(
            _('Enter tracker template to use (one of (%(template_list)s)) [%(default_template)s]: ') %
            { 'template_list': ','.join(templates),
              'default_template': template})
            if not template:
                template = DEFAULT_TEMPLATE
            elif template not in templates:
                print("Unknown template: %s. Exiting." % template)
                exit(1)
        # install
        url_port = cli_args.urlport or cli_args.port or DEFAULT_PORT
        demo.install_demo(home, backend,
                          admin.AdminTool().listTemplates()[template]['path'],
                          use_port=url_port, use_host=cli_args.hostname)
    else:
        # make sure that no options are specified that are only useful on initialization.
        if ( cli_args.backend or cli_args.template or
             cli_args.backend_db ):
            usage(home, cli, msg=(
                "Specifying backend or template is only allowed when\n"
                "creating a tracker or with nuke.\n"))
            exit(1)
    # run
    demo.run_demo(home, bind_addr=cli_args.bind_address,
                  bind_port=cli_args.port)

if __name__ == '__main__':
    run()

# vim: set et sts=4 sw=4 :
