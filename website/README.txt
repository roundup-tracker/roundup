Roundup has three web sites:

 * http://www.roundup-tracker.org/
 * http://wiki.roundup-tracker.org/
 * http://issues.roundup-tracker.org/

www and wiki are hosted on SourceForge.


updating issues.roundup-tracker.org
===================================

 * log into issues.roundup-tracker.org
 * get a working copy of roundup/website/issues from the SCM, either via
   hg clone http://hg.code.sf.net/p/roundup/code
   or download a snapshot:
   http://sourceforge.net/p/roundup/code/ci/default/tarball

 * check the differences
   diff -ur /home/roundup/trackers/roundup/ /home/YOURUSERID/roundup/website/issues/
 * copy the files into the tracker instance, using sudo:
      sudo -u roundup cp <file> /home/roundup/trackers/roundup/...
   or use rsync to check and only copy the changed files as user roundup like
      rsync -rvc /home/YOURUSERID/roundup/website/issues/ trackers/roundup/
      HINT: old files will not be deleted by this rsync command 
 * restart the roundup server:
      sudo /etc/init.d/roundup restart


updating services hosted on sf.net (www and wiki)
=================================================
Generic SF instructions for web service recommend
uploading files through SFTP, described here:
http://sourceforge.net/p/forge/documentation/Project%20Web%20Services/

However, SFTP is ugly to script in non-interactive
mode, so we use SSH access to fetch everything and
build from server side.

logging into sf.net
-------------------
Current docs are taken down with SourceForge Trac,
so working instructions are available from here:
http://web.archive.org/web/20140618231150/http://sourceforge.net/apps/trac/sourceforge/wiki/Shell%20service

    # log in, replace <user> with your account
    ssh -t <user>,roundup@shell.sourceforge.net create

    # set project_home and go there
    project_home=/home/project-web/roundup
    cd ${project_home}

    # read up on other people changes and add yours
    vim logbuch.txt

    # pull latest Roundup source with www and wiki
    # (the warning about "Not trusting file ... " can be ignored
    #  for now https://sourceforge.net/p/forge/site-support/8217/)
    hg pull -u --cwd src/roundup


updating wiki.roundup-tracker.org
---------------------------------
wiki doesn't require building anything, so if you're
logged in to SF (see above), just copy new files over
to new directories:

    cd ${project_home}/src/roundup/website/wiki
    cp -r -p static/roundup ${project_home}/htdocs/_wiki/
    cp -p wiki/data/plugin/theme/roundup.py ${project_home}/persistent/wiki/data/plugin/theme/
    cd -

If you need to adjust wiki configuration, it is here:

    vim persistent/wiki/wikiconfig.py


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
    make clean
    make html
    # you can check which files updated
    #diff -qur ./html/ ${project_home}/htdocs/
    # copy to website dir
    cp -r -p ./html/* ${project_home}/htdocs/
    # or try it with rsync (skip --dry-run when ready)
    #rsync --dry-run -v --checksum --recursive ./html/* ${project_home}/htdocs/

When done working in the shell, you can destroy it early
to free resources:

    shutdown
