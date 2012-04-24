issues.roundup-tracker.org:

 * log into issues.roundup-tracker.org
 * get a working copy of roundup/website/issues from the SCM, either via
   hg clone http://roundup.hg.sourceforge.net:8000/hgroot/roundup/roundup
   or download a snapshot:
   http://roundup.hg.sourceforge.net/hgweb/roundup/roundup/archive/default.tar.gz
 * copy the files into the tracker instance, using sudo:
      sudo -u roundup cp <file> /home/roundup/trackers/roundup/...
 * restart the roundup server:
      sudo -u roundup /etc/init.d/roundup restart

www.roundup-tracker.org:

 * log into sf.net
      ssh -t <user>,roundup@shell.sourceforge.net create
 * set project_home:
      project_home=/home/project-web/roundup
 * activate the virtualenv
      cd ${project_home}
      . docbuilder/bin/activate
 * update the working copy
      cd ${project_home}/src/roundup/website/www
      FIXME hg pull -u
      FIXME ln -s ../../doc/ docs
 * build it
      make html
 * you may also "make clean"
 * install it
      cp -r ./html/* ${project_home}/htdocs/

(I think I can simplify the Makefile above such that the installation will be included as a make target.)

wiki.roundup-tracker.org:

 * log into sf.net
      ssh -t <user>,roundup@shell.sourceforge.net create
 * set project_home:
      project_home=/home/project-web/roundup
 * update the working copy
      cd ${project_home}/src/roundup/website/wiki
      hg pull -u
 * copy the files into the right places:
      cp static/roundup/* ${project_home}/htdocs/_wiki/
      cp wiki/data/plugin/theme/roundup.py ${project_home}/persistent/wiki/data/plugin/theme/
