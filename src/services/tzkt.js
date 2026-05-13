// Thin wrapper around the TzKT indexer API.
//
// All UI components should read on-chain state through this module instead of
// calling fetch() against tzkt.io directly. Centralising the access:
//   - keeps URL construction in one place,
//   - lets us switch networks (or indexers) by changing constants.js,
//   - applies a uniform timeout + retry + null-on-failure policy,
//   - keeps components from each handling their own network errors.
//
// Note: the games live on ghostnet but the TXL NFT collection is on mainnet,
// so this module has to support both simultaneously. Each function accepts
// an optional { network } override; the default comes from constants.NETWORK.
//
// Docs: https://api.tzkt.io/

import { TZKT_API_URL } from '../constants'

const DEFAULT_TIMEOUT_MS = 8000
const DEFAULT_RETRIES = 1

/** Map a network name to its TzKT base URL. */
export function tzktBaseUrl(network) {
  if (!network) return TZKT_API_URL
  return network === 'mainnet' ? 'https://api.tzkt.io' : `https://api.${network}.tzkt.io`
}

/**
 * Low-level GET against TzKT. Returns parsed JSON, or `null` on any failure.
 * Never throws — callers can write `if (!data) return` and move on.
 *
 * @param path     A path starting with `/v1/...` OR a full https URL.
 * @param options  { network, timeoutMs, retries }
 */
export async function tzktGet(
  path,
  { network, timeoutMs = DEFAULT_TIMEOUT_MS, retries = DEFAULT_RETRIES } = {}
) {
  const url = path.startsWith('http') ? path : `${tzktBaseUrl(network)}${path}`

  for (let attempt = 0; attempt <= retries; attempt++) {
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), timeoutMs)
    try {
      const response = await fetch(url, { signal: controller.signal })
      clearTimeout(timer)
      if (!response.ok) {
        console.warn(`[tzkt] ${response.status} ${response.statusText} for ${url}`)
        return null
      }
      return await response.json()
    } catch (err) {
      clearTimeout(timer)
      if (attempt === retries) {
        console.warn(`[tzkt] ${url} failed: ${err.name === 'AbortError' ? 'timeout' : err.message}`)
        return null
      }
      // Small backoff before retry.
      await new Promise((r) => setTimeout(r, 250))
    }
  }
  return null
}

/**
 * Some contracts in constants.js are placeholders (e.g.
 * "KT1XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX") for entries that haven't been
 * deployed yet. Polling them spams TzKT with 400 responses every refresh
 * cycle. Detect that pattern and short-circuit before hitting the network.
 */
function isPlaceholderAddress(addr) {
  return !addr || /^KT1X{10,}/.test(addr)
}

/**
 * Fetch the storage object for a contract.
 * https://api.tzkt.io/#operation/Contracts_GetStorage
 */
export const getContractStorage = (contractAddress, options) => {
  // Note: BLOCKCHAIN_ENABLED guards live in the components that *poll* these
  // endpoints, not here. Read-only TzKT lookups are harmless and we rely on
  // isPlaceholderAddress() below to silence the obvious offenders.
  if (isPlaceholderAddress(contractAddress)) return Promise.resolve(null)
  return tzktGet(`/v1/contracts/${contractAddress}/storage`, options)
}

/**
 * Look up a single key in a TzKT-indexed bigmap by id.
 *
 * Optional `params` can pass any additional query params TzKT supports
 * (e.g. `select`, `value.eq`, `active`).
 *
 * https://api.tzkt.io/#operation/BigMaps_GetKeys
 */
export function getBigmapKey(bigmapId, key, params = {}, options = {}) {
  // Bigmap reads are always allowed — the TXL NFT collection (mainnet) reads
  // through here regardless of whether contract WRITES are kill-switched.
  const query = new URLSearchParams({ 'key.eq': String(key), ...params }).toString()
  return tzktGet(`/v1/bigmaps/${bigmapId}/keys?${query}`, options)
}

/** Convenience: chain head — useful as a connectivity probe. */
export const getHead = (options) => tzktGet('/v1/head', options)
