issues.roundup-tracker.org:

 * log into issues.roundup-tracker.org
 * get a working copy of web/trunk/issues
 * copy the files into the tracker instance, using sudo:
       sudo -u roundup cp <file> /home/roundup/trackers/roundup/...
 * restart the roundup server:
       sudo -u roundup /etc/init.d/roundup restart

www.roundup-tracker.org:
 
 * project_home=/home/groups/r/ro/roundup

 * log into sf.net
      ssh -t <user>,roundup@shell.sourceforge.net create
 * update the working copy
      cd ${project_home}/src/web/www
      svn update
 * (Update the roundup source docs directory as well?)
 * make sure PATH includes ${project_home}/bin, and PYTHONPATH includes ${project_home}/lib/python
 * build it
      make [clean] html
      # with clean ignore: "loading pickled environment... failed"
 * make sure you leave all files writable for the group "roundup"
      chmod g+rw -R .
 * install it
      cp -r ./html/* ${project_home}/htdocs/

(I think I can simplify the Makefile above such that the installation will be included as a make target.)

wiki.roundup-tracker.org:

 * log into sf.net (see above)
 * update the working copy
       cd /home/r/ro/roundup/src/web/wiki
       svn update
 * copy the files into the right places:
       - cp static/roundup/* ${project_home}/htdocs/_wiki/
       - cp wiki/data/plugin/theme/roundup.py ${project_home}/persistent/wiki/data/plugin/theme/ 
