Roundup has three web sites:

 * http://www.roundup-tracker.org/
 * https://wiki.roundup-tracker.org/
 * https://issues.roundup-tracker.org/

www and wiki are hosted on SourceForge.


updating issues.roundup-tracker.org
===================================
See doc/developers.txt for details on accessing the new location.


updating wiki.roundup-tracker.org
=================================
Wiki isn't hosted on sourceforge anymore. See:

 https://issues.roundup-tracker.org/issue2551045

for details on Implementing wiki move to Waldmann-EDV.

Bern Reiter will be adding new docs on how to update files (if
possible). Old directions are:

=============

copy new files over to new directories:

    cd ${project_home}/src/roundup/website/wiki
    cp -r -p static/roundup ${project_home}/htdocs/_wiki/
    cp -p wiki/data/plugin/theme/roundup.py ${project_home}/persistent/wiki/data/plugin/theme/
    cd -

If you need to adjust wiki configuration, it is here:

    vim persistent/wiki/wikiconfig.py

==============

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
    # (the warning about "Not trusting file ... " can be ignored
    #  for now https://sourceforge.net/p/forge/site-support/8217/)
    hg pull -u --cwd ${project_home}/src/roundup
    # see below if this fails with: not trusting file
      # /home/project-web/roundup/src/roundup/.hg/hgrc from untrusted
      # user 110231, group 48

    # read up on other people changes and add yours
    cd ${project_home}
    vim logbuch.txt

If you get a "not trusting" error the problem is that the .hg files in
use are not owned by you and hg won;t use them. Add this to your
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
you `sphinx` and `sphinxcontrib-cheeseshop` are required/
Hopefully, they are already installed into virtualenv, so
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


If you are relasing an alpha/beta arelease, don't update:

 ${project_home}/htdocs/docs/

instead update:

  ${project_home}/htdocs/dev-docs/

and the URL will be: http://www.roundup-tracker.org/dev-docs/docs.html

Note there appears to be a cache somewhere in the path, so you may
need to use:

  http://www.roundup-tracker.org/dev-docs/docs.html?foo=1

to cache bust.
