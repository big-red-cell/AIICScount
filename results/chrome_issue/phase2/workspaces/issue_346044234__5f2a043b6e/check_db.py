import sqlite3, sys
con = sqlite3.connect(sys.argv[1])
cur = con.cursor()
cur.execute("SELECT COUNT(*) FROM logins")
print("total logins:", cur.fetchone()[0])
cur.execute("SELECT origin_url, username_value FROM logins WHERE username_value LIKE 'repro%'")
rows = cur.fetchall()
for r in rows:
    print("REPRO FOUND:", r)
if not rows:
    print("no repro credentials in this DB")
cur.execute("SELECT origin_url, username_value FROM logins LIMIT 8")
for r in cur.fetchall():
    print(r)
con.close()
