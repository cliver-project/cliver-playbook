"""Helpers for deriving isolated test databases from the configured admin DSN."""

from sqlalchemy.engine import make_url


def derive_test_dsn(admin_dsn: str, database: str) -> str:
    """Return ``admin_dsn`` with only the database name replaced.

    Host, port, credentials, and query parameters are preserved, so the test
    database lives wherever ``CLIVER_TEST_DATABASE_URL`` points instead of a
    hardcoded localhost instance.
    """
    url = make_url(admin_dsn).set(database=database)
    return url.render_as_string(hide_password=False)
