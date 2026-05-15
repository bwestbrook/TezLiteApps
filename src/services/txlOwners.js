// TXL ownership data source for the explorer UI.
//
// Two modes:
//   1. loadSnapshot()  — instantly returns the {token_id → owner} map baked
//      into public/txl-owners-snapshot.json. Cheap, no network.
//   2. fetchLive()     — single tzkt request that pulls current owners for
//      every TXL token in one shot using the bigmap key.nat.in= filter.
//
// Typical usage in a component:
//
//   import { loadOwners } from '@/services/txlOwners'
//
//   created() {
//     loadOwners().then(({ owners, topHolders, fetchedAt }) => {
//       this.owners      = owners       // { '60199': 'tz1...', ... }
//       this.topHolders  = topHolders   // [['tz1...', 16], ...]
//       this.snapshotAt  = fetchedAt
//     })
//   }
//
// loadOwners() resolves once with the freshest data available, so a single
// .then() always works. To paint progressively, pass an `onUpdate` callback:
// it fires immediately with the snapshot, then again with the live data when
// the background tzkt fetch lands.
//
// To regenerate the snapshot: see reports/txl-owners-README.md (run
// src/services/reconcile_txl_owners.py — it writes the same data to
// reports/txl-owners-<ts>.csv/.md, then copy the JSON to
// public/txl-owners-snapshot.json).

import { tzktGet } from './tzkt'

const SNAPSHOT_URL = '/txl-owners-snapshot.json'
const TXL_OWNER_BIGMAP = 857

// The objkt.com marketplace contract. Tokens held here are listed for sale,
// not owned by a collector — components should label them accordingly.
export const OBJKT_MARKETPLACE = 'KT1FvqJwEDWb1Gwc55Jd1jjTHRVWbYKUUpyq'

// Full set of Kalamint token IDs the TXL manager tracks. Keep in sync with
// idLookUp in browseNFTs.vue and src/services/smart_contract_txl.py.
export const TXL_TOKEN_IDS = [
  60199, 60200, 60201, 60202, 60203, 60204, 60206, 60207, 60208, 60209,
  60210, 60211, 60212, 60213, 60215, 60216, 60218, 60219, 60220, 60221,
  60224, 60225, 60226, 60227, 60228, 60230, 60231, 60233, 60234, 60235,
  60236, 60237, 60238, 60239, 60240, 60241, 60242, 60243, 60244, 60245,
  60246, 60247, 60248, 60249, 60250, 60251, 60252, 60253, 60254, 60255,
  60256, 60257, 60258, 60259, 60260, 60338, 60339, 60340, 60344, 60346,
  60348, 60349, 60350, 60354, 60355, 60356, 60357, 60358, 60359, 60361,
  60362, 60363, 60366, 60367, 60368, 60369, 60370, 60371, 60372, 60373,
  60374, 60375, 60377, 60379, 60380, 60381, 60382, 60383, 60384, 60386,
  60387, 60388, 60389, 60391, 60392, 60393, 60394, 60395, 60396, 60397,
  60399, 60401, 60403, 60404, 60406, 60407, 60413, 60414, 60416, 60418,
  60429, 60432, 60433, 60434, 60436, 60437, 60438, 60439, 60440, 60441,
  60442, 60443, 60444, 60445, 60446, 60447, 60448, 60449, 60450, 60451,
  60452, 60453, 60454, 60455, 60456, 60457, 60458, 60459, 60460, 60461,
  60462, 60463, 60464, 60465, 60466, 60467, 60468, 60469, 60470, 60471,
  60472, 60473, 60474, 60475, 60476, 60477, 60478, 60479, 60480, 60481,
  60483, 60486, 60487, 60489, 60491, 60492, 60493, 60494, 60495, 60496,
  60497, 60498, 60499, 60500, 60501, 60502, 60534, 60535, 60536, 60537,
  60545, 60546, 60547, 60548, 60549, 60550, 60551, 60552, 60553, 60554,
  60560, 60561, 60562, 60563, 60564, 60565, 60566, 60567, 60571, 60572,
  60573, 60575, 60576, 60577, 60578, 60580, 60581, 60582, 60583, 60584,
  60585, 60586, 60587, 60589, 60590, 60593, 60595, 60596, 60597, 60599,
  60600, 60601, 60603, 60605, 60606, 60607, 60608, 60612, 60613, 60614,
  60615, 60616, 60617, 60618, 60619, 60620, 60621, 60622, 60623, 60624,
  60625, 60626, 60627, 60628, 60629, 60630, 60631, 60632, 60633, 60636,
  60637, 60638, 60639, 60640, 60641, 60642, 60643, 60644, 60645, 60646,
  60647, 60648, 60649, 60650, 60651, 60688, 60690, 60692, 60693, 60694,
  60696,
]

/** Compute holder counts (descending) and an objkt-marketplace flag. */
function summarize(owners) {
  const counts = new Map()
  for (const addr of Object.values(owners)) {
    counts.set(addr, (counts.get(addr) ?? 0) + 1)
  }
  const topHolders = [...counts.entries()].sort((a, b) => b[1] - a[1])
  return {
    distinctHolders: counts.size,
    onMarketplace: counts.get(OBJKT_MARKETPLACE) ?? 0,
    topHolders,
  }
}

/** Read the static snapshot (synchronous from the user's POV — no tzkt call). */
export async function loadSnapshot() {
  const res = await fetch(SNAPSHOT_URL, { cache: 'no-cache' })
  if (!res.ok) throw new Error(`txl-owners-snapshot.json: ${res.status}`)
  const data = await res.json()
  return {
    fetchedAt: data.fetched_at ?? null,
    owners: data.owners ?? {},
    ...summarize(data.owners ?? {}),
  }
}

/** One-shot live fetch from tzkt (mainnet). Returns the same shape as loadSnapshot. */
export async function fetchLive() {
  const ids = TXL_TOKEN_IDS.join(',')
  const path =
    `/v1/bigmaps/${TXL_OWNER_BIGMAP}/keys` +
    `?active=true&value.eq=1&select=key&limit=10000&key.nat.in=${ids}`
  const rows = await tzktGet(path, { network: 'mainnet' })
  if (!rows) return null
  const owners = {}
  for (const row of rows) {
    // row.key shape: { nat: '60199', address: 'tz1...' }
    owners[row.nat] = row.address
  }
  return {
    fetchedAt: new Date().toISOString(),
    owners,
    ...summarize(owners),
  }
}

/**
 * Snapshot first, live refresh second.
 *
 * Resolves to the freshest data available — live if the tzkt fetch lands,
 * otherwise the snapshot, otherwise null — so `loadOwners().then(...)` always
 * gets a usable result in one `.then()`.
 *
 * Pass `onUpdate` to paint progressively: it fires once with the snapshot the
 * instant it's read (no network wait), then again with the live data when the
 * background fetch lands. Each call receives the full
 * { owners, topHolders, distinctHolders, onMarketplace, fetchedAt } shape.
 */
export async function loadOwners({ refresh = true, onUpdate } = {}) {
  const notify = typeof onUpdate === 'function' ? onUpdate : null
  const snapshot = await loadSnapshot().catch(() => null)
  // Instant paint — hand the snapshot back before touching the network.
  if (snapshot && notify) notify(snapshot)
  if (!refresh) return snapshot
  const live = await fetchLive().catch(() => null)
  // Background refresh landed — push the fresher numbers to the caller.
  if (live && notify) notify(live)
  return live ?? snapshot
}
