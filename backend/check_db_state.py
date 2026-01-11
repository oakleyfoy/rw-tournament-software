import sqlite3

conn = sqlite3.connect("tournament.db")
cursor = conn.cursor()

# Check tables
cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
tables = [row[0] for row in cursor.fetchall()]
print("Tables:", tables)

# Check if scheduleslot table exists and has court_label column
if "scheduleslot" in tables:
    cursor.execute("PRAGMA table_info(scheduleslot)")
    columns = [row[1] for row in cursor.fetchall()]
    print("\nScheduleSlot columns:", columns)
    has_court_label = "court_label" in columns
    print("Has court_label:", has_court_label)
else:
    print("\nScheduleSlot table does not exist")

# Check alembic version
cursor.execute("SELECT version_num FROM alembic_version")
try:
    version = cursor.fetchone()[0]
    print(f"\nCurrent Alembic version: {version}")
except (TypeError, IndexError):
    print("\nNo Alembic version found")

conn.close()
