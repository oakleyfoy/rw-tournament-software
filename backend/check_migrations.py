#!/usr/bin/env python3
"""Quick script to check if schedule tables exist in the database"""

import sys

from sqlalchemy import inspect

from app.database import engine


def check_tables():
    """Check if required schedule tables exist"""
    inspector = inspect(engine)
    existing_tables = inspector.get_table_names()

    required_tables = ["scheduleversion", "scheduleslot", "match", "matchassignment"]

    print("Checking for required schedule tables...")
    print(f"Database: {engine.url}")
    print()

    missing_tables = []
    for table in required_tables:
        if table in existing_tables:
            print(f"✓ {table} exists")
        else:
            print(f"✗ {table} MISSING")
            missing_tables.append(table)

    print()
    if missing_tables:
        print("ERROR: Missing tables detected!")
        print("Run migrations with: alembic upgrade head")
        return False
    else:
        print("All required tables exist!")
        return True


if __name__ == "__main__":
    try:
        success = check_tables()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"Error checking tables: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
