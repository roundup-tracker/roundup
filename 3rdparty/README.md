# 3rd party libraries for some of the trackers

The files in theis directory are the sources for files that are used
by the trackers and optional functionality. It includes unminified
javascript and source files used to generate javscript and css.

## Bootstrap

To build Boostrap, install [nodejs](http://nodejs.org/) and then do
the following -

```
$ sudo npm install -g connect@2.1.3 hogan.js@2.0.0 jshint@0.9.1 recess@1.1.9 uglify-js@1.3.4
$ make build
```

The files are now located in docs/assets
