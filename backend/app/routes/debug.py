from fastapi import APIRouter
from sqlalchemy import text

from app.database import engine
from app.db_schema_patch import _is_sqlite

router = APIRouter()


@router.get("/debug/events-columns")
def debug_events_columns():
    """Debug endpoint to verify event table columns"""
    from app.models.event import Event

    table_name = Event.__table__.name

    if _is_sqlite(engine):
        with engine.connect() as conn:
            res = conn.execute(text(f"PRAGMA table_info({table_name});")).fetchall()
            return {"db": "sqlite", "table": table_name, "columns": [{"name": r[1], "type": r[2]} for r in res]}
    else:
        sql = """
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = :table_name
        ORDER BY ordinal_position;
        """
        with engine.connect() as conn:
            res = conn.execute(text(sql), {"table_name": table_name}).fetchall()
            return {"db": "postgres", "table": table_name, "columns": [{"name": r[0], "type": r[1]} for r in res]}
