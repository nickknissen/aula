"""Helpers for turning Aula's ``YYYY-Wnn`` week strings into dates."""

import datetime
import logging

_LOGGER = logging.getLogger(__name__)


def monday_of_week(week: str) -> str:
    """Return the Monday of ``YYYY-Wnn`` as an ISO timestamp with a ``Z`` suffix.

    EasyIQ's portal takes a single ``date`` and answers with the week that
    contains it, so any day of the week would do; Monday keeps it unambiguous.
    Falls back to today when ``week`` cannot be parsed, which is better than
    sending nothing.
    """
    try:
        year_part, week_part = week.split("-W")
        monday = datetime.date.fromisocalendar(int(year_part), int(week_part), 1)
    except ValueError, AttributeError:
        _LOGGER.warning("Could not parse week %r, using today's date instead", week)
        monday = datetime.date.today()
    return f"{monday.isoformat()}T00:00:00Z"
