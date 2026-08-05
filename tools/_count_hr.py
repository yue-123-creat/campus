import sqlite3
from datetime import datetime

conn = sqlite3.connect("data/campus_safety.db")
total = conn.execute("SELECT COUNT(*) FROM hardware_reports").fetchone()[0]
now = datetime.now()
start = datetime(now.year, now.month, now.day, 0, 0, 0).isoformat()
end = now.isoformat()
in_day = conn.execute(
    "SELECT COUNT(*) FROM hardware_reports WHERE created_at >= ? AND created_at <= ?",
    (start, end),
).fetchone()[0]
asc5000 = conn.execute(
    """
    SELECT COUNT(*) FROM (
      SELECT 1 FROM hardware_reports
      WHERE created_at >= ? AND created_at <= ?
      ORDER BY created_at ASC
      LIMIT 5000
    )
    """,
    (start, end),
).fetchone()[0]
# max created in asc first 5000
mx = conn.execute(
    """
    SELECT MAX(created_at) FROM (
      SELECT created_at FROM hardware_reports
      WHERE created_at >= ? AND created_at <= ?
      ORDER BY created_at ASC
      LIMIT 5000
    )
    """,
    (start, end),
).fetchone()[0]
print("total_hardware_reports", total)
print("today_window_count", in_day)
print("first_5000_asc_max_created_at", mx)
conn.close()
