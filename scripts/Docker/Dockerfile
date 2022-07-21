# build in root dir using:
#
#     docker build -t roundup-app --rm -f scripts/Dockerfile .
#
# run using:
#
#    docker run --rm -v /.../issue.tracker:/usr/src/app/tracker \
#           -p 9017:8080 roundup-app:latest


# Global vars for all build stages

# application directory
ARG appdir=/usr/src/app

# support roundup install from 'local' directory,
# 'local_pip' local directory using pip to install or
# latest release from 'pypi'
ARG source=local

FROM python:3-alpine as build

# Inherit global values https://github.com/moby/moby/issues/37345
ARG appdir

WORKDIR $appdir

# Add packages needed to compile mysql, pgsql and other python modules.
# Can't use apk to add them as that installs a 3.9 python version.
#        g++ installs cc1plus needed by pip install
RUN apk add \
    g++ \
    gcc \
    gpgme-dev \
    libxapian \
    linux-headers \
    make \
    musl-dev \
    mysql-dev \
    postgresql-dev \
    swig \
    xapian-core-dev

# build xapian bindings:
# file with sphinx build dependencies to remove after build
# they are over 70MB of space.
COPY scripts/Docker/sphinxdeps.txt .

RUN set -xv && CWD=$PWD && \
    VER=$(apk list -I 'xapian-core-dev' | \
          sed 's/^xapian-core-dev-\([0-9.]*\)-.*/\1/') && \
    cd /tmp && \
    wget https://oligarchy.co.uk/xapian/$VER/xapian-bindings-$VER.tar.xz && \
    tar -Jxvf xapian-bindings-$VER.tar.xz && \
    cd xapian-bindings-$VER/ && \
    pip --no-cache-dir install sphinx && \
    ./configure --prefix=/usr/local --with-python3 --disable-documentation && \
    make && make install && \
    pip uninstall --no-cache-dir -y sphinx && \
    pip uninstall --no-cache-dir -y -r $CWD/sphinxdeps.txt

# add requirements for pip here, e.g. Whoosh, gpg, zstd or other
#   modules not installed in the base library.
# ignore warnings from pip to use virtualenv
COPY scripts/Docker/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Allow user to add more modules during build
ARG pip_mod
RUN if [ -n "$pip_mod" ]; then pip install --no-cache-dir ${pip_mod}; fi

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
# import from global/command line
ARG source
RUN set -xv && if [ "$source" = "local" ] ||  \
                  [ "$source" = "pypi"  ] || \
                  [ "$source" = "local_pip"   ]; then :; \
           else echo "invalid value for source: $source"; \
                echo "must be local or pypi"; exit 1; fi; \
    if [ "$source" = "local" ]; then cd install && ./setup.py install; fi; \
    if [ "$source" = "local_pip" ]; then cd install && pip install \
                            --use-feature=in-tree-build . ; fi; \
    if [ "$source" = "pypi" ]; then pip install roundup; \
       cp -ril /usr/local/lib/python3.10/site-packages/usr/local/share/* \
	   /usr/local/share; fi

# build a new smaller docker image for execution. Build image above
# is 1G in size.
FROM python:3-alpine

# import from global
ARG appdir

WORKDIR $appdir

# add libraries needed to run gpg/mysql/pgsql/brotli
RUN apk add \
     gpgme \
     mariadb-connector-c \
     libpq \
     libstdc++ \
     libxapian

ARG source
LABEL "org.roundup-tracker.vendor"="Roundup Issue Tracker Team" \
      "org.roundup-tracker.description"="Roundup Issue Tracker using sqlite" \
      "version"="2.1.0 $source" \
      "org.opencontainers.image.authors"="roundup-devel@lists.sourceforge.net"


# pull over built assets
COPY --from=build /usr/local/lib/python3.10/site-packages /usr/local/lib/python3.10/site-packages/
COPY --from=build /usr/local/bin/roundup* /usr/local/bin/
COPY --from=build /usr/local/share /usr/local/share/
COPY scripts/Docker/roundup_start .
COPY scripts/Docker/roundup_healthcheck .

# make roundup scripts execuable and mount a trackerdir on tracker location
RUN chmod +x roundup_start roundup_healthcheck; mkdir tracker
VOLUME $appdir/tracker

# map port 8080 to your local port
EXPOSE 8080/tcp

HEALTHCHECK --start-period=1m \
   CMD ./roundup_healthcheck

# do not run roundup as root. This creates roundup user and group.
ARG roundup_uid
RUN adduser -D -h ${appdir} -u ${roundup_uid:-1000} roundup
USER roundup

# run the server, disable output buffering so we can see logs.
ENV PYTHONUNBUFFERED=1
#ENTRYPOINT [ "roundup-server", "-n", "0.0.0.0" ]
ENTRYPOINT [ "./roundup_start" ]

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
