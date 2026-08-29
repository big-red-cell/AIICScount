// node gcm_decrypt.mjs <key-b64> <blob-b64>
import crypto from 'crypto';
const key = Buffer.from(process.argv[2], 'base64');
const blob = Buffer.from(process.argv[3], 'base64');
const payload = blob.subarray(3);
const nonce = payload.subarray(0, 12);
const tag = payload.subarray(payload.length - 16);
const ct = payload.subarray(12, payload.length - 16);
try {
  const decipher = crypto.createDecipheriv('aes-256-gcm', key, nonce);
  decipher.setAuthTag(tag);
  const pt = Buffer.concat([decipher.update(ct), decipher.final()]);
  console.log('DECRYPTED:', pt.toString('utf8'));
} catch (e) {
  console.log('FAILED:', e.message);
}
