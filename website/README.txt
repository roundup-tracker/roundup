Roundup has three web sites:

 * https://www.roundup-tracker.org/
 * https://issues.roundup-tracker.org/
 * https://wiki.roundup-tracker.org/

www is hosted on SourceForge, issues is hosted on a python software
foundation host and wiki is hosted at waldman-edv.

Updating services hosted on sf.net (www)
=================================================

Generic SF instructions for web service recommend
uploading files through SFTP, described here:
http://sourceforge.net/p/forge/documentation/Project%20Web%20Services/

Since SFTP is ugly to script in non-interactive mode, we used to use
SSH access to fetch everything and build from server side.

As of June 30, 2026, soureforce no longer allows interactive shell
sessions. So you need to build locally and transfer the built files.

I added some scripted rsync commands to www/Makefile to
automate install of the html subdir to sourceforge.

  sourceforge_dev_sync  sync html directory to sourceforce htdocs/dev_docs
     subdir

  sourceforge_prod_sync  sync html directory to sourceforce production
     website

  sourceforge_prod_pull  sync sourceforce production website to local
     web_html

  sourceforge_home_sync  sync html directory to
    sourceforge:~/roundup_docs

These commands should preserve the file htdocs/ahref*. If you move the
current htdocs/ directory using sftp (and then create a new empty
htdocs), you need to copy the ahref* file from the current production
tree to the new directory so we keep some level of analytics.

Note that sourceforge_prod_sync should create a backup for each
original file in a dated docs_backup-<date>. So should be able to
recover the website by:

  * run `make sourceforge_prod_pull`
  * in the web_html subdirectory, move the files from the
    docs_backup-.... subdir to ther place in web_html
  * replace the www/html directory with www/web_html
  * run make sourceforge_prod_sync

Reverting a sync over SFTP is painful, hence the workflow to copy it
back to your local host.

If you need to do the changes on the sourceforge site, I suggest using
the lftp program with the 'sftp://yourUsername@web.sourceforge.net'
rather than the sftp program as lftp supports recursive directory
removal and other useful features.

Updating the Documentation
--------------------------

Site update requires rebuilding HTML files. For that `sphinx` version
8 or newer is required. You can use the website/www/requirements.pip
file to set up sphinx: `python -m pip install -r requirements.pip` in
a venv. If you install sphinx into a virtual environment, use:

  PATH=/path/to/venv/bin/sphinx-build:$PATH make

when `make` is used below. Also you should run make in the doc
directory beforehand to generate html pages used by the website build
(e.g. man pages, config.ini documentation...).

The whole procedure starting from the root of a current checked out
source tree looks like so:

    hg up <release tag>  # make sure you are using the released code
    cd doc
    make clean
    make
    # cd to website source and build it
    cd ../website/www
    make clean
    make html
    # you can check which files updated (the date will change with many files)
    #make sourceforge_prod_pull
    #diff -ur --brief web_html ./html/
    # copy to website dir
    make sourceforge_prod_sync

If you are generating the docs for an alpha/beta release, use

  make sourceforge_dev_sync

instead of `make sourceforge_prod_sync` to update:

  htdocs/dev-docs/

and the URL will be: https://www.roundup-tracker.org/dev-docs/docs.html

Note there appears to be a cache somewhere in the path, so you may
need to use:

  https://www.roundup-tracker.org/dev-docs/docs.html?foo=1

to cache bust if you do multiple deploys and are seeing an older version.

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

The configuration is tracked in multiple places.
The one used by PSF infrastrcuture is:

   https://github.com/psf/bpo-tracker-roundup

Contact psf infra https://infra.psf.io/overview.html (email:
infrastructure-staff at python dot org) for an invite to their repo.

Usually testing is done with: the "website/issues" section
of Roundup's Mercurical SCM repository and copied manually to the live
tracker.

  * get a working copy of roundup/website/issues from the SCM, either via
        hg clone https://hg.code.sf.net/p/roundup/code
    or download a snapshot:
        https://sourceforge.net/p/roundup/code/ci/default/tarball

  * check the differences
      diff -ur /srv/roundup/trackers/roundup/ roundup/website/issues/

Copy differences using 'sudo -u roundup ...' into production for testing.

Restart the server with:

 sudo service roundup-roundup restart

The git version is what PSF uses if they have to rebuild/move our
tracker. So it's important to keep it up to date.

They also generate the config.ini from an ansible script. So if you
need to change settings in config.ini (e.g. logging from ERROR to
WARNING) and have it persist across (daily+) ansible runs you need to
update:

 pillar/base/bugs.sls

in the https://github.com/python/psf-salt repo and then push it.

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

DNS
===
Thomas Waldman is also our DNS manager. All changes should go to him
at email: info AT waldmann-edv DOT de.

Richard Jones still owns/pays for the roundup-tracker.org domain.
It expires on: 2027-01-06T10:49:58Z.

