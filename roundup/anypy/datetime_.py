# https://issues.roundup-tracker.org/issue2551278
# datetime.utcnow deprecated
try:
    from datetime import UTC, datetime

    def utcnow():
        return datetime.now(UTC)

except ImportError:
    from datetime import datetime

    def utcnow():
        return datetime.utcnow()
