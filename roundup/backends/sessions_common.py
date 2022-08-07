import base64, logging

import roundup.anypy.random_ as random_
from roundup.anypy.strings import b2s

logger = logging.getLogger('roundup.hyperdb.backend.sessions')
if not random_.is_weak:
    logger.debug("Importing good random generator")
else:
    logger.warning("**SystemRandom not available. Using poor random generator")


class SessionCommon:

    def log_debug(self, msg, *args, **kwargs):
        """Log a message with level DEBUG."""

        logger = self.get_logger()
        logger.debug(msg, *args, **kwargs)

    def log_info(self, msg, *args, **kwargs):
        """Log a message with level INFO."""

        logger = self.get_logger()
        logger.info(msg, *args, **kwargs)

    def log_warning(self, msg, *args, **kwargs):
        """Log a message with level INFO."""
        logger = self.get_logger()
        logger.warning(msg, *args, **kwargs)

    def get_logger(self):
        """Return the logger for this database."""

        # Because getting a logger requires acquiring a lock, we want
        # to do it only once.
        if not hasattr(self, '__logger'):
            self.__logger = logging.getLogger('roundup.hyperdb.backends.%s' %
                                              self.name or "basicdb" )

        return self.__logger

    def getUniqueKey(self, length=40):
        otk = b2s(base64.urlsafe_b64encode(
            random_.token_bytes(length))).rstrip('=')
        while self.exists(otk):
            otk = b2s(base64.urlsafe_b64encode(
                random_.token_bytes(length))).rstrip('=')

        return otk
