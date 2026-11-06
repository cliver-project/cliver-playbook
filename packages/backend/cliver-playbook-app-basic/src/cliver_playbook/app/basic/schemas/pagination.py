"""The shared pagination envelope.

Every paginated endpoint returns the same four fields, so a client can write
one pager and one typed decoder instead of reverse-engineering each route:
``items`` is this window, ``total`` is the size of the full filtered set,
and ``limit``/``offset`` echo the window the server actually applied.
"""

from pydantic import BaseModel, Field


class Page[T](BaseModel):
    """One window of a larger, ordered result set.

    ``total`` counts the full filtered set, not the rows in ``items`` — it is
    what makes "next page" decidable. The row order is the endpoint's
    contract; pagination itself only slices it.
    """

    items: list[T]
    total: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)
