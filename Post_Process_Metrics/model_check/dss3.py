"""Datetime conversion shared by pydsstools 3 and persisted run caches."""


def dss_datetimes(record):
    """Return Python datetimes, preserving empty-series and cache semantics."""
    times = getattr(record, 'times', None)
    if times is None:
        return None
    return [value.datetime() if callable(getattr(value, 'datetime', None)) else value
            for value in times]
