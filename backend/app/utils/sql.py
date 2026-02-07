"""
SQL utilities for consistent handling of query results.

SQLModel/SQLAlchemy may return COUNT results as int or as a 1-tuple/Row.
Use scalar_int() to safely coerce to int everywhere.
"""
from typing import Any


def scalar_int(x: Any) -> int:
    """Convert COUNT/aggregate result to int. Handles int or 1-tuple/Row."""
    try:
        return int(x[0])
    except Exception:
        return int(x)
