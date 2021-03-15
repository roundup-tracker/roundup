Roundup has three web sites:

 * https://www.roundup-tracker.org/
 * https://issues.roundup-tracker.org/
 * https://wiki.roundup-tracker.org/

www is hosted on SourceForge, issues is hosted on a python software
foundation host and wiki is hosted at waldman-edv.

updating services hosted on sf.net (www)
=================================================
Generic SF instructions for web service recommend
uploading files through SFTP, described here:
http://sourceforge.net/p/forge/documentation/Project%20Web%20Services/

However, SFTP is ugly to script in non-interactive
mode, so we use SSH access to fetch everything and
build from server side.

Working with sf.net
-------------------
Current docs are taken down with SourceForge Trac,
so working instructions are available from here:
http://web.archive.org/web/20140618231150/http://sourceforge.net/apps/trac/sourceforge/wiki/Shell%20service

    # log in, replace <user> with your account
    ssh -t <user>,roundup@shell.sourceforge.net create

    # set project_home
    project_home=/home/project-web/roundup

    # pull latest Roundup source with www and wiki
    hg pull -u --cwd ${project_home}/src/roundup
    # see below if this fails with: not trusting file
      # /home/project-web/roundup/src/roundup/.hg/hgrc from untrusted
      # user 110231, group 48

    # read up on other people changes and add yours
    cd ${project_home}
    vim logbuch.txt

If you get a "not trusting" error the problem is that the .hg files in
use are not owned by you and hg won't use them. Add this to your
~/.hgrc file (create file if needed)

[trusted]
groups=48
users=110231

if the uid/gid changes you may have to change the values.
See: https://www.mercurial-scm.org/wiki/Trust for details

When done working in the sf shell, you can destroy it early
to free resources:

    shutdown

updating www.roundup-tracker.org
---------------------------------
Site update requires rebuilding HTML files. For that
`sphinx` is required/
Hopefully, it is already installed into virtualenv, so
the whole procedure looks like so:

    # activate the virtualenv
    . ${project_home}/docbuilder/bin/activate
    # cd to website source and build it
    cd ${project_home}/src/roundup/website/www
    hg up <release tag>  # make sure you are using the released code
    make clean
    make html
    # you can check which files updated (the date will change with many files)
    #diff -ur --brief ${project_home}/htdocs/ ./html/
    # copy to website dir
    cp -r -p ./html/* ${project_home}/htdocs/
    # copy legacy html doc to website docs/ dir
    # (in main doc/conf.py this is done automatically)
    cp -r -p ../../doc/html_extra/* ${project_home}/htdocs/docs/
    # or try it with rsync (skip --dry-run when ready)
    #rsync --dry-run -v --checksum --recursive ./html/* ${project_home}/htdocs/


If you are releasing an alpha/beta release, don't update:

 ${project_home}/htdocs/docs/

instead update:

  ${project_home}/htdocs/dev-docs/

and the URL will be: https://www.roundup-tracker.org/dev-docs/docs.html

Note there appears to be a cache somewhere in the path, so you may
need to use:

  https://www.roundup-tracker.org/dev-docs/docs.html?foo=1

to cache bust.

Updating issues.roundup-tracker.org
===================================

The tracker resides on bugs.ams1.psf.io (188.166.48.69). You can also
ssh to issues.roundup-tracker.org. They have the same fingerprint:

    ED25519 key fingerprint is f1:f7:3d:bf:3b:01:8d:e1:4e:30:b3:0f:6e:98:b8:9b.

The roundup installation belongs to the user roundup. 
The setup uses virtualenv. Use the python version:

  /srv/roundup/env/bin/python2.7

to get a python with roundup on the PYTHONPATH.

The Roundup tracker https://issues.roundup-tracker.org/ is in
/srv/roundup/trackers/roundup/ with the database set to
/srv/roundup/data/roundup/. Note that postgres is used for the
backend, so the database directory above is used for msgs and files.

Source is in: /srv/roundup/src/

Roundup is run using gunicorn and wsgi.

You have 'sudo -u roundup' access if you need to run things as the
roundup user.

The configuration is in the "website/issues" section of Roundup's
Mercurical SCM repository and copied manually to the live tracker.

  * get a working copy of roundup/website/issues from the SCM, either via
        hg clone https://hg.code.sf.net/p/roundup/code
    or download a snapshot:
        https://sourceforge.net/p/roundup/code/ci/default/tarball

  * check the differences
      diff -ur /srv/roundup/trackers/roundup/ roundup/website/issues/

Copy differences using 'sudo -u roundup ...'.

Getting a user account
~~~~~~~~~~~~~~~~~~~~~~

To get access to the host, submit a pull request for:

    https://github.com/python/psf-salt

by forking the repo, make a change similar to:

    https://github.com/rouilj/psf-salt/commit/2aa55d0fc5a343f45f5507437d3fba077cbaf852

and submit it as a pull request. Contact ewdurbin via #roundup IRC or by
adding an issue to the master psf-salt repo.


updating wiki.roundup-tracker.org
=================================
Wiki isn't hosted on sourceforge anymore. See:

 https://issues.roundup-tracker.org/issue2551045

for details on Implementing wiki move to Waldmann-EDV.

Contact Thomas Waldmann. Web site: https://www.waldmann-edv.de/
email: info AT waldmann-edv DOT de.

The sites theme is under wiki/wiki/data/plugin/theme/roundup.py.  Last
updated by emailing Thomas 2/2021. Images/icons and css under
wiki/_static.

Backups are assumed to be done by Waldmann-edv. There does not appear
to be a way to get access to the underlying filesystem via ssh or to
do a backup/tarball via with web.
