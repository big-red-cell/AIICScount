import sqlite3, json, os, base64, sys
ud = os.environ['LOCALAPPDATA'] + r'\Google\Chrome\User Data'
con = sqlite3.connect(os.path.join(ud, 'Default', 'Login Data'))
cur = con.cursor()
cur.execute("SELECT origin_url, username_value, password_value FROM logins")
rows = cur.fetchall()
out = []
for url, user, pwd in rows:
    if user.startswith('repro'):
        out.append({'url': url, 'user': user, 'blob_b64': base64.b64encode(pwd).decode()})
json.dump(out, open(sys.argv[1], 'w'))
print('exported', len(out), 'repro rows')
con.close()
