import json, base64, sqlite3, sys, os
import ctypes
from ctypes import wintypes

# DPAPI via ctypes
class DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

def dpapi_unprotect(blob):
    inb = DATA_BLOB(len(blob), ctypes.cast(ctypes.create_string_buffer(blob), ctypes.POINTER(ctypes.c_char)))
    outb = DATA_BLOB()
    if not ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(inb), None, None, None, None, 0, ctypes.byref(outb)):
        raise OSError("DPAPI unprotect failed")
    data = ctypes.string_at(outb.pbData, outb.cbData)
    ctypes.windll.kernel32.LocalFree(outb.pbData)
    return data

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding as sym_padding

ud = os.environ['LOCALAPPDATA'] + r'\Google\Chrome\User Data'
ls = json.load(open(os.path.join(ud, 'Local State'), encoding='utf-8'))
enc_key = base64.b64decode(ls['os_crypt']['encrypted_key'])
assert enc_key[:5] == b'DPAPI'
key = dpapi_unprotect(enc_key[5:])
print('os_crypt key length:', len(key))

con = sqlite3.connect(os.path.join(ud, 'Default', 'Login Data'))
cur = con.cursor()
cur.execute("SELECT origin_url, username_value, password_value FROM logins")
rows = cur.fetchall()
print('logins:', len(rows))
for url, user, pwd in rows:
    if user.startswith('repro'):
        if pwd.startswith(b'v10'):
            iv = b' 0 1 2 3 4 5 6 7 8 9 10 11'
            cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
            dec = cipher.decryptor().update(pwd[3:]) + cipher.decryptor().finalize()
            unp = sym_padding.PKCS7(128).unpadder()
            plain = unp.update(dec) + unp.finalize()
            print(f'DECRYPTED v10 {url} {user} -> {plain!r}')
        elif pwd.startswith(b'v11'):
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            nonce, ct = pwd[3:15], pwd[15:]
            plain = AESGCM(key).decrypt(nonce, ct, None)
            print(f'DECRYPTED v11 {url} {user} -> {plain!r}')
        else:
            plain = dpapi_unprotect(pwd)
            print(f'DECRYPTED dpapi {url} {user} -> {plain!r}')
con.close()
