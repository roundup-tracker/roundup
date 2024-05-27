# hadolint global ignore=DL3003
# build in root dir using:
#
#     docker build -t roundup-app --rm -f scripts/Dockerfile .
#
# run using:
#
#    docker run --rm -v /.../issue.tracker:/usr/src/app/tracker \
#           -p 9017:8080 roundup-app:latest

# arguments expected to be useful on command line. Lower case names.

# Source of roundup code:
# 'local' directory using setup.py,
# 'pypi[...]' to install latest final or version specified release
#   from PyPI, E.G. pypi=2.4; pypi<2.3 etc. All pip version specifiers
#   are allowed.
# 'pip_local' local directory using pip to install, or
# 'pip_sdist' to install dist/newest_version-tarball
ARG source=local

# Internal settings that are for advanced users to override.

# parameterize the sha256 sum to pin version of python:3-alpine
# Must use the same version in both build stages.
ARG SHA256=5365725a6cd59b72a927628fdda9965103e3dc671676c89ef3ed8b8b0e22e812

# Set to any non-empy value to enable shell debugging for troubleshooting
ARG VERBOSE=

# application directory
ARG appdir=/usr/src/app

# Python version as a.b Used as path component for 
# installation directory and COPY from install dir
# in second build stage.
ARG pythonversion=3.12

#FROM python:3-alpine via SHA256 sum
FROM python@sha256:$SHA256 as build 

# Inherit global values https://github.com/moby/moby/issues/37345
ARG appdir

WORKDIR $appdir

# Update to get security and other improvements;
RUN apk --no-cache upgrade

# Add packages needed to compile mysql, pgsql and other python modules.
# Can't use apk to add python packages as it installs 3.9 python version.
#        g++ installs cc1plus needed by pip install
RUN apk --no-cache add \
    file \
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

ARG pythonversion
# verify that pythonversion matches the one in the image.
RUN image_python_version=$(python -c 'import sys; print("%s.%s"%sys.version_info[0:2])'); \
    if [ "${pythonversion}" != "${image_python_version}" ]; then \
       printf "\n\n*****\npythonversion does not match.\n" ; \
       printf "Add:\n   --build-arg=\"pythonversion=%s\"\nto docker build\n******\n\n" "${image_python_version}"; \
       exit 1; \
    fi

# build xapian bindings:
# file with sphinx build dependencies to remove after build
# they are over 70MB of space.
COPY scripts/Docker/sphinxdeps.txt .

# suppress warning when running pip as root
ENV PIP_ROOT_USER_ACTION=ignore

SHELL ["/bin/ash", "-eo", "pipefail", "-c"]
ARG VERBOSE
ARG pythonversion

RUN [ -z "${VERBOSE}" ] || set -xv; \
    CWD="$PWD" && \
    upgrades=$(python3 -m pip --no-cache --disable-pip-version-check \
	list --outdated | awk 'NR > 2 {print $1}'); \
    if [ -n "$upgrades" ]; then \
        echo "Pip updating $upgrades"; \
        python -m pip --no-cache --disable-pip-version-check \
           install -U $upgrades < /dev/null; \
    else \
        echo "Nothing to pip update"; \
    fi; \
    ls -l /usr/local/lib/python${pythonversion}/site-packages; \
    VER=$(apk list -I 'xapian-core-dev' | \
          sed 's/^xapian-core-dev-\([0-9.]*\)-.*/\1/') && \
    cd /tmp && \
    wget -q "https://oligarchy.co.uk/xapian/$VER/xapian-bindings-$VER.tar.xz" && \
    tar -Jxvf "xapian-bindings-$VER.tar.xz" && \
    cd "xapian-bindings-$VER/" && \
    pip --no-cache-dir install sphinx && \
    sed -i -e '/PYTHON3_SO=/s/distutils\.//g' \
           -e '/PYTHON3_SO=/s/"SO"/"EXT_SUFFIX"/g' \
           -e '/PYTHON3_CACHE_TAG=/s/imp;print(imp.get_tag())/sys;print(sys.implementation.cache_tag)/' \
           -e '/PYTHON3_CACHE_OPT1_EXT=/s/imp\.get_tag()/sys.implementation.cache_tag/g' \
           -e '/PYTHON3_CACHE_OPT1_EXT=/s/imp\b/importlib/g' \
           configure && \
    ./configure --prefix=/usr/local --with-python3 --disable-documentation && \
    make && make install && \
    pip uninstall --no-cache-dir -y sphinx && \
    pip uninstall --no-cache-dir -y -r "$CWD/sphinxdeps.txt" && \
    rm -rf /usr/local/share/doc/xapian-bindings

# add requirements for pip here, e.g. Whoosh, gpg, zstd or other
#   modules not installed in the base library.
# ignore warnings from pip to use virtualenv
COPY scripts/Docker/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# copy the elements of the release directory to the docker image
COPY setup.py install/
COPY doc install/doc/
COPY frontends install/frontends/
COPY locale install/locale/
COPY roundup install/roundup/
COPY share install/share/
# dist/* might not exist, so include README.txt so we don't get an error
#COPY README.txt dist/* install/dist/

# verify source has one of four valid values then
# install in python3 standard directories from:
#  * local copy using setup.py
#  * pypi using pip
#  * local files using pip
#  * pip using a pre-existing sdist built in original source tree: disabled
#  *    copy from dist/* fails if dist directory is missing breaking the
#       Distfile. COPY used to ignore missing files if at least one
#       existing file was copied 8-(.

# import from global/command line
ARG source

RUN [ -z "${VERBOSE}" ] || set -xv; \
    case "$source" in \
        "local") \
            cd install && ./setup.py install;; \
        "pypi"*) \
            version_spec=$( printf "%s" "$source" | \
				sed -ne 's/^pypi\([~=!<>].*\)/\1/p'); \
            pip install --no-cache-dir "roundup${version_spec}"; \
            cp -ril /usr/local/lib/"python${pythonversion}"/site-packages/usr/local/share/* \
               /usr/local/share;; \
        "pip_local") \
	    cd install && \
		pip -V && \
		pip install --no-cache-dir . ;; \
	"pip_sdist") \
	    printf "\n\npip_sdist disabled\n\n" && exit 1 ; \
	    dist=$(find install/dist | sed -ne '/roundup-[0-9].*\.tar\.gz$/p' | tail -n 1); \
	    if [ -z "$dist" ] ; then \
		printf "\n\nUnable to find a source distribution file in dist\n"; \
		printf "Exiting\n\n"; \
		exit 1; \
            fi; \
            printf "Building with distribution: %s\n" "$dist"; \
            pip install --no-cache-dir "install/dist/$dist";; \
        *) \
            printf "\n\ninvalid value for source: $source\n"; \
	    printf "must be local, pypi, pip_local or pip_sdist\n\n"; \
            exit 1;; \
    esac

# Allow user to add more modules during build
ARG pip_mod
RUN if [ -n "$pip_mod" ]; then pip install --no-cache-dir ${pip_mod}; fi

# build a new smaller docker image for execution. Build image above
# is 1G in size.
# FROM python:3-alpine
FROM python@sha256:$SHA256

# import from global
ARG appdir

WORKDIR $appdir

# suppress warning when running pip as root
ENV PIP_ROOT_USER_ACTION=ignore

# upgrade to get any security updates; bundle with
#    rest of apk actions to reduce layers/wasted space 
# add libraries needed to run gpg/mysql/pgsql/brotli
# clean out any caches to save space
# upgrade pip packages to get security and other updates
#   bundle with apk updates
SHELL ["/bin/ash", "-eo", "pipefail", "-c"]
RUN apk --no-cache upgrade; \
    apk --no-cache add \
     brotli-libs \
     dumb-init \
     gpgme \
     mariadb-connector-c \
     libpq \
     libstdc++ \
     libxapian \
     zstd-libs; \
    upgrades=$(python3 -m pip --no-cache --disable-pip-version-check \
	list --outdated | awk 'NR > 2 {print $1}'); \
    if [ -n "$upgrades" ]; then \
        echo "Pip updating $upgrades"; \
        python -m pip --no-cache --disable-pip-version-check \
           install -U $upgrades < /dev/null; \
    else \
        echo "Nothing to pip update"; \
    fi

ARG source
ARG pythonversion
ARG pip_mod
LABEL "org.opencontainers.image.vendor"="Roundup Issue Tracker Team" \
      "org.opencontainers.image.title"="Roundup Issue Tracker" \
      "org.opencontainers.image.description"="Roundup Issue Tracker with multi-backend support installed via $source with python version $pythonversion" \
      "org.opencontainers.image.version"="2.4.0b1" \
      "org.opencontainers.image.authors"="roundup-devel@lists.sourceforge.net" \
      "org.opencontainers.image.licenses"="MIT AND ZPL-2.0 AND Python-2.0" \
      "org.opencontainers.image.documentation"="https://www.roundup-tracker.org/docs/installation.html" \
      "pip-modules"="$pip_mod"


ARG pythonversion
# pull over built assets
COPY --from=build /usr/local/lib/python${pythonversion}/site-packages /usr/local/lib/python${pythonversion}/site-packages/
COPY --from=build /usr/local/bin/roundup* /usr/local/bin/
COPY --from=build /usr/local/share /usr/local/share/
COPY scripts/Docker/roundup_start scripts/Docker/roundup_healthcheck ./

# Do not run roundup as root. This creates roundup user and group.
ARG roundup_uid
RUN adduser -D -h ${appdir} -u ${roundup_uid:-1000} roundup

# make roundup scripts execuable and mount a trackerdir on tracker location
RUN chmod +x roundup_start roundup_healthcheck; \
    mkdir tracker; chown ${roundup_uid:-1000}:${roundup_uid:-1000} tracker
VOLUME $appdir/tracker

# map port 8080 to your local port
EXPOSE 8080/tcp

HEALTHCHECK --start-period=1m \
   CMD ./roundup_healthcheck

# switch to using roundup user
USER roundup

# run the server, disable output buffering so we can see logs.
ENV PYTHONUNBUFFERED=1
#ENTRYPOINT [ "roundup-server", "-n", "0.0.0.0" ]
ENTRYPOINT [ "/usr/bin/dumb-init", "./roundup_start" ]

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
