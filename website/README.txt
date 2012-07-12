issues.roundup-tracker.org:

 * log into issues.roundup-tracker.org
 * get a working copy of roundup/website/issues from the SCM, either via
   hg clone http://roundup.hg.sourceforge.net:8000/hgroot/roundup/roundup
   or download a snapshot:
   http://roundup.hg.sourceforge.net/hgweb/roundup/roundup/archive/default.tar.gz
 * copy the files into the tracker instance, using sudo:
      sudo -u roundup cp <file> /home/roundup/trackers/roundup/...
   or use rsync to check and only copy the changes files as user roundup like
      rsync -rvc /home/YOURUSERID/roundup/website/issues/ trackers/roundup/
 * restart the roundup server:
      sudo /etc/init.d/roundup restart

[1] All services hosted on sf.net:
 * log into sf.net
   http://sourceforge.net/apps/trac/sourceforge/wiki/Shell%20service
      ssh -t <user>,roundup@shell.sourceforge.net create
 * set project_home:
      project_home=/home/project-web/roundup
      cd ${project_home}
 * read up on other people changes and add yours
      vim ${project_home}/logbuch.txt
 * update the working copy of the SCM roundup source (includes www and wiki)
      cd ${project_home}/src/roundup
      hg pull -u /home/scm_hg/r/ro/roundup/roundup
   (The warning about "Not trusting file 
   /home/scm_hg/r/ro/roundup/roundup/.hg/hgrc from untrusted user" 
   can be ignored.)

www.roundup-tracker.org:
 * follow [1].
 * activate the virtualenv
      . ${project_home}/docbuilder/bin/activate
 * go to the now current source directory
      cd ${project_home}/src/roundup/website/www
 * build it
      make html
 * you may also "make clean"
 * install it
      cp -r ./html/* ${project_home}/htdocs/

(I think I can simplify the Makefile above such that the installation will be included as a make target.)

wiki.roundup-tracker.org:
 * follow [1].
 * go to the now current source directory
      cd ${project_home}/src/roundup/website/wiki
 * copy the files into the right places:
      cp static/roundup/* ${project_home}/htdocs/_wiki/
      cp wiki/data/plugin/theme/roundup.py ${project_home}/persistent/wiki/data/plugin/theme/
