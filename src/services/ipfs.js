// IPFS pinning helpers for Mint Time.
//
// Two modes, picked based on whether VUE_APP_PINATA_JWT is set in .env:
//   - REAL: POST to Pinata's pinFileToIPFS / pinJSONToIPFS, return the CID.
//   - DEV : skip the network, return a deterministic placeholder ref
//           (`local-<sha256>`) so the rest of the flow (mint, preview,
//           on-chain storage) still works end-to-end without API keys.
//
// The placeholder is NOT a valid IPFS CID and the contract enforces a
// 96-char ceiling on image_ipfs, so leaving DEV mode on for a real mint
// just stores a useless reference — that's intentional, makes it loud.

const PINATA_FILE_ENDPOINT = 'https://api.pinata.cloud/pinning/pinFileToIPFS'
const PINATA_JSON_ENDPOINT = 'https://api.pinata.cloud/pinning/pinJSONToIPFS'

function getJwt() {
  // process.env is webpack-replaced at build time. Only VUE_APP_* vars
  // are exposed by vue-cli — anything else is undefined in the browser.
  return (
    (typeof process !== 'undefined' && process.env && process.env.VUE_APP_PINATA_JWT) ||
    ''
  )
}

export function ipfsConfigured() {
  return Boolean(getJwt())
}

async function sha256Hex(bytes) {
  const buf = await crypto.subtle.digest('SHA-256', bytes)
  return Array.from(new Uint8Array(buf))
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('')
}

/**
 * Pin an image file. Returns `ipfs://<cid>` on success.
 *
 * In DEV mode (no JWT), returns `local-<sha256-first-32>` so the caller
 * still gets a stable, content-addressed reference for previewing.
 */
export async function pinImage(file) {
  if (!(file instanceof File || file instanceof Blob)) {
    throw new Error('pinImage: expected File or Blob')
  }
  const jwt = getJwt()
  if (!jwt) {
    const bytes = new Uint8Array(await file.arrayBuffer())
    const h = await sha256Hex(bytes)
    return `local-${h.slice(0, 40)}`
  }
  const fd = new FormData()
  fd.append('file', file)
  fd.append(
    'pinataMetadata',
    JSON.stringify({ name: `mint-time-${Date.now()}-${file.name || 'capsule'}` }),
  )
  const r = await fetch(PINATA_FILE_ENDPOINT, {
    method: 'POST',
    headers: { Authorization: `Bearer ${jwt}` },
    body: fd,
  })
  if (!r.ok) {
    const detail = await r.text().catch(() => '')
    throw new Error(`Pinata file upload failed: ${r.status} ${detail}`)
  }
  const j = await r.json()
  return `ipfs://${j.IpfsHash}`
}

/**
 * Pin a JSON metadata blob. Returns `ipfs://<cid>`. DEV mode returns
 * `local-<sha256>` of the serialized JSON.
 */
export async function pinJson(obj) {
  const jwt = getJwt()
  if (!jwt) {
    const bytes = new TextEncoder().encode(JSON.stringify(obj))
    const h = await sha256Hex(bytes)
    return `local-${h.slice(0, 40)}`
  }
  const r = await fetch(PINATA_JSON_ENDPOINT, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${jwt}`,
    },
    body: JSON.stringify({ pinataContent: obj }),
  })
  if (!r.ok) {
    const detail = await r.text().catch(() => '')
    throw new Error(`Pinata JSON upload failed: ${r.status} ${detail}`)
  }
  const j = await r.json()
  return `ipfs://${j.IpfsHash}`
}

/**
 * Turn a stored reference into a viewable URL. Handles both real
 * `ipfs://Qm...` strings and DEV-mode `local-...` placeholders (the
 * latter has nothing to fetch — caller decides whether to show a
 * fallback). Returns '' for empty input.
 */
export function ipfsToHttp(ref) {
  if (!ref) return ''
  if (ref.startsWith('local-')) return ''
  if (ref.startsWith('ipfs://')) return `https://ipfs.io/ipfs/${ref.slice(7)}`
  if (ref.startsWith('http://') || ref.startsWith('https://')) return ref
  return `https://ipfs.io/ipfs/${ref}`
}
