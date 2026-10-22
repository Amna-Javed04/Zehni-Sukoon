import sqlite3
con = sqlite3.connect("instance/zehni_test.db")
cur = con.execute(
    "UPDATE users SET is_admin = 1 WHERE lower(email) = lower(?)",
    ("admin123@gmail.com",),
)
con.commit()
print("rows updated:", cur.rowcount)