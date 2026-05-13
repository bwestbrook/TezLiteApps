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
 */
export function getBeaconNetwork() {
  if (NETWORK === 'mainnet') return { type: 'mainnet' }
  return { type: 'custom', name: NETWORK, rpcUrl: NODE_URL }
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
export const AD_CONTRACT_ADDRESS_SHADOWNET         = 'KT1VpPzzwqyJEywjEv2TyfMNrQRPs3rGT1Zs'
export const TTT_CONTRACT_ADDRESS_SHADOWNET        = 'KT1XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX'
export const OBJECT_CONTRACT_SHADOWNET             = 'KT1XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX'
export const SQUARES_CONTRACT_ADDRESS_SHADOWNET    = 'KT1XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX'
export const RNG_ORACLE_CONTRACT_ADDRESS_SHADOWNET = 'KT1XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX'
export const REVERSI_CONTRACT_ADDRESS_SHADOWNET    = 'KT1XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX'
export const PLINKO_CONTRACT_ADDRESS_SHADOWNET     = 'KT1TqeFFmrV7VKChZwxT3VFL19JyyPbjLyJG'
export const CHESS_CONTRACT_ADDRESS_SHADOWNET      = 'KT1XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX'
export const WAR_CONTRACT_ADDRESS_SHADOWNET        = 'KT1XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX'

// ── Mainnet (last known Ghostnet leftovers; redeploy each before real use) ──
export const ORACLE_CONTRACT_MAINNET             = 'KT1VvcCnTPCUc7YaxyMT6opDrSPi2AUHnfvx'
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
export const ADMIN_ADDRESS = 'tz1Vq5mYKXw1dD9js26An8dXdASuzo3bfE2w'

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

export const AD_GAME_INFO = [
  'Choose Ace High or Ace Low and then Ante up for 0.3 XTZ (plus you pay a 0.1 XTZ 2.725K holder fee)',
  'Your bet goes into the pot',
  'If you get a pair to start, you get half your bet back and the game is over (holders get the other half of your bet)',
  "If the cards don't match, then you can bet up to the pot (plus a 0.1 XTZ fee) that the next card will between your low and high card",
  'Get good cards on your ante and then big on your Acey Duecey Hand!',
  'Submit your bet (along with another 0.1 XTZ 2.725K holder fee) and try your luck',
  'NOTE: If the next card hits the rail, your bet is removed from the pot and sent the the 2.725K fund!',
  "It's always a good time to be a 2.725K holder",
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
  'Pure-luck H2H — both players have exactly the same odds.',
  'Player A creates a game with a stake. Player B matches it to start.',
  'The oracle shuffles a deck. Five cards are dealt to each side, face up.',
  'Hand value = sum of ranks (A=14, K=13, Q=12, J=11, 2-10 face).',
  'Higher total takes the pot minus a 10% holder fee.',
  'Exact tie → one more card each (sudden death). Tie again → push (refund minus fee).',
  'No skill, no edge — just a fair 50/50 coin flip with prettier cards.',
]

export const PLINKO_GAME_INFO = [
  'Drop a ball over 8, 12, or 16 rows of pegs.',
  'Each peg, the ball goes left or right at 50/50.',
  'Risk dials the variance: Low keeps middle slots near 1×, High pushes the edges to 29× / 76× / 1000×.',
  'Bet 0.1–1.0 ꜩ. Plus a 0.1 ꜩ holder fee per drop.',
  'Payout settles inline — no claim step needed.',
]

// Plinko multiplier preview tables (must mirror plinko_seed_multipliers.py).
// Used by the UI to render the bucket strip; on-chain is still the source of
// truth at payout time.
export const PLINKO_MULTIPLIERS = {
  8: {
    0: [5.6, 2.1, 1.1, 1.0, 0.5, 1.0, 1.1, 2.1, 5.6],
    1: [13, 3, 1.3, 0.7, 0.4, 0.7, 1.3, 3, 13],
    2: [29, 4, 1.5, 0.3, 0.2, 0.3, 1.5, 4, 29],
  },
  12: {
    0: [10, 3, 1.6, 1.4, 1.1, 1.0, 0.5, 1.0, 1.1, 1.4, 1.6, 3, 10],
    1: [33, 11, 4, 2, 1.1, 0.6, 0.3, 0.6, 1.1, 2, 4, 11, 33],
    2: [76, 18, 5, 1.9, 0.4, 0.2, 0.2, 0.2, 0.4, 1.9, 5, 18, 76],
  },
  16: {
    0: [16, 9, 2, 1.4, 1.4, 1.2, 1.1, 1.0, 0.5, 1.0, 1.1, 1.2, 1.4, 1.4, 2, 9, 16],
    1: [110, 41, 10, 5, 3, 1.5, 1.0, 0.5, 0.3, 0.5, 1.0, 1.5, 3, 5, 10, 41, 110],
    2: [1000, 130, 26, 9, 4, 2, 0.2, 0.2, 0.2, 0.2, 0.2, 2, 4, 9, 26, 130, 1000],
  },
}

export const SQUARES_GAME_INFO = [
  '10×10 board. Rows = home team digit, columns = away team digit.',
  'Buy any open square at the ticket price.',
  'Once all 100 sell (or admin closes sales), the axis labels are randomized.',
  'After each quarter, the square at (homeScore mod 10, awayScore mod 10) wins that quarter\'s share of the pot.',
  'Default split: 15% / 15% / 15% / 55%. Holders absorb any unowned-square pots.',
  'Winnings are pull-pattern — click "Claim winnings" to withdraw.',
]

export const GAME_INFO = [
  'The goal of the game is to connect four in a row before you oponent does!',
  'Sync your wallet and check out the game center ',
  'Create a game or select a game to play, join, leave, or view',
  'To create a game specifying the amount of XTZ (+ 3% TXL holder fee) you want to wager that you can beat your opponent',
  'Leave an unmatched game to retrieve your XTZ at any time (but you forfeit your 3% fee)',
  "Once you've matchwith an opponent you have to play to win your money",
  "If it's your turn, select a move and submit it to the block chain",
  'Wait for your opponent to play',
  'Connect four in a row before you opponent and win the amount specificied at the start of the game!',
  'In the case of the cats game, both users get 75% of thier wager back and the rest goes to 2P725K holders',
  "It's always a good time to be a 2.725K holder",
]
