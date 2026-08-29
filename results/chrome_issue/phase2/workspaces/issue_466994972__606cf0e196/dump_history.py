import sqlite3, sys

db = sys.argv[1]
con = sqlite3.connect(db)
cur = con.cursor()
cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
print('tables:', [r[0] for r in cur.fetchall()])
try:
    cur.execute('PRAGMA table_info(downloads)')
    cols = [r[1] for r in cur.fetchall()]
    print('downloads cols:', cols)
    cur.execute('SELECT * FROM downloads')
    rows = cur.fetchall()
    print('rows:', len(rows))
    for r in rows:
        d = dict(zip(cols, r))
        for k in ['id', 'guid', 'target_path', 'current_path', 'total_bytes', 'received_bytes',
                  'state', 'danger_type', 'referrer', 'site_url', 'tab_url', 'tab_referrer_url',
                  'mime_type', 'original_mime_type', 'interrupt_reason', 'etag', 'last_modified']:
            print(' ', k, '=', repr(d.get(k))[:250])
        print('  ---')
except Exception as e:
    print('ERR:', e)
con.close()
