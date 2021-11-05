# build in root dir using:
#     docker build -t roundup-app --rm -f Dockerfile ..
#
# run using:
#    docker run --rm -v /home/rouilj/develop/roundup.sysadmin/issue.tracker:/usr/src/app/tracker -p 9017:8080 roundup-app:latest

FROM python:3-alpine

ENV appdir=/usr/src/app
WORKDIR $appdir

# allow roundup install from local directory or from pypi
ARG source=local

LABEL "org.roundup-tracker.vendor"="Roundup Issue Tracker Team" \
      "org.roundup-tracker.description"="Roundup Issue Tracker using sqlite" \
      "version"="2.1.0 $source"

# add requirements for pip here, e.g. pytz or other modules
#  ignore warnings from pip to use virtualenv
COPY scripts/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# copy the elements of the release directory to the docker image
COPY setup.py install/
COPY doc install/doc/
COPY frontends install/frontends/
COPY locale install/locale/
COPY roundup install/roundup/
COPY share install/share/

# verify source has one of two valid values then
# install in python3 standard directories from local copy
# or install in python3 standard directories from pypi using pip

RUN if [ "$source" == "local" ] || [ "$source" == "pypi" ]; then :; \
           else echo "invalid value for source: $source"; \
                echo "must be local or pypi"; exit 1; fi; \
    if [ "$source" == "local" ]; then cd install && ./setup.py install; fi; \
    if [ "$source" == "pypi" ]; then pip install roundup; fi

# delete source files
RUN rm -rf install

# map port 8080 to your local port
EXPOSE 8080/tcp

# mount a trackerdir on tracker location
RUN mkdir tracker
VOLUME $appdir/tracker

# do not run roundup as root
RUN adduser -D roundup

# run the server
USER roundup
ENTRYPOINT [ "roundup-server", "-L", "-n", "0.0.0.0" ]

# allow the invoker to override cmd with multiple trackers
# in each subdirectory under $appdir/tracker. E.G.
# docker run .... \
#   issues=tracker/issues foo=tracker/foo
#
# note using "issue=$appdir/tracker" results in error:
#
#  No valid configuration files found in directory /usr/src/app/$appdir/tracker
#
# so $appdir not expanded and $PWD prefixed onto the (relative path)
#   $appdir/tracker. Hence use relative path for spec.
CMD [  "issues=tracker" ]
