$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Security
Add-Type -AssemblyName System.Core
$ls = Get-Content "$env:LOCALAPPDATA\Google\Chrome\User Data\Local State" -Raw | ConvertFrom-Json
$encKey = [Convert]::FromBase64String($ls.os_crypt.encrypted_key)
$key = [Security.Cryptography.ProtectedData]::Unprotect($encKey[5..($encKey.Length-1)], $null, [Security.Cryptography.DataProtectionScope]::CurrentUser)
"key len: $($key.Length)"
$rows = Get-Content "$PSScriptRoot\repro_blobs.json" -Raw | ConvertFrom-Json
foreach ($row in $rows) {
  $blob = [Convert]::FromBase64String($row.blob_b64)
  $payload = $blob[3..($blob.Length-1)]
  $nonce = $payload[0..11]
  $tag = $payload[($payload.Length-16)..($payload.Length-1)]
  $ct = $payload[12..($payload.Length-17)]
  try {
    $aes = [Security.Cryptography.AesGcm]::new($key, 16)
    $pt = [byte[]]::new($ct.Length)
    $aes.Decrypt($nonce, $ct, $tag, $pt)
    "GCM-DECRYPTED: $($row.url) user=$($row.user) -> '$([Text.Encoding]::UTF8.GetString($pt))'"
  } catch {
    "GCM FAILED for $($row.user): $($_.Exception.Message)"
  }
}
