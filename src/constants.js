// ─── Server / Socket ─────────────────────────────────────────────────────────
export const PORT = 3000

// Where socket.io-client should connect. In production `server.js` serves
// BOTH the static SPA and the socket.io endpoint from the same origin, so
// we use window.location.origin and don't need to hardcode a Heroku URL.
//
// In local dev (vue-cli-service on :8080), point at the server.js port:
//   localhost:8080      → http://localhost:3000
//   192.168.1.5:8080    → http://192.168.1.5:3000   (phone on the same Wi-Fi)
function deriveSocketUrl() {
  if (typeof window === 'undefined') return ''   // SSR / build-time stub
  const { protocol, hostname, origin } = window.location
  const isDev = hostname === 'localhost' || /^\d+\.\d+\.\d+\.\d+$/.test(hostname)
  return isDev ? `${protocol}//${hostname}:${PORT}` : origin
}
export const SOCKET_URL = deriveSocketUrl()

// ─── App ─────────────────────────────────────────────────────────────────────
export const APP_NAME = 'TezTacToe'

// ─── Game layout ─────────────────────────────────────────────────────────────
export const GAME_WIDTH_FRACTION = 0.9
export const MAX_GAME_SIZE = 600
export const DEFAULT_GAME_SIZE = 500

// ─── Tezos network ───────────────────────────────────────────────────────────
// The active network is read from localStorage at startup and defaults to
// shadownet (so first-time visitors don't accidentally hit mainnet
// contracts). The mainBody network badge is a clickable toggle that calls
// setNetwork() below — it writes the preference and reloads the page.
//
// NOTE: Ghostnet was decommissioned in 2026 — Baking Bad shut down their
// TzKT Ghostnet API at the same time. Shadownet is the current Tezos testnet.
//   https://teztnets.com/shadownet-about

const NETWORK_STORAGE_KEY = 'tezliteapps:network'
const VALID_NETWORKS = ['shadownet', 'mainnet']
const DEFAULT_NETWORK = 'shadownet'

function detectActiveNetwork() {
  try {
    if (typeof window !== 'undefined' && window.localStorage) {
      const saved = window.localStorage.getItem(NETWORK_STORAGE_KEY)
      if (VALID_NETWORKS.includes(saved)) return saved
    }
  } catch (_e) {
    // localStorage unavailable (SSR, restricted browser, etc.) — fall through
  }
  return DEFAULT_NETWORK
}
export const NETWORK = detectActiveNetwork()

/**
 * Toggle the active network and reload. Wired to the network badge in
 * mainBody.vue. Persists the choice via localStorage so the next visit
 * starts on the same network.
 */
export function setNetwork(name) {
  if (typeof window === 'undefined') return
  if (!VALID_NETWORKS.includes(name)) return
  if (name === NETWORK) return
  try {
    window.localStorage.setItem(NETWORK_STORAGE_KEY, name)
  } catch (_e) {
    // ignore quota / private-mode errors
  }
  window.location.reload()
}

// Master kill switch for blockchain calls. Was `false` during UI dev so we
// didn't poll dead contracts; flipped to `true` now that oracle / TXL / AD
// are originated on shadownet and `tzkt.js` already short-circuits any
// remaining `KT1XXX…` placeholder addresses.
//
// What this controls:
//   - the per-second PollingSubscribeProvider in TezTacToe
//   - the tezTacToe contractEvent subscriptions
//   - the auto setInterval polls in aceyDuecey / squaresGame
// Read-only TzKT lookups (browseNFTs, contract storage reads) are NOT
// gated — they short-circuit individually based on isPlaceholderAddress.
export const BLOCKCHAIN_ENABLED = true

// Tezos RPC node + TzKT indexer. Both derived from NETWORK so they stay
// in sync with whatever the user toggled to.
//   mainnet:    https://mainnet.tezos.ecadinfra.com   /  https://api.tzkt.io
//   shadownet:  https://rpc.shadownet.teztnets.com    /  https://api.shadownet.tzkt.io
//               (faucet: https://faucet.shadownet.teztnets.com)
export const NODE_URL =
  NETWORK === 'mainnet'
    ? 'https://mainnet.tezos.ecadinfra.com/'
    : 'https://rpc.shadownet.teztnets.com/'

export const TZKT_API_URL =
  NETWORK === 'mainnet' ? 'https://api.tzkt.io' : `https://api.${NETWORK}.tzkt.io`

/**
 * Beacon-compatible network config for `new BeaconWallet({ network })` and
 * `client.requestPermissions({ network })`. Built from NETWORK + NODE_URL
 * so the wallet and the dApp always agree on the same chain.
 *
 * Plain string `type` (rather than `NetworkType.X` from beacon-types) so
 * this file doesn't pull in a runtime dependency on the Beacon enum.
 *
 * IMPORTANT: use `'shadownet'`, NOT `'custom'`. `shadownet` is a
 * first-class NetworkType in beacon-sdk ≥4.x, so hosted wallets like
 * Kukai recognize it. Passing `'custom'` makes Kukai throw
 * NetworkNotSupportedBeaconError and silently fall back to mainnet —
 * Kukai's web wallet won't accept an arbitrary custom RPC. We still
 * pass `rpcUrl` so Taquito/extension wallets hit the right node.
 */
export function getBeaconNetwork() {
  if (NETWORK === 'mainnet') return { type: 'mainnet' }
  // NETWORK is one of VALID_NETWORKS; the non-mainnet case is shadownet.
  return { type: NETWORK, name: NETWORK, rpcUrl: NODE_URL }
}

/**
 * Alternative Beacon relay (Matrix) nodes. Beacon SDK ships a default
 * list that points at servers under `*.papers.tech`. We've seen
 * `beacon-node-1.beacon-server-2.papers.tech` fail DNS resolution; if
 * that's the first relay Beacon tries on a given page load, the user
 * waits ~45 seconds for the SDK's internal retries before anything
 * useful happens.
 *
 * Providing this list to BeaconWallet's constructor sidesteps the dead
 * relay by giving the SDK working alternatives to round-robin through.
 */
export const BEACON_MATRIX_NODES = [
  'beacon-node-1.diamond.papers.tech',
  'beacon-node-1.sky.papers.tech',
  'beacon-node-1.hope.papers.tech',
  'beacon-node-2.sky.papers.tech',
]

/**
 * Hostnames Beacon has been seen failing on. App.vue scrubs any localStorage
 * entries containing these so the SDK can't reuse a stale cached choice.
 */
const BEACON_KNOWN_BAD_HOSTS = [
  'beacon-server-1.papers.tech',
  'beacon-server-2.papers.tech',
  'beacon-server-3.papers.tech',
  'beacon-server-4.papers.tech',
  // Single-char malformed cache entries from a prior mis-shaped
  // matrixNodes config — these get baked into beacon:matrix-* keys and
  // hang the SDK on every reload. Sweep them too.
  '"https://a/"',
  '"https://b/"',
  '"https://c/"',
  '"https://h/"',
]

/**
 * Beacon SDK caches the selected Matrix relay in localStorage under
 * `beacon:matrix-selected-node` (and a couple sibling keys). When the cached
 * choice is a dead server, the SDK ignores any matrixNodes override we pass
 * to BeaconWallet and re-tries the dead host on every connect.
 *
 * Sweep any beacon:* keys that reference a known-bad host. Idempotent —
 * safe to call on every page load.
 */
export function clearStaleBeaconStorage() {
  if (typeof window === 'undefined' || !window.localStorage) return
  let removed = 0
  try {
    const ls = window.localStorage
    const keysToCheck = []
    for (let i = 0; i < ls.length; i++) {
      const k = ls.key(i)
      if (k && k.startsWith('beacon:')) keysToCheck.push(k)
    }
    for (const key of keysToCheck) {
      const raw = ls.getItem(key) || ''
      // matches the raw hostname or the URL-encoded form
      if (BEACON_KNOWN_BAD_HOSTS.some((host) => raw.includes(host))) {
        ls.removeItem(key)
        removed++
      }
    }
    if (removed > 0) {
      console.warn(`[constants] cleared ${removed} stale Beacon storage entries`)
    }
  } catch (_e) {
    // localStorage unavailable — nothing to do
  }
}

// ─── Smart contracts ─────────────────────────────────────────────────────────
//
// One canonical address per (contract, network) pair. The deploy script
// (scripts/deploy.py) patches the *_SHADOWNET or *_MAINNET line depending
// on its --network flag, so this file stays in sync with what's live.
//
// Down below, NETWORK-dispatched aliases (ORACLE_CONTRACT, AD_CONTRACT_ADDRESS,
// etc.) resolve to the address for whichever network the user is currently
// on. All components import only those backward-compatible aliases.

// ── Shadownet (current testnet, primary dev target) ──
export const ORACLE_CONTRACT_SHADOWNET             = 'KT19V1YiyPtyCbxouhyeM96SekRTVC7Gw6qq'
export const TXL_CONTRACT_ADDRESS_SHADOWNET        = 'KT1Ro63rVDUx2x8pMChCLSySso8t6JH47oRQ'
export const AD_CONTRACT_ADDRESS_SHADOWNET         = 'KT1N4dEistsQcxMTLW7A6AdBc7Sh9GkohHnJ'
export const TTT_CONTRACT_ADDRESS_SHADOWNET        = 'KT1GkvjJhHtEZfsiSJnQWCS3zZVdgfnBdqWc'
export const OBJECT_CONTRACT_SHADOWNET             = 'KT1XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX'
export const SQUARES_CONTRACT_ADDRESS_SHADOWNET    = 'KT1WZXaVyhscbwamSEXh9ay7dHrb1bdrRviM'
export const RNG_ORACLE_CONTRACT_ADDRESS_SHADOWNET = 'KT1XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX'
export const REVERSI_CONTRACT_ADDRESS_SHADOWNET    = 'KT1XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX'
export const PLINKO_CONTRACT_ADDRESS_SHADOWNET     = 'KT18z3DNXbp1cZpXJe2SkaPnCTdDJAbb7Pph'
export const CHESS_CONTRACT_ADDRESS_SHADOWNET      = 'KT1XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX'
export const WAR_CONTRACT_ADDRESS_SHADOWNET        = 'KT1Cbb7aTgWjhSCK4bXTEWp4aGoqQ2FNrZ4W'

// ── Mainnet (last known Ghostnet leftovers; redeploy each before real use) ──
export const ORACLE_CONTRACT_MAINNET             = 'KT1H3RJBs3SjoLyFRG3Q6LXMGtm4n5wJGa4N'
export const TXL_CONTRACT_ADDRESS_MAINNET        = 'KT1HD71gj4ZdehpS4Ri8nasjpDTPDQ574Sxy'
export const AD_CONTRACT_ADDRESS_MAINNET         = 'KT1LQTALXvukm56XA1p1BcRrGi36tMyWnXp5'
export const TTT_CONTRACT_ADDRESS_MAINNET        = 'KT1FsKda1m7CR2YwXRM9Awzctq1Js7TjmTmM'
export const OBJECT_CONTRACT_MAINNET             = 'KT1FvqJwEDWb1Gwc55Jd1jjTHRVWbYKUUpyq'
export const SQUARES_CONTRACT_ADDRESS_MAINNET    = 'KT1XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX'
export const RNG_ORACLE_CONTRACT_ADDRESS_MAINNET = 'KT1XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX'
export const REVERSI_CONTRACT_ADDRESS_MAINNET    = 'KT1XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX'
export const PLINKO_CONTRACT_ADDRESS_MAINNET     = 'KT1XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX'
export const CHESS_CONTRACT_ADDRESS_MAINNET      = 'KT1XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX'
export const WAR_CONTRACT_ADDRESS_MAINNET        = 'KT1XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX'

// Active-network aliases. These are what every component imports.
const IS_MAINNET = NETWORK === 'mainnet'
export const ORACLE_CONTRACT             = IS_MAINNET ? ORACLE_CONTRACT_MAINNET             : ORACLE_CONTRACT_SHADOWNET
export const TXL_CONTRACT_ADDRESS        = IS_MAINNET ? TXL_CONTRACT_ADDRESS_MAINNET        : TXL_CONTRACT_ADDRESS_SHADOWNET
export const AD_CONTRACT_ADDRESS         = IS_MAINNET ? AD_CONTRACT_ADDRESS_MAINNET         : AD_CONTRACT_ADDRESS_SHADOWNET
export const TTT_CONTRACT_ADDRESS        = IS_MAINNET ? TTT_CONTRACT_ADDRESS_MAINNET        : TTT_CONTRACT_ADDRESS_SHADOWNET
export const OBJECT_CONTRACT             = IS_MAINNET ? OBJECT_CONTRACT_MAINNET             : OBJECT_CONTRACT_SHADOWNET
export const SQUARES_CONTRACT_ADDRESS    = IS_MAINNET ? SQUARES_CONTRACT_ADDRESS_MAINNET    : SQUARES_CONTRACT_ADDRESS_SHADOWNET
export const RNG_ORACLE_CONTRACT_ADDRESS = IS_MAINNET ? RNG_ORACLE_CONTRACT_ADDRESS_MAINNET : RNG_ORACLE_CONTRACT_ADDRESS_SHADOWNET
export const REVERSI_CONTRACT_ADDRESS    = IS_MAINNET ? REVERSI_CONTRACT_ADDRESS_MAINNET    : REVERSI_CONTRACT_ADDRESS_SHADOWNET
export const PLINKO_CONTRACT_ADDRESS     = IS_MAINNET ? PLINKO_CONTRACT_ADDRESS_MAINNET     : PLINKO_CONTRACT_ADDRESS_SHADOWNET
export const CHESS_CONTRACT_ADDRESS      = IS_MAINNET ? CHESS_CONTRACT_ADDRESS_MAINNET      : CHESS_CONTRACT_ADDRESS_SHADOWNET
export const WAR_CONTRACT_ADDRESS        = IS_MAINNET ? WAR_CONTRACT_ADDRESS_MAINNET        : WAR_CONTRACT_ADDRESS_SHADOWNET

// ─── Addresses ───────────────────────────────────────────────────────────────
// The wallet that controls admin entrypoints on every deployed game
// contract (oracle, AD, TTT, war, plinko, squares, …). This is the
// address DEPLOY_MNEMONIC derives to — same key the off-chain oracle
// worker runs with. Must match the `admin` baked into each contract's
// initial storage; if it drifts, the UI's isAdmin checks silently fail
// and the deployer can't admin from the web UI.
//
// Distinct from jamin_b's TXL-holder wallet (tz1Vq5mYKXw1dD9js26An8dXdASuzo3bfE2w).
export const ADMIN_ADDRESS = 'tz1ZU2RLW7UgY8XXz49ccKihNy86zs6TdQ8Q'

// ─── Game / NFT info copy ────────────────────────────────────────────────────
export const NFT_INFO = [
  'More Information Coming Soon!',
  'All games on thextz.life plan to generate revenue in the form of XTZ',
  'This revenue will be shared evenly among the holders with an inverse weight against NFT rank',
  "There's only 275 of them and already over 100 unique owners",
  'They are only 2.725 XTZ on primary!',
  'The only way to cash out from the contract is by hodling the NFTs',
  'A separate smart contract takes snaps shots of the NFTs owners and monitors for sales',
  'Each NFT has its own balance that gets set back to zero when claimed by the owner',
]

// XC-2 — `default()` semantics: the AceyDuecey contract's default
// entrypoint accepts anonymous tez and credits it to `potReserve`
// (`self.data.potReserve += sp.amount`). Sending plain tez to the KT1
// is a pot top-up, not a no-op.
export const AD_GAME_INFO = [
  'Ante up 0.4 ꜩ to play (0.2 ꜩ ante + 0.1 ꜩ 2.725K holder fee + 0.1 ꜩ v3 oracle fee). Aces are always high.',
  'Two cards are dealt. If they pair, the ante is forfeit to the pot — no refund.',
  'Otherwise, place an Acey-Duecey bet (up to 30% of the pot) that the next card lands strictly between them.',
  'Payouts are TRUE ODDS with a 5% house rake — tight spreads pay big, wide spreads pay slim:',
  '  spread 1  →  12.35× · spread 5  →  2.47× · spread 11  →  1.12×',
  'Edge (third card matches an anchor) or out-of-range third card forfeits the bet.',
  'Win, lose, or pair — every bet keeps the pot growing.',
]

export const CHESS_GAME_INFO = [
  'Standard chess. White moves first.',
  'Click a piece to select; click a destination to move.',
  'On-chain rules: piece movement, path-clear for sliders, castling, en passant, no-leaving-king-in-check.',
  'Pawn auto-promotes to a queen.',
  'No automatic checkmate detection — resign when you\'re mated, or claim by timeout if your opponent stalls.',
  'Stake matches between both players. Winner takes the pot minus the holder fee.',
]

export const REVERSI_GAME_INFO = [
  '8x8 board — black moves first.',
  'A move is legal only if it flanks at least one opponent stone in any of the 8 directions.',
  'Flanked stones flip to your color.',
  'When neither player can move (or both pass), the player with more stones takes the pot.',
  'Stake matches between both players. Winner gets the full pot minus the holder fee.',
]

export const WAR_GAME_INFO = [
  'Speed War: best-of-3 high-card showdown. Whole match settles in one oracle call.',
  'Player A creates a game with a wager (0.1 – 5 ꜩ). Player B matches it to start.',
  'The oracle deals 6 distinct cards — three per side — in one transaction.',
  'Each round: higher rank wins that round. Whoever wins more rounds takes the pot.',
  'Rank order: A=14, K=13, Q=12, J=11, 2–10 face value. Suits are decorative.',
  'Series tied (e.g. 1–1 with a wash) → both players refunded their wager.',
  'Settles inline — no claim step. Flat 0.1 ꜩ holder fee per side; creator can cancel an open game.',
]

// XC-2 — `default()` semantics: the Plinko contract's default
// entrypoint accepts anonymous tez and credits it to `potReserve`
// ("Anyone can top up the reserve"). Same as AD — plain tez sent to
// the KT1 is a reserve top-up.
export const PLINKO_GAME_INFO = [
  'Drop a ball through a 3D peg pyramid — 8, 12, or 16 layers deep.',
  'Each layer the ball deflects on TWO axes at once: ±X and ±Z, 50/50 on each.',
  'It lands on a grid of bins. Payout is RADIAL — the ring distance from dead centre is all that matters: centre pays sub-1×, the outer corners pay huge.',
  'Risk dials the variance: Low keeps the inner rings near 1×, High pushes the corner ring to ~17× (8 rows) up to ~575× (16 rows).',
  'Bet 0.1–10.0 ꜩ plus a flat 0.1 ꜩ holder fee per drop. Payout settles inline — no claim step.',
]

// 3D Plinko multipliers — RING-indexed (radially symmetric), not per-slot.
// Index = Chebyshev ring distance from centre: 0 = dead-centre bin (worst
// payout), rows/2 = outer corner ring (best). The ball lands on a
// (rows+1)×(rows+1) grid; ring = max(|finalX-rows/2|, |finalZ-rows/2|).
// Values scaled so each (rows,risk) profile pays ~97% RTP against the
// TRUE 3D ring-probability distribution (two independent Binomials).
// Must mirror scripts/plinko_seed_multipliers.py (the on-chain source
// of truth at payout time).
export const PLINKO_MULTIPLIERS = {
  8: {
    0: [0.4, 0.81, 0.89, 1.69, 4.52],
    1: [0.29, 0.5, 0.93, 2.14, 9.27],
    2: [0.12, 0.18, 0.9, 2.4, 17.43],
  },
  12: {
    0: [0.42, 0.84, 0.92, 1.17, 1.34, 2.51, 8.38],
    1: [0.21, 0.42, 0.76, 1.38, 2.77, 7.61, 22.83],
    2: [0.16, 0.16, 0.33, 1.55, 4.09, 14.71, 62.12],
  },
  16: {
    0: [0.43, 0.86, 0.94, 1.03, 1.2, 1.2, 1.72, 7.72, 13.72],
    1: [0.21, 0.34, 0.69, 1.03, 2.06, 3.43, 6.85, 28.1, 75.39],
    2: [0.12, 0.12, 0.12, 1.15, 2.3, 5.18, 14.96, 74.81, 575.44],
  },
}

// XC-2 — `default()` semantics: the TezTacToe contract's default
// entrypoint has an empty body (`pass`), so anonymous tez sent to the
// KT1 is accepted into the contract balance but credited to nothing —
// effectively discarded / unrecoverable. Unlike AD and Plinko, this is
// NOT a pot top-up. Don't send plain tez to the TTT contract.
export const GAME_INFO = [
  'TezTacToe is 3D four-in-a-row — line up four of your marks on the board before your opponent does.',
  'Sync your wallet to play. The board is up top; the wager controls and your Game Hub sit just below it.',
  'Drag the wager slider to set your stake, then hit New Game. Both players lock the same wager, plus a flat 0.1 ꜩ holder fee per transaction.',
  'Use the Game Hub to play, join, leave, or view games. Leaving an unmatched game refunds your wager any time — the per-tx fee is non-refundable, it has already paid out to TXL holders.',
  "Once you're matched it's turn-based: when it's your turn, select a move and submit it to the blockchain, then wait for your opponent.",
  'WIN: connect four and the contract pays you the full pot minus the house cut (default 2.5%).',
  "CAT'S GAME: each side gets back their wager minus half the house cut.",
  'SURRENDER: you forfeit your stake — your opponent takes the full pot minus the house cut.',
  'The house cut and per-tx fee both flow to TXL holders — every game funds the holder pool.',
  "It's always a good time to be a 2.725K holder.",
]
