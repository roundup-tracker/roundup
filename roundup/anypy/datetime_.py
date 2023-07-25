# https://issues.roundup-tracker.org/issue2551278
# datetime.utcnow deprecated
try:
    from datetime import now, UTC

    def utcnow():
        return now(UTC)
except ImportError:
    import datetime

    def utcnow():
        return datetime.datetime.utcnow()
