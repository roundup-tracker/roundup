'''Roundup basic logging support.

This module will use the standard Python logging implementation when
available. If not, then a basic logging implementation, BasicLogging and
BasicLoggingChannel will be used.

Configuration for "logging" module:
 - tracker configuration file specifies the location of a logging
   configration file as LOGGING_CONFIG
 - roundup-server and roundup-mailgw specify the location of a logging
   configuration file on the command line
Configuration for "BasicLogging" implementation:
 - tracker configuration file specifies the location of a log file
   LOGGING_FILENAME
 - tracker configuration file specifies the level to log to as
   LOGGING_LEVEL
 - roundup-server and roundup-mailgw specify the location of a log
   file on the command line
 - roundup-server and roundup-mailgw specify the level to log to on
   the command line

In both cases, if no logfile is specified then logging will simply be sent
to sys.stderr with only logging of ERROR messages.

In terms of the Roundup code using the logging implementation:
 - a "logging" object will be available on the "config" object for each
   tracker
 - the roundup-server and roundup-mailgw code will have a global "logging"
   object.

It is intended that the logger API implementation here be the same as (or
close enough to) that of the standard Python library "logging" module.
'''
import sys, time, traceback

class BasicLogging:
    LVL_DEBUG = 4
    LVL_INFO = 3
    LVL_WARNING= 2
    LVL_ERROR= 1
    LVL_NONE = 0
    NAMES = {
        LVL_DEBUG: 'DEBUG',
        LVL_INFO: 'INFO',
        LVL_WARNING: 'WARNING',
        LVL_ERROR: 'ERROR',
    }
    level = LVL_INFO
    loggers = {}
    file = None
    def getLogger(self, name):
        return self.loggers.setdefault(name, BasicLogger(self.file, self.level))
    def fileConfig(self, filename):
        '''User is attempting to use a config file, but the basic logger
        doesn't support that.'''
        raise RuntimeError, "File-based logging configuration requires "\
            "the logging package."
    def setFile(self, file):
        '''Set the file to log to. "file" is either an open file object or
        a string filename to append entries to.
        '''
        if isinstance(file, type('')):
            file = open(file, 'a')
        self.file = file
    def setLevel(self, level):
        '''Set the maximum logging level. "level" is either a level number
        (one of the LVL_ values) or a string level name.
        '''
        if isinstance(level, type('')):
            for num, name in self.NAMES.items():
                if name == level:
                    level = num
        self.level = level

class BasicLogger:
    '''Used when the standard Python library logging module isn't available.
    
    Supports basic configuration through the tracker config file vars
    LOGGING_LEVEL and LOGGING_FILENAME.'''
    def __init__(self, file, level):
        self.file = file
        self.level = level
        self.format = '%(time)s %(level)s %(message)s'

    def setFile(self, file):
        '''Set the file to log to. "file" is either an open file object or
        a string filename to append entries to.
        '''
        if isinstance(file, type('')):
            file = open(file, 'a')
        self.file = file
    def setLevel(self, level):
        '''Set the maximum logging level. "level" is either a level number
        (one of the LVL_ values) or a string level name.
        '''
        if isinstance(level, type('')):
            for num, name in BasicLogging.NAMES.items():
                if name == level:
                    level = num
        self.level = level
    def setFormat(self, format):
        self.format = format
    def write(self, level, message):
        info = {
            'time': time.strftime('%Y-%m-%d %H:%M:%D'),
            'level': BasicLogging.NAMES[level],
            'message': message
        }
        message = self.format%info
        self._write(message)
        self._write('\n')
    def _write(self, text):
        file = self.file or sys.stderr
        file.write(text)
    def debug(self, message):
        if self.level < BasicLogging.LVL_DEBUG: return
        self.write(BasicLogging.LVL_DEBUG, message)
    def info(self, message):
        if self.level < BasicLogging.LVL_INFO: return
        self.write(BasicLogging.LVL_INFO, message)
    def warning(self, message):
        if self.level < BasicLogging.LVL_WARNING: return
        self.write(BasicLogging.LVL_WARNING, message)
    def error(self, message):
        if self.level < BasicLogging.LVL_ERROR: return
        self.write(BasicLogging.LVL_ERROR, message)
    def exception(self, message):
        if self.level < BasicLogging.LVL_ERROR: return
        self.write(BasicLogging.LVL_ERROR, message)
        self._write(traceback.format_exception(*(sys.exc_info())))

