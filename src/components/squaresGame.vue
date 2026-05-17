<script>
// Super-Bowl-Squares UI.
// Reads grid state from contract storage via tzkt; writes via wallet.
//
// Single-view component: a game-selector bar (one button per pool on
// chain) + the 10×10 grid + buy/create controls. App-level nav lives in
// the top carousel. The selector follows the newest game until the user
// picks one explicitly (gameSelected flag); createGame resets that so
// the bar jumps to the freshly-created pool.
//
// Phases (must match smart_contract_squares_v2.py):
//   0 = SELLING
//   1 = LOCKED
//   2 = AXES_SET
//   3 = COMPLETE

import { getContractStorage, tzktGet } from '../services/tzkt'
import { reduceAddress } from '@/utilities'
import {
  ADMIN_ADDRESS,
  BLOCKCHAIN_ENABLED,
  SQUARES_CONTRACT_ADDRESS,
} from '../constants'

const PHASE_LABELS = {
  0: 'Sales open',
  1: 'Sales closed — awaiting axis randomization',
  2: 'In play',
  3: 'Game complete',
}

// Test fixtures — real, completed playoff games (verified ESPN event ids).
// fetchEspnGames() falls back to these when the live slate for the
// chosen date is empty, so the picker always has something to select
// during testing. All are Finals with complete quarter linescores, so
// the oracle's reportQuarter path can be exercised end-to-end. The two
// Cavs games plus a non-Cavs matchup give the picker some contrast.
const TEST_NBA_GAMES = [
  {
    league: 'NBA',
    id: '401871337',
    date: '2025-05-04T19:00:00Z',
    awayAbbr: 'CLE', homeAbbr: 'DET',
    awayName: 'Cleveland Cavaliers', homeName: 'Detroit Pistons',
    awayLogo: 'https://a.espncdn.com/i/teamlogos/nba/500/cle.png',
    homeLogo: 'https://a.espncdn.com/i/teamlogos/nba/500/det.png',
    awayScore: '124', homeScore: '122',
    awayPeriods: [30, 28, 32, 24, 10], homePeriods: [28, 30, 31, 25, 8],
    statusDetail: 'Final/OT',
  },
  {
    league: 'NBA',
    id: '401871336',
    date: '2025-05-01T23:00:00Z',
    awayAbbr: 'DET', homeAbbr: 'CLE',
    awayName: 'Detroit Pistons', homeName: 'Cleveland Cavaliers',
    awayLogo: 'https://a.espncdn.com/i/teamlogos/nba/500/det.png',
    homeLogo: 'https://a.espncdn.com/i/teamlogos/nba/500/cle.png',
    awayScore: '105', homeScore: '112',
    awayPeriods: [25, 28, 30, 22], homePeriods: [30, 28, 32, 22],
    statusDetail: 'Final',
  },
  // More real 2025 playoff games — a fuller lobby to pick from while
  // testing, and contrast for the "Cavs Vs." labeling.
  {
    league: 'NBA',
    id: '401768057',
    date: '2025-04-28T03:30:00Z',
    awayAbbr: 'LAL', homeAbbr: 'MIN',
    awayName: 'Los Angeles Lakers', homeName: 'Minnesota Timberwolves',
    awayLogo: 'https://a.espncdn.com/i/teamlogos/nba/500/lal.png',
    homeLogo: 'https://a.espncdn.com/i/teamlogos/nba/500/min.png',
    awayScore: '95', homeScore: '117',
    awayPeriods: [22, 25, 24, 24], homePeriods: [30, 28, 30, 29],
    statusDetail: 'Final',
  },
  {
    league: 'NBA',
    id: '401768043',
    date: '2025-04-27T22:00:00Z',
    awayAbbr: 'NY', homeAbbr: 'DET',
    awayName: 'New York Knicks', homeName: 'Detroit Pistons',
    awayLogo: 'https://a.espncdn.com/i/teamlogos/nba/500/ny.png',
    homeLogo: 'https://a.espncdn.com/i/teamlogos/nba/500/det.png',
    awayScore: '121', homeScore: '118',
    awayPeriods: [30, 28, 33, 30], homePeriods: [28, 30, 30, 30],
    statusDetail: 'Final',
  },
  {
    league: 'NBA',
    id: '401768031',
    date: '2025-04-27T17:00:00Z',
    awayAbbr: 'BOS', homeAbbr: 'ORL',
    awayName: 'Boston Celtics', homeName: 'Orlando Magic',
    awayLogo: 'https://a.espncdn.com/i/teamlogos/nba/500/bos.png',
    homeLogo: 'https://a.espncdn.com/i/teamlogos/nba/500/orl.png',
    awayScore: '89', homeScore: '103',
    awayPeriods: [22, 25, 24, 18], homePeriods: [25, 28, 27, 23],
    statusDetail: 'Final',
  },
  {
    league: 'NBA',
    id: '401768049',
    date: '2025-04-27T19:30:00Z',
    awayAbbr: 'IND', homeAbbr: 'MIL',
    awayName: 'Indiana Pacers', homeName: 'Milwaukee Bucks',
    awayLogo: 'https://a.espncdn.com/i/teamlogos/nba/500/ind.png',
    homeLogo: 'https://a.espncdn.com/i/teamlogos/nba/500/mil.png',
    awayScore: '117', homeScore: '95',
    awayPeriods: [30, 28, 32, 27], homePeriods: [22, 24, 25, 24],
    statusDetail: 'Final',
  },
]

// Leagues the picker pulls from. Each entry is a path under ESPN's site
// API (`/apis/site/v2/sports/<path>/scoreboard?dates=YYYYMMDD`). The
// merged lobby tags each card with the league id for display + later
// oracle routing.
// Squares only does well in leagues that put up 5+ points per period —
// otherwise the mod-10 digit lottery is near-deterministic. NHL, soccer
// (EPL/MLS), and MLB are dropped for now; can be restored once we model
// low-scoring periods sensibly. See periodSpecForLeague below.
const LEAGUES = [
  { id: 'NBA',  path: 'basketball/nba' },
  { id: 'WNBA', path: 'basketball/wnba' },
]

// Forward window for the picker fetch — today + the next (DAYS_AHEAD - 1)
// calendar days. ESPN accepts a `dates=YYYYMMDD-YYYYMMDD` range, so we
// get the whole window in one request per league regardless of size.
const DAYS_AHEAD = 3

// Two cells on the 10×10 board are reserved for the house:
//   - idx 44  (row 4, col 4 — "middle", top-left of the central 2×2)
//   - idx 90  (row 9, col 0 — bottom-left corner)
// The frontend never offers these as random buys, and the contract's
// reportQuarter already routes "unowned winning square" payouts to
// txlContract — so when either cell wins, the share pays TXL holders
// without any contract change. Consequence: max sellable = 98, so the
// contract's auto-lock-at-100 trigger never fires — admin uses
// "Lock sales".
const HOUSE_SQUARES = new Set([44, 90])

// Per-click cap on the random-buy batch — half the buyable pool with
// the two house cells reserved (98 / 2).
const MAX_BUY_PER_CLICK = 49

// UI-side per-player cap for one game. The contract doesn't enforce
// this — it's a fairness guard so one wallet can't sweep an entire
// 99-square board. Tracked by counting cells owned by myAddress.
const MAX_BUY_PER_PLAYER_PER_GAME = 50

export default {
  name: 'squaresGame',
  props: ['socket', 'wallet', 'tezos'],
  data() {
    return {
      currentGameId: 0,
      activeGameId: 0,
      // Every game record from contract storage, keyed by id. Powers the
      // game-selector bar and lets selectGameId switch without a refetch.
      allGames: {},
      // false → the selector follows the newest game on every poll.
      // true  → the user has explicitly picked one; stop auto-following.
      gameSelected: false,
      game: null,
      walletAddress: '',
      pollInterval: null,
      // Rolling ESPN slate refresh. ESPN re-publishes start times,
      // status, and the day's new games as the calendar advances —
      // we re-poll every 5 min so the "next 3 days" lobby naturally
      // drops finished games and picks up new postings.
      espnRefreshInterval: null,
      blockchainStatus: 'idle',
      buyCount: 1,
      myAddress: '',
      // Pool id of the most recently created card. Drives the "✓ Card
      // created" confirmation tile that sits below the create button.
      // The tile renders whenever this pool is the one being viewed,
      // so revisiting via the lobby brings the tile back.
      lastCreatedPoolId: null,
      // Lobby pagination — `lobbyPage` is the index of the leftmost
      // tile shown. visibleLobby slices the next two; the arrows shift
      // this by ±1 so each click advances exactly one game.
      lobbyPage: 0,
      // Create-game form. Anyone can start a new pool; admin still
      // owns scoring (reportQuarter) and randomization (setAxes).
      newGameName: '',
      // Default ticket price. Picked 0.1 ꜩ for mainnet-friendliness —
      // a 98-cell sellout is ~9.8 ꜩ pot, ~5 ꜩ max single-player
      // exposure at the contract's PER_PLAYER_PER_GAME=50 cap. Creators
      // can crank it via the input field for higher-stakes pools.
      // Keep the createCard / createGame `|| 0.1` fallbacks below in
      // sync — they protect against the user clearing the field.
      newGameTicketTez: 0.1,
      showCreateForm: false,
      // ─── NBA game picker for createGame ─────────────────────────
      // Lets the creator bind a pool to a real ESPN event. The chosen
      // id is encoded into the on-chain game name as "ESPN:<id>"; the
      // oracle (scripts/oracle_worker.py) parses that tag to auto-report
      // quarter scores. Convention lives in scripts/sports_api.py.
      espnGames: [],
      espnLoading: false,
      selectedEspnId: null,
    }
  },
  computed: {
    phaseLabel() {
      if (!this.game) return 'No game loaded'
      return PHASE_LABELS[this.game.phase] || `phase ${this.game.phase}`
    },
    canBuy() {
      return this.game && Number(this.game.phase) === 0
    },
    sold() {
      return this.game ? Number(this.game.sold) : 0
    },
    ticketPriceTez() {
      if (!this.game) return '—'
      return (Number(this.game.ticketPrice) / 1_000_000).toFixed(3)
    },
    feePriceTez() {
      if (!this.game) return '—'
      return (Number(this.game.holderFee) / 1_000_000).toFixed(3)
    },
    potTez() {
      // Pot ≈ ticketPrice * sold (the fee goes to holders, not the pot).
      if (!this.game) return '—'
      const lamports = Number(this.game.ticketPrice) * this.sold
      return (lamports / 1_000_000).toFixed(3)
    },
    isAdmin() {
      // ADMIN_ADDRESS is the canonical admin in constants.js. The wallet
      // string in walletAddress is from the App-level socket broadcast and
      // looks like "UNSYNC WALLET tz1...abc" or "SYNC WALLET" — not directly
      // comparable. We track the user's actual address separately in
      // myAddress (set by refreshState() once a wallet is connected).
      return this.myAddress && this.myAddress === ADMIN_ADDRESS
    },
    grid() {
      // Build a 10x10 array of { idx, owner, axisHome, axisAway }.
      const out = []
      for (let r = 0; r < 10; r++) {
        const row = []
        for (let c = 0; c < 10; c++) {
          const idx = r * 10 + c
          row.push({
            idx,
            owner: this.game?.squares?.[idx] || null,
            axisHomeDigit: this.game?.axisHome?.[r] ?? null,
            axisAwayDigit: this.game?.axisAway?.[c] ?? null,
          })
        }
        out.push(row)
      }
      return out
    },
    openSquareIdxs() {
      // Indices (0..99) that no one has bought yet. House cells
      // (HOUSE_SQUARES) are reserved for TXL holders and never buyable.
      const owned = this.game?.squares || {}
      const open = []
      for (let i = 0; i < 100; i++) {
        if (HOUSE_SQUARES.has(i)) continue
        if (!owned[i]) open.push(i)
      }
      return open
    },
    // Expose the module-level constants so the template can reference
    // them without hardcoding 50 in copy.
    MAX_BUY_PER_CLICK() { return MAX_BUY_PER_CLICK },
    MAX_BUY_PER_PLAYER_PER_GAME() { return MAX_BUY_PER_PLAYER_PER_GAME },
    myOwnedSquaresInGame() {
      // How many cells the current wallet already owns in this game.
      // Drives the per-player-per-game cap (MAX_BUY_PER_PLAYER_PER_GAME).
      if (!this.myAddress || !this.game?.squares) return 0
      let n = 0
      for (const owner of Object.values(this.game.squares)) {
        if (owner === this.myAddress) n++
      }
      return n
    },
    myRemainingAllowance() {
      // How many more squares this wallet is allowed to buy in this game.
      return Math.max(0, MAX_BUY_PER_PLAYER_PER_GAME - this.myOwnedSquaresInGame)
    },
    atPerGameLimit() {
      return !!this.myAddress && this.myRemainingAllowance === 0
    },
    maxBuy() {
      // Three caps stacked: per-tx batch size, remaining open squares,
      // and what's left of this wallet's per-game allowance.
      return Math.max(
        0,
        Math.min(
          MAX_BUY_PER_CLICK,
          this.openSquareIdxs.length,
          this.myRemainingAllowance,
        ),
      )
    },
    // Exposed for the picker's "Showing the next N days" hint.
    DAYS_AHEAD() {
      return DAYS_AHEAD
    },
    // Matchup label for the just-created pool, used by the confirmation
    // tile below the create button. Reuses the lobby's title resolution
    // (ESPN label when the slate has the matching event, otherwise the
    // pool name).
    lastCreatedGameLabel() {
      if (this.lastCreatedPoolId === null) return ''
      const pool = this.allGames?.[this.lastCreatedPoolId]
      if (!pool) return ''
      const m = /\bESPN:(\d{6,})\b/.exec(pool.name || '')
      if (m) {
        const ev = this.espnGames.find((x) => x.id === m[1])
        if (ev) return this.espnGameLabel(ev)
      }
      return this.gameButtonLabel(this.lastCreatedPoolId)
    },
    // Per-square price (ꜩ) of the just-created pool. Reads ticketPrice
    // off the pool record returned from the games big_map.
    lastCreatedPrice() {
      if (this.lastCreatedPoolId === null) return ''
      const pool = this.allGames?.[this.lastCreatedPoolId]
      if (!pool) return ''
      return (Number(pool.ticketPrice || 0) / 1_000_000).toFixed(3)
    },
    // Matchup label for whatever game the create-card form should reference.
    // Prefer the lobby selection (selectedEspnId, set by pickEspnGame on
    // each "+ NEW" tile click) so picking a fresh tile updates the form
    // even while a different pool is still open below. Fall back to the
    // currently selected pool's game when nothing is staged.
    selectedGameLabel() {
      if (this.selectedEspnId) {
        const g = this.espnGames.find((x) => x.id === this.selectedEspnId)
        if (g) return this.espnGameLabel(g)
      }
      if (this.game) return this.gridDisplayName
      return ''
    },
    clampedBuyCount() {
      const n = Math.floor(Number(this.buyCount) || 0)
      return Math.max(1, Math.min(this.maxBuy || 1, n))
    },
    buyTotalTez() {
      if (!this.game) return '—'
      const per = Number(this.game.ticketPrice) + Number(this.game.holderFee)
      return ((per * this.clampedBuyCount) / 1_000_000).toFixed(3)
    },
    // Human label for the grid name with the ESPN tag stripped. Falls
    // back to the raw name when there's no tag.
    gridDisplayName() {
      const name = this.game?.name || ''
      return name.replace(/\bESPN:\d{6,}\b/, '').replace(/^\s*[·•|\-—]\s*/, '').trim() || name
    },
    // A pool must be bound to a real NBA game before it can be created —
    // the squares contract is only meaningful when an ESPN event drives
    // the quarter scores. Gates the "Start game" button.
    canCreateGame() {
      return !!this.selectedEspnId
    },
    // Game ids for the selector bar, newest first. Game ids are a dense
    // 0..currentGameId-1 range (contract increments currentGameId on
    // every createGame), so we don't need to read the map keys.
    gameIds() {
      const ids = []
      for (let i = this.currentGameId - 1; i >= 0; i--) ids.push(i)
      return ids
    },
    // The top selector bar is now the full lobby: every on-chain pool
    // (so the user can jump to one) PLUS every ESPN game that doesn't
    // have a pool yet (so the user can start one in one click). Sorted
    // by tip-off so the bar reads chronologically.
    lobby() {
      const items = []
      // Walk every pool. Parse its name for an ESPN tag, then pair it
      // with the matching slate entry for date / status / league.
      const matchedEspnIds = new Set()
      for (let i = 0; i < this.currentGameId; i++) {
        const name = this.allGames?.[i]?.name || ''
        const m = /\bESPN:(\d{6,})\b/.exec(name)
        const espnId = m ? m[1] : null
        if (espnId) matchedEspnIds.add(espnId)
        const ev = espnId ? this.espnGames.find((x) => x.id === espnId) : null
        items.push({
          kind: 'pool',
          key: `pool-${i}`,
          poolId: i,
          league: ev?.league || '',
          // Prefer the slate's clean matchup label when we have it —
          // covers pools whose on-chain name has junk abbrs or just an
          // "ESPN:<id>" tag. Falls back to the pool-name parsing.
          title: ev ? this.espnGameLabel(ev) : this.gameButtonLabel(i),
          date: ev?.date || '',
          statusDetail: ev?.statusDetail || '',
        })
      }
      // Add every slate entry that doesn't already have a pool — these
      // are the "start a pool for this game" tiles.
      for (const g of this.espnGames) {
        if (matchedEspnIds.has(g.id)) continue
        items.push({
          kind: 'espn',
          key: `espn-${g.id}`,
          espnId: g.id,
          league: g.league || '',
          title: this.espnGameLabel(g),
          date: g.date || '',
          statusDetail: g.statusDetail || '',
        })
      }
      // Sort by tip-off; entries with no date sink to the bottom.
      items.sort((a, b) => {
        if (!a.date && !b.date) return 0
        if (!a.date) return 1
        if (!b.date) return -1
        return String(a.date).localeCompare(String(b.date))
      })
      return items
    },
    // Two-tile sliding window into the full lobby. Clamped so it stays
    // valid as the lobby grows or shrinks; pageLobby() updates lobbyPage.
    visibleLobby() {
      const maxStart = Math.max(0, this.lobby.length - 2)
      const start = Math.max(0, Math.min(this.lobbyPage, maxStart))
      return this.lobby.slice(start, start + 2)
    },
    lobbyCanPageLeft() {
      return this.lobbyPage > 0
    },
    lobbyCanPageRight() {
      return this.lobbyPage + 2 < this.lobby.length
    },
  },
  created() {
    this.socket.on('newWallet', (w) => {
      this.walletAddress = w
    })
    this.refreshState()
    if (BLOCKCHAIN_ENABLED) {
      this.pollInterval = setInterval(() => this.refreshState(), 8000)
    }
    // Prime the picker slate up-front, then auto-select the earliest
    // game on the calendar so the create form opens ready-to-go with
    // a default selection (the form is never hidden — user just
    // changes which game it targets via the lobby).
    this.fetchEspnGames().then(() => {
      if (!this.selectedEspnId && this.espnGames.length) {
        this.pickEspnGame(this.espnGames[0])
        this.showCreateForm = true
      }
    })
    // Rolling refresh: ESPN updates the slate as games end and new
    // postings open. 5-minute cadence keeps the lobby current without
    // hammering the API (game times and statuses don't churn faster
    // than that). Skips work when the tab is hidden.
    this.espnRefreshInterval = setInterval(() => {
      if (typeof document !== 'undefined' && document.hidden) return
      this.fetchEspnGames()
    }, 5 * 60 * 1000)
  },
  beforeUnmount() {
    if (this.pollInterval) clearInterval(this.pollInterval)
    if (this.espnRefreshInterval) clearInterval(this.espnRefreshInterval)
  },
  watch: {
    // HTML5 `:max` on type=number is only a validation hint — users can
    // still type 999 or paste a huge value. Clamp on every change so the
    // input box itself reflects the real per-click + per-game cap.
    buyCount(n) {
      const max = this.maxBuy
      const num = Math.floor(Number(n) || 0)
      if (max <= 0) {
        if (num !== 0) this.buyCount = 0
        return
      }
      if (num > max) this.buyCount = max
      else if (num < 1) this.buyCount = 1
    },
    // If maxBuy drops (e.g. someone else bought a square, or the user
    // just bought 30 and only 20 are left), pull buyCount down to fit.
    maxBuy(newMax) {
      if (this.buyCount > newMax) this.buyCount = Math.max(1, newMax)
    },
  },
  methods: {
    async refreshState() {
      try {
        const storage = await getContractStorage(SQUARES_CONTRACT_ADDRESS)
        if (!storage) return
        this.currentGameId = Number(storage.currentGameId || 0)
        // `games` is a big_map in the v2 contract — storage carries only its
        // numeric id, so the rows come from the bigmap keys endpoint.
        this.allGames = this.currentGameId > 0
          ? await this.fetchGames(storage.games)
          : {}
        // Until the user clicks a game in the selector bar, follow the
        // newest pool. Once they've picked one (gameSelected = true),
        // keep their choice across polls — but clamp it if that game id
        // somehow no longer exists.
        if (!this.gameSelected || this.activeGameId >= this.currentGameId) {
          this.activeGameId = Math.max(0, this.currentGameId - 1)
        }
        this.game = this.allGames?.[this.activeGameId] || null
        // Cache the user's wallet address for the admin gate.
        try {
          const account = await this.wallet?.client?.getActiveAccount?.()
          this.myAddress = account?.address || ''
        } catch (_e) {
          this.myAddress = ''
        }
      } catch (e) {
        console.warn('squares storage refresh failed:', e?.message)
      }
    },
    // Resolve the `games` big_map into a { gameId: record } object. Storage
    // gives us only the bigmap's numeric id; a plain object means an
    // inline-map contract, so pass that straight through for back-compat.
    async fetchGames(games) {
      if (games == null) return {}
      if (typeof games === 'object') return games
      const rows = await tzktGet(`/v1/bigmaps/${games}/keys?active=true&limit=1000`)
      if (!rows) return {}
      const out = {}
      for (const row of rows) out[row.key] = row.value
      return out
    },
    // Game-selector bar: load a specific pool. Switches without a
    // refetch — refreshState() already cached every game in allGames.
    selectGameId(id) {
      this.activeGameId = Number(id)
      this.gameSelected = true
      this.game = this.allGames?.[this.activeGameId] || null
    },
    // Click handler for the top lobby. The create form is never hidden
    // by tile clicks — it just updates which game it targets.
    //   - Pool tile: view that pool below, and clear the ESPN selection
    //     so the form falls back to the pool's matchup (gridDisplayName).
    //   - "+ NEW" tile: stage that ESPN game in the form.
    selectLobbyEntry(entry) {
      // Don't clear lastCreatedPoolId here — the "✓ Card created" tile
      // is gated on activeGameId === lastCreatedPoolId, so it naturally
      // hides when you switch away and reappears when you click back.
      if (entry.kind === 'pool') {
        // User wants to ENTER an existing pool to bet — close the create
        // form so the bet interface (grid + Buy N squares) is what they
        // see right below the lobby instead of the form covering it.
        this.selectedEspnId = null
        this.newGameName = ''
        this.showCreateForm = false
        this.selectGameId(entry.poolId)
        return
      }
      const g = this.espnGames.find((x) => x.id === entry.espnId)
      if (!g) return
      this.pickEspnGame(g)
      this.showCreateForm = true
    },
    // Slide the 2-tile lobby window by exactly one game per arrow click.
    // No scroll — visibleLobby slices the next two entries — so the
    // tiles always sit at exactly half the strip width with no overflow.
    pageLobby(dir) {
      const maxStart = Math.max(0, this.lobby.length - 2)
      this.lobbyPage = Math.max(0, Math.min(this.lobbyPage + dir, maxStart))
    },
    // Short label for a game-selector button: the matchup (ESPN tag
    // stripped) when the pool is linked to an NBA game, else "Game #id".
    gameButtonLabel(id) {
      const name = this.allGames?.[id]?.name || ''
      const matchup = name
        .replace(/\bESPN:\d{6,}\b/, '')
        .replace(/^[\s\-–—·|]+/, '')
        .trim()
      if (!matchup) return name || 'Untitled pool'
      // Cavs pools read as "Cavs Vs. <opponent>" — matches the NBA picker.
      const m = /^(\w+)\s*@\s*(\w+)$/.exec(matchup)
      if (m && m[1] === 'CLE') return `Cavs Vs. ${m[2]}`
      if (m && m[2] === 'CLE') return `Cavs Vs. ${m[1]}`
      return matchup
    },
    pickRandomOpenSquares(n) {
      // Fisher-Yates partial shuffle of the open-square index pool.
      const pool = this.openSquareIdxs.slice()
      const take = Math.min(n, pool.length)
      for (let i = 0; i < take; i++) {
        const j = i + Math.floor(Math.random() * (pool.length - i))
        const tmp = pool[i]
        pool[i] = pool[j]
        pool[j] = tmp
      }
      return pool.slice(0, take)
    },
    setBuyMax() {
      this.buyCount = this.maxBuy
    },
    async buyRandomMany() {
      if (!this.canBuy) return
      const n = this.clampedBuyCount
      if (n <= 0) return
      const activeAccount = await this.wallet.client.getActiveAccount()
      if (!activeAccount) return
      const picks = this.pickRandomOpenSquares(n)
      if (picks.length === 0) {
        this.blockchainStatus = 'No open squares left.'
        return
      }
      this.tezos.setWalletProvider(this.wallet)
      this.blockchainStatus = `Buying ${picks.length} random square${picks.length === 1 ? '' : 's'}...`
      const perOpMutez = Number(this.game.ticketPrice) + Number(this.game.holderFee)
      const perOpTez = perOpMutez / 1_000_000
      try {
        const contract = await this.tezos.wallet.at(SQUARES_CONTRACT_ADDRESS)
        let batch = this.tezos.wallet.batch()
        for (const idx of picks) {
          batch = batch.withContractCall(
            contract.methodsObject.buySquare({ gameId: this.activeGameId, squareIdx: idx }),
            { amount: perOpTez },
          )
        }
        const op = await batch.send()
        this.blockchainStatus = `Submitted (${op.opHash}) — waiting for confirmation`
        await op.confirmation()
        this.blockchainStatus = `Bought ${picks.length} square${picks.length === 1 ? '' : 's'}: ${picks.join(', ')}`
        await this.refreshState()
      } catch (err) {
        console.error('buyRandomMany failed:', err)
        this.blockchainStatus = 'multi-buy failed — see console (likely a square was bought between pick and submit)'
      }
    },
    async claimAll() {
      const activeAccount = await this.wallet.client.getActiveAccount()
      if (!activeAccount) return
      this.tezos.setWalletProvider(this.wallet)
      this.blockchainStatus = 'Claiming pending winnings...'
      try {
        const contract = await this.tezos.wallet.at(SQUARES_CONTRACT_ADDRESS)
        const op = await contract.methodsObject.claim().send()
        await op.confirmation()
        this.blockchainStatus = 'claimed.'
      } catch (err) {
        console.error('claim failed:', err)
        this.blockchainStatus = 'no winnings to claim, or claim failed'
      }
    },
    toggleCreateForm() {
      this.showCreateForm = !this.showCreateForm
      if (this.showCreateForm) {
        if (!this.newGameName) this.newGameName = `Squares #${this.currentGameId}`
        // Pull the day's NBA slate the first time the form opens.
        if (!this.espnGames.length) this.fetchEspnGames()
      }
    },
    // Pull the forward DAYS_AHEAD-day slate across every league in LEAGUES
    // from ESPN's open scoreboard API — one request per league using the
    // `?dates=YYYYMMDD-YYYYMMDD` range syntax. Same endpoint family
    // scripts/sports_api.py uses on the oracle side. Results merged and
    // sorted by tip-off.
    async fetchEspnGames() {
      this.espnLoading = true
      this.espnGames = []
      try {
        const ymd = (d) =>
          `${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, '0')}` +
          `${String(d.getDate()).padStart(2, '0')}`
        const today = new Date()
        const end = new Date(today)
        end.setDate(today.getDate() + DAYS_AHEAD - 1)
        const range = `${ymd(today)}-${ymd(end)}`
        // One range request per league, in parallel.
        const requests = LEAGUES.map(async (lg) => {
          const url = `https://site.api.espn.com/apis/site/v2/sports/${lg.path}/scoreboard?dates=${range}`
          try {
            const res = await fetch(url, { headers: { Accept: 'application/json' } })
            if (!res.ok) return []
            const json = await res.json()
            return (json.events || []).map((ev) => {
              const comp = (ev.competitions || [])[0] || {}
              const cs = comp.competitors || []
              const home = cs.find((c) => c.homeAway === 'home') || cs[0] || {}
              const away = cs.find((c) => c.homeAway === 'away') || cs[1] || {}
              const t = (ev.status || {}).type || {}
              const periods = (c) =>
                (c.linescores || []).map((l) => Number(l.value ?? 0))
              return {
                league: lg.id,
                date: ev.date || '',
                id: String(ev.id),
                state: t.state || '',   // 'pre' | 'in' | 'post'
                homeAbbr: home.team?.abbreviation || '?',
                awayAbbr: away.team?.abbreviation || '?',
                homeName: home.team?.displayName || home.team?.shortDisplayName || '?',
                awayName: away.team?.displayName || away.team?.shortDisplayName || '?',
                homeLogo: home.team?.logo || '',
                awayLogo: away.team?.logo || '',
                // Box-score data — final tally + per-period scores.
                homeScore: home.score || '',
                awayScore: away.score || '',
                homePeriods: periods(home),
                awayPeriods: periods(away),
                statusDetail: t.shortDetail || t.detail || t.description || '',
              }
            })
          } catch {
            return []
          }
        })
        const results = await Promise.all(requests)
        // Drop entries where ESPN didn't supply real team abbreviations
        // (otherwise the lobby's first tile — and the auto-picked default
        // for the create form — can show "? @ ?" / "?v?"). Dedupe by id
        // (defensive — adjacent leagues can share ids theoretically, and
        // the same event can re-appear via timezone boundary fuzz). Sort
        // by tip-off date.
        // Rolling "upcoming only" filter — drop games that have
        // already ended or are currently in-progress. ESPN's `type.state`
        // is the source of truth ('pre' = not yet started). As a
        // belt-and-suspenders check we also gate on the wall-clock
        // start time so a stuck 'pre' from a delayed ESPN update can't
        // smuggle past midnight cutovers.
        const now = Date.now()
        const seen = new Set()
        this.espnGames = results
          .flat()
          .filter((g) => g.awayAbbr !== '?' && g.homeAbbr !== '?')
          .filter((g) => g.state === 'pre')
          .filter((g) => {
            const ts = Date.parse(g.date)
            return Number.isNaN(ts) ? true : ts > now
          })
          .filter((g) => (seen.has(g.id) ? false : seen.add(g.id)))
          .sort((a, b) => String(a.date).localeCompare(String(b.date)))
      } catch (e) {
        console.warn('ESPN scoreboard fetch failed:', e?.message)
      } finally {
        // Fall back to the Cavs/NBA test fixtures when every request comes
        // back empty (off-season, fetch failure, etc.) so the picker is
        // never a dead end during testing.
        if (!this.espnGames.length) {
          this.espnGames = TEST_NBA_GAMES.slice()
        }
        this.espnLoading = false
      }
    },
    // Render an ISO timestamp as "Tue 5/14 · 7:30 PM PST" in Pacific Time
    // (the timezone covers both PST and PDT — DST is handled automatically
    // by Intl). Returns '' if the input isn't a parseable date.
    formatGameDate(iso) {
      if (!iso) return ''
      const d = new Date(iso)
      if (Number.isNaN(d.getTime())) return ''
      const parts = new Intl.DateTimeFormat('en-US', {
        timeZone: 'America/Los_Angeles',
        weekday: 'short',
        month: 'numeric',
        day: 'numeric',
        hour: 'numeric',
        minute: '2-digit',
      }).formatToParts(d)
      const get = (t) => parts.find((p) => p.type === t)?.value || ''
      return `${get('weekday')} ${get('month')}/${get('day')} · ` +
        `${get('hour')}:${get('minute')} ${get('dayPeriod')} PST`
    },
    // Tip-off date label for the game-selector button: parse the pool's
    // on-chain name for its ESPN tag, then look up the date in the
    // picker's fetched slate. Empty string if the slate doesn't include
    // it (game outside the DAYS_AHEAD window, fetch hasn't run, etc.).
    gameButtonDateLabel(id) {
      const name = this.allGames?.[id]?.name || ''
      const m = /\bESPN:(\d{6,})\b/.exec(name)
      if (!m) return ''
      const ev = this.espnGames.find((g) => g.id === m[1])
      return ev ? this.formatGameDate(ev.date) : ''
    },
    // Picker label for an NBA game. Cavs games (the test fixtures, or a live
    // slate that includes Cleveland) read as "Cavs Vs. <opponent>"; every
    // other game keeps the plain away @ home abbreviation.
    espnGameLabel(g) {
      const CAVS = 'Cleveland Cavaliers'
      if (g.homeName === CAVS) return `Cavs Vs. ${g.awayName}`
      if (g.awayName === CAVS) return `Cavs Vs. ${g.homeName}`
      return `${g.awayAbbr} @ ${g.homeAbbr}`
    },
    // Bind / unbind the pool to an NBA game. The on-chain name carries
    // the "ESPN:<id>" tag — that's how the contract + oracle know which
    // real game this pool tracks. 64-char cap matches createGame()'s slice.
    pickEspnGame(g) {
      // Re-clicking the same tile is a no-op (form stays exactly as it
      // was) — the user explicitly does not want the form to disappear
      // or unbind when a game is clicked again.
      if (this.selectedEspnId === g.id) return
      this.selectedEspnId = g.id
      // ASCII only — Michelson strings reject unicode, so no "·"/em-dash.
      this.newGameName = `ESPN:${g.id} - ${g.awayAbbr} @ ${g.homeAbbr}`.slice(0, 64)
    },
    // Anyone can spin up a new Squares pool. The contract gates scoring
    // (reportQuarter) and randomization (setAxes) to admin, so the only
    // trust the creator earns is "I named the pool".
    async createGame() {
      // Hard gate: a pool has to track a real NBA game. The button is
      // disabled in this state too, but guard here in case createGame is
      // reached another way (keyboard, programmatic).
      if (!this.canCreateGame) {
        this.blockchainStatus = 'Pick an NBA game from the list first.'
        return
      }
      const activeAccount = await this.wallet.client.getActiveAccount()
      if (!activeAccount) return
      const ticketTez = Math.max(0.001, Number(this.newGameTicketTez) || 0.1)
      const ticketMutez = Math.round(ticketTez * 1_000_000)
      const holderFeeMutez = 50_000 // 0.05 ꜩ — matches AD / Plinko convention
      // Period count + weights are sport-specific (2 halves for soccer,
      // 3 periods for hockey, 4 quarters for NBA/NFL, 9 innings for MLB).
      // periodSpecForLeague derives both from the staged league.
      const { numPeriods, quarterWeights } = this.periodSpecForLeague(
        this.leagueForCreate(),
      )
      // Michelson strings are ASCII-only — strip anything outside printable
      // ASCII so a stray "·" / em-dash / emoji can't revert the tx with an
      // opaque "unicode symbols are not allowed" error.
      // eslint-disable-next-line no-control-regex
      const asciiName = (this.newGameName || `Squares #${this.currentGameId}`)
        .replace(/[^\x20-\x7E]/g, '')
        .trim()
      const name = (asciiName || `Squares #${this.currentGameId}`).slice(0, 64)
      this.tezos.setWalletProvider(this.wallet)
      this.blockchainStatus = `Creating "${name}"...`
      try {
        const contract = await this.tezos.wallet.at(SQUARES_CONTRACT_ADDRESS)
        const op = await contract.methodsObject
          .createGame({
            name,
            ticketPrice: ticketMutez,
            holderFee: holderFeeMutez,
            numPeriods,
            quarterWeights,
          })
          .send()
        this.blockchainStatus = `Submitted (${op.opHash}) — waiting for confirmation`
        await op.confirmation()
        this.blockchainStatus = `New game created: "${name}".`
        this.showCreateForm = false
        this.newGameName = ''
        this.selectedEspnId = null
        // Jump the selector bar to the just-created game.
        this.gameSelected = false
        await this.refreshState()
        // Stash for the "✓ Card created" confirmation tile.
        this.lastCreatedPoolId = this.activeGameId
      } catch (err) {
        console.error('createGame failed:', err)
        this.blockchainStatus = 'createGame failed — see console'
      }
    },
    // A "card" is a Squares pool bound to a specific game. Two entry points:
    //   1. The user is viewing an existing pool ⇒ reuse `this.game.name` so
    //      the new card carries the same ESPN tag (same oracle scoring).
    //   2. The user picked an ESPN game from the top lobby (selectedEspnId
    //      set, newGameName already populated by pickEspnGame) ⇒ use that.
    // Either way the creator only picks the per-square price.
    async createCard() {
      // Prefer the lobby-picked game's name when selectedEspnId is set —
      // matches what selectedGameLabel shows in the form. Fall back to the
      // currently-viewed pool's name when there's no fresh selection.
      const sourceName = this.selectedEspnId
        ? this.newGameName
        : (this.game?.name || this.newGameName)
      if (!sourceName) {
        this.blockchainStatus = 'Pick a game first.'
        return
      }
      const activeAccount = await this.wallet.client.getActiveAccount()
      if (!activeAccount) return
      const ticketTez = Math.max(0.001, Number(this.newGameTicketTez) || 0.1)
      const ticketMutez = Math.round(ticketTez * 1_000_000)
      const holderFeeMutez = 50_000 // 0.05 ꜩ — matches createGame()
      // Period model from the source game's league. Same path createGame
      // uses, so a card always inherits the right scoring model.
      const { numPeriods, quarterWeights } = this.periodSpecForLeague(
        this.leagueForCreate(),
      )
      // Same ASCII-only guard as createGame() — Michelson rejects unicode.
      // eslint-disable-next-line no-control-regex
      const name = sourceName
        .replace(/[^\x20-\x7E]/g, '')
        .trim()
        .slice(0, 64) || `Squares #${this.currentGameId}`
      this.tezos.setWalletProvider(this.wallet)
      this.blockchainStatus = `Creating a new card for "${name}"...`
      try {
        const contract = await this.tezos.wallet.at(SQUARES_CONTRACT_ADDRESS)
        const op = await contract.methodsObject
          .createGame({
            name,
            ticketPrice: ticketMutez,
            holderFee: holderFeeMutez,
            numPeriods,
            quarterWeights,
          })
          .send()
        this.blockchainStatus = `Submitted (${op.opHash}) — waiting for confirmation`
        await op.confirmation()
        this.blockchainStatus = `New card created for "${name}".`
        this.showCreateForm = false
        this.selectedEspnId = null
        this.newGameName = ''
        // Jump the selector bar to the just-created card.
        this.gameSelected = false
        await this.refreshState()
        // After refreshState the new pool is at currentGameId - 1 and is
        // also activeGameId (because gameSelected was just cleared).
        // Stash it so the "✓ Card created" tile renders below the panel.
        this.lastCreatedPoolId = this.activeGameId
      } catch (err) {
        console.error('createCard failed:', err)
        this.blockchainStatus = 'createCard failed — see console'
      }
    },
    // Admin-only: close sales when the board is full or it's gametime.
    async lockSales() {
      if (!this.isAdmin) return
      const activeAccount = await this.wallet.client.getActiveAccount()
      if (!activeAccount) return
      this.tezos.setWalletProvider(this.wallet)
      this.blockchainStatus = 'Locking sales...'
      try {
        const contract = await this.tezos.wallet.at(SQUARES_CONTRACT_ADDRESS)
        // v2 entrypoint is `closeSales`, taking a { gameId } record — it
        // flips the game's phase to LOCKED.
        const op = await contract.methodsObject
          .closeSales({ gameId: this.activeGameId })
          .send()
        await op.confirmation()
        this.blockchainStatus = 'Sales locked.'
        await this.refreshState()
      } catch (err) {
        console.error('closeSales failed:', err)
        this.blockchainStatus = 'Lock sales failed — see console'
      }
    },
    // Admin escape hatch when a grid never fills. v2's refundUnsold credits
    // each buyer their ticket price back into the pending-claim map (and
    // marks the game COMPLETE); buyers then call claim() to actually pull
    // the funds. Valid only while phase is SELLING or LOCKED.
    async refundUnsold() {
      if (!this.isAdmin) return
      const activeAccount = await this.wallet.client.getActiveAccount()
      if (!activeAccount) return
      this.tezos.setWalletProvider(this.wallet)
      this.blockchainStatus = 'Refunding unsold squares...'
      try {
        const contract = await this.tezos.wallet.at(SQUARES_CONTRACT_ADDRESS)
        const op = await contract.methodsObject
          .refundUnsold({ gameId: this.activeGameId })
          .send()
        await op.confirmation()
        this.blockchainStatus = 'Refunds queued — buyers can Claim winnings.'
        await this.refreshState()
      } catch (err) {
        console.error('refundUnsold failed:', err)
        this.blockchainStatus = 'Refund failed — see console'
      }
    },
    isMine(owner) {
      if (!owner) return false
      if (this.myAddress) return owner === this.myAddress
      // Fallback for sessions where myAddress hasn't loaded yet.
      return this.walletAddress?.endsWith(owner.slice(-4))
    },
    // True when this 10×10 cell index is one of the TXL house cells
    // (currently idx 44 + idx 90). Used by the grid to label / style
    // those cells as "TXL" and to skip them in the random-buy pool.
    isHouse(idx) {
      return HOUSE_SQUARES.has(idx)
    },
    // Period model (numPeriods + quarterWeights) for a given league.
    // Sport-specific so contract reportQuarter accepts the right number
    // of reports and the pool's weight distribution mirrors how the
    // sport actually scores. Only basketball-family quarters are
    // supported right now (NBA / WNBA / NFL / NCAAM all share the same
    // 4-quarter, 15/15/15/55 shape). NHL/soccer/MLB used to live here
    // but were pulled — too few points per period for the mod-10 digit
    // lottery to feel fair. Restore from git history if/when we add a
    // more forgiving payout model for low-scoring sports.
    periodSpecForLeague(_league) {
      // four quarters, 15/15/15/55.
      return {
        numPeriods: 4,
        quarterWeights: { 0: 15, 1: 15, 2: 15, 3: 55 },
      }
    },
    // Resolve the league for whatever game the create-card form is
    // about to bind to. Falls back to '' (unknown) → 4-quarter default.
    leagueForCreate() {
      // If the user staged an ESPN selection, that's the truth.
      if (this.selectedEspnId) {
        const g = this.espnGames.find((x) => x.id === this.selectedEspnId)
        if (g?.league) return g.league
      }
      // Otherwise parse the active pool's name for its ESPN tag and
      // look it up in the picker slate. Pools whose game isn't in the
      // current 3-day window won't resolve — that's fine, we default.
      const name = this.game?.name || this.newGameName || ''
      const m = /\bESPN:(\d{6,})\b/.exec(name)
      if (m) {
        const ev = this.espnGames.find((x) => x.id === m[1])
        if (ev?.league) return ev.league
      }
      return ''
    },
    // True when the connected wallet owns at least one square in this
    // pool — drives the "BETTING" badge on the lobby tile so the user
    // can spot at a glance which cards they're already in.
    isMyPool(poolId) {
      if (!this.myAddress) return false
      const squares = this.allGames?.[poolId]?.squares || {}
      for (const owner of Object.values(squares)) {
        if (owner === this.myAddress) return true
      }
      return false
    },
    // Short-form creator address for the lobby tile. Pools are global —
    // every user sees pools created by every other user — so surface
    // who started this one as a "by t.AbCd" line.
    poolCreator(poolId) {
      const creator = this.allGames?.[poolId]?.creator || ''
      return creator ? reduceAddress(creator) : ''
    },
  },
}
</script>

<template>
  <div class="gameManagement squaresRoot">
    <!-- The 10×10 board always renders — blank (numbered, no owners)
         when no game is loaded, live once one is. Sits at the top of
         the view so the play surface is the first thing the user sees;
         lobby, create form, stats and buy controls live underneath. -->
    <div class="squaresWrap">
      <table class="squaresGrid">
        <thead>
          <tr>
            <th></th>
            <th v-for="c in 10" :key="c">
              {{ game && game.axesAssigned ? game.axisAway?.[c - 1] : '?' }}
            </th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(row, r) in grid" :key="r">
            <th>{{ game && game.axesAssigned ? game.axisHome?.[r] : '?' }}</th>
            <td
              v-for="cell in row"
              :key="cell.idx"
              :class="[
                'square',
                isHouse(cell.idx) ? 'house' : (cell.owner ? 'taken' : 'open'),
                isMine(cell.owner) ? 'mine' : '',
              ]"
            >
              <span v-if="isHouse(cell.idx)" class="houseLabel">TXL</span>
              <span v-else-if="cell.owner" class="ownerInitial">
                {{ cell.owner.slice(-3) }}
              </span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Top lobby — every upcoming ESPN game across all leagues plus
         every existing on-chain pool. Pool tiles jump to that pool;
         no-pool tiles open the create form pre-bound to that game.
         Arrows scroll the strip horizontally, DK/FD style. -->
    <div class="sqLobbyCarousel">
      <button
        type="button"
        :class="['navArrow', 'navArrow--left', lobbyCanPageLeft ? '' : 'navArrow--disabled']"
        :disabled="!lobbyCanPageLeft"
        aria-label="Previous game"
        @click="pageLobby(-1)"
      >‹</button>
      <div class="rowFlex sqGameBar" ref="lobbyStrip">
        <div
          v-for="entry in visibleLobby"
          :key="entry.key"
          :class="[
            'actionButton',
            'sqGameBtn',
            (entry.kind === 'pool' && activeGameId === entry.poolId) ||
            (entry.kind === 'espn' && selectedEspnId === entry.espnId)
              ? 'sqGameBtn--active'
              : '',
            entry.kind === 'pool' && isMyPool(entry.poolId) ? 'sqGameBtn--mine' : '',
          ]"
          @click="selectLobbyEntry(entry)"
        >
          <div class="sqGameBtnHead">
            <span
              v-if="entry.league"
              :class="['sqLeague', `sqLeague--${entry.league.toLowerCase()}`]"
            >{{ entry.league }}</span>
            <span
              :class="['sqGameBtnTag', entry.kind === 'pool' ? 'sqGameBtnTag--pool' : 'sqGameBtnTag--new']"
            >{{ entry.kind === 'pool' ? 'POOL' : '+ NEW' }}</span>
            <span
              v-if="entry.kind === 'pool' && isMyPool(entry.poolId)"
              class="sqGameBtnTag sqGameBtnTag--mine"
            >YOU</span>
          </div>
          <div class="sqGameBtnMain">{{ entry.title }}</div>
          <div v-if="entry.date" class="sqGameBtnWhen">
            {{ formatGameDate(entry.date) }}
          </div>
          <div
            v-if="entry.kind === 'pool' && poolCreator(entry.poolId)"
            class="sqGameBtnCreator"
          >by {{ poolCreator(entry.poolId) }}</div>
        </div>
        <div v-if="!lobby.length" class="gameInfo sqGameBarEmpty">
          Loading the lobby…
        </div>
      </div>
      <button
        type="button"
        :class="['navArrow', 'navArrow--right', lobbyCanPageRight ? '' : 'navArrow--disabled']"
        :disabled="!lobbyCanPageRight"
        aria-label="Next game"
        @click="pageLobby(1)"
      >›</button>
    </div>

    <!-- Start a new card (for the selected game) or — when nothing is
         selected — a brand-new game. Sits right under the lobby so the
         selection + create flow is one continuous block. -->
    <div class="sqCreatePanel">
      <!-- No manual toggle: the create form opens by clicking a "+ NEW"
           lobby tile (selectLobbyEntry pre-binds the game and flips
           showCreateForm). It closes on successful create, or when the
           user switches to a pool tile. -->


      <!-- A "card" is a Squares pool bound to a specific game — either
           the currently selected pool's game, or whatever the user
           picked from the top lobby. Only the per-square price is
           needed; everything else is inherited from the game. -->
      <div v-if="showCreateForm && (game || selectedEspnId)" class="sqCreateForm sqCreateForm--compact">
        <div class="sqCreateHeader">
          <span class="sqCreateLabel">New card</span>
          <span class="sqCreateHeaderGame">{{ selectedGameLabel }}</span>
        </div>
        <label class="sqCreateField sqCreateField--inline">
          <span class="sqCreateLabel">ꜩ / square</span>
          <input
            type="number"
            min="0.001"
            step="0.1"
            v-model.number="newGameTicketTez"
            class="sqCreateInput sqCreateInput--compact"
          />
        </label>
        <div class="rowFlex">
          <div class="actionButton sqPrimary" @click="createCard">
            Create — {{ Number(newGameTicketTez).toFixed(3) }} ꜩ/sq
          </div>
        </div>
      </div>

      <!-- No game selected yet → full new-game flow: pick the matchup. -->
      <div v-else-if="showCreateForm" class="sqCreateForm">
        <div class="sqCreateField">
          <span class="sqCreateLabel">Pick a game (required)</span>
          <div class="rowFlex sqEspnDateRow">
            <div class="sqCreateHint sqEspnWindowHint">
              Showing the next {{ DAYS_AHEAD }} days · NBA · WNBA
            </div>
            <div class="actionButton sqEspnRefresh" @click="fetchEspnGames">
              {{ espnLoading ? 'Loading…' : 'Refresh slate' }}
            </div>
          </div>
          <div v-if="espnLoading" class="sqCreateHint">Loading slate…</div>
          <div v-else-if="!espnGames.length" class="sqCreateHint">
            No games in the next {{ DAYS_AHEAD }} days.
          </div>
          <div v-else class="sqEspnList">
            <div
              v-for="g in espnGames"
              :key="g.id"
              :class="['sqGameCard', selectedEspnId === g.id ? 'sqGameCard--active' : '']"
              @click="pickEspnGame(g)"
            >
              <div class="sqGameCardTop">
                <div class="sqGameTitleRow">
                  <span
                    v-if="g.league"
                    :class="['sqLeague', `sqLeague--${g.league.toLowerCase()}`]"
                  >{{ g.league }}</span>
                  <div class="sqGameTitleStack">
                    <span class="sqGameTitle">{{ espnGameLabel(g) }}</span>
                    <span v-if="g.date" class="sqGameWhen">{{ formatGameDate(g.date) }}</span>
                  </div>
                </div>
                <span class="sqGameStatus">{{ g.statusDetail }}</span>
              </div>
              <div class="sqBox">
                <div
                  v-if="g.awayPeriods && g.awayPeriods.length"
                  class="sqBoxRow sqBoxHeader"
                >
                  <span class="sqBoxTeam"></span>
                  <span
                    v-for="i in g.awayPeriods.length"
                    :key="`h${i}`"
                    class="sqBoxCell"
                  >{{ i }}</span>
                  <span class="sqBoxCell sqBoxFinal">F</span>
                </div>
                <div class="sqBoxRow">
                  <span class="sqBoxTeam">
                    <img v-if="g.awayLogo" :src="g.awayLogo" :alt="g.awayAbbr" class="sqBoxLogo" />
                    <span class="sqBoxAbbr">{{ g.awayAbbr }}</span>
                  </span>
                  <span
                    v-for="(p, i) in (g.awayPeriods || [])"
                    :key="`a${i}`"
                    class="sqBoxCell"
                  >{{ p }}</span>
                  <span v-if="g.awayScore" class="sqBoxCell sqBoxFinal">{{ g.awayScore }}</span>
                </div>
                <div class="sqBoxRow">
                  <span class="sqBoxTeam">
                    <img v-if="g.homeLogo" :src="g.homeLogo" :alt="g.homeAbbr" class="sqBoxLogo" />
                    <span class="sqBoxAbbr">{{ g.homeAbbr }}</span>
                  </span>
                  <span
                    v-for="(p, i) in (g.homePeriods || [])"
                    :key="`hp${i}`"
                    class="sqBoxCell"
                  >{{ p }}</span>
                  <span v-if="g.homeScore" class="sqBoxCell sqBoxFinal">{{ g.homeScore }}</span>
                </div>
              </div>
              <div v-if="selectedEspnId === g.id" class="sqGamePicked">
                ✓ Selected — tap again to unbind
              </div>
            </div>
          </div>
        </div>
        <label class="sqCreateField">
          <span class="sqCreateLabel">Name</span>
          <input
            type="text"
            maxlength="64"
            v-model="newGameName"
            :placeholder="`Squares #${currentGameId}`"
            class="sqCreateInput"
          />
        </label>
        <label class="sqCreateField">
          <span class="sqCreateLabel">Tez per square</span>
          <input
            type="number"
            min="0.001"
            step="0.1"
            v-model.number="newGameTicketTez"
            class="sqCreateInput"
          />
        </label>
        <div class="sqCreateHint">
          0.05 ꜩ holder fee · 15/15/15/55 split · auto-lock at 100.
          <template v-if="selectedEspnId">Oracle auto-reports scores.</template>
          <template v-else>Pick a game above to enable Start.</template>
        </div>
        <div class="rowFlex">
          <div
            :class="['actionButton', 'sqPrimary', canCreateGame ? '' : 'sqPrimaryDisabled']"
            @click="createGame"
          >
            <template v-if="canCreateGame">
              Start — {{ Number(newGameTicketTez).toFixed(3) }} ꜩ/sq
            </template>
            <template v-else>Pick a game first</template>
          </div>
        </div>
      </div>

      <!-- Confirmation tile after a successful create. Re-renders
           whenever the user is viewing that pool, so navigating away
           and back via the lobby brings the card-summary back. -->
      <div
        v-if="lastCreatedPoolId !== null
          && activeGameId === lastCreatedPoolId
          && !showCreateForm"
        class="sqCreatedTile"
      >
        <div class="sqCreatedHead">✓ Card created</div>
        <div class="sqCreatedBody">
          <strong>{{ lastCreatedGameLabel }}</strong>
          <span>{{ lastCreatedPrice }} ꜩ / square</span>
        </div>
        <div class="sqCreatedHint">
          Your grid is loaded below — buy squares to enter.
        </div>
      </div>
    </div>

    <div v-if="!game" class="gameInfo">
      No game loaded yet. Start one below.
    </div>
    <div v-else class="rowFlex">
      <div class="txlRank">Sold: {{ sold }} / 100</div>
      <div class="txlRank">Pot: {{ potTez }} ꜩ</div>
      <div class="txlRank">Ticket: {{ ticketPriceTez }} ꜩ + {{ feePriceTez }} ꜩ fee</div>
    </div>

    <!-- Buy + admin controls only make sense once a game is loaded. -->
    <template v-if="game">
      <!-- Buy squares: pick a count, the contract assigns squares at random.
           Max 50 per click; the center cell is reserved for TXL holders. -->
      <div class="rowFlex sqQuickBuyRow">
        <input
          class="sqBuyInput"
          type="number"
          min="1"
          :max="maxBuy"
          v-model.number="buyCount"
          :disabled="!canBuy || maxBuy === 0"
        />
        <div class="actionButton sqMaxBtn" @click="setBuyMax">Max ({{ maxBuy }})</div>
        <div
          :class="['actionButton', 'sqPrimary', !canBuy || maxBuy === 0 ? 'sqPrimaryDisabled' : '']"
          @click="canBuy && maxBuy > 0 && buyRandomMany()"
        >
          Buy {{ clampedBuyCount }} — {{ buyTotalTez }} ꜩ
        </div>
        <div class="actionButton" @click="claimAll">Claim</div>
      </div>
      <div class="sqQuickBuyHint">
        <template v-if="atPerGameLimit">
          You own {{ myOwnedSquaresInGame }} squares — the {{ MAX_BUY_PER_PLAYER_PER_GAME }}-per-game limit.
        </template>
        <template v-else-if="myOwnedSquaresInGame > 0">
          You own {{ myOwnedSquaresInGame }}/{{ MAX_BUY_PER_PLAYER_PER_GAME }} · {{ myRemainingAllowance }} more allowed. Center pays TXL.
        </template>
        <template v-else>
          Random assignment · ≤{{ MAX_BUY_PER_CLICK }} per click · ≤{{ MAX_BUY_PER_PLAYER_PER_GAME }} per game · center pays TXL.
        </template>
      </div>

      <!-- Admin actions — score reporting + sales lock stay restricted. -->
      <div v-if="isAdmin" class="sqAdminPanel">
        <div class="sqAdminLabel">Admin</div>
        <div class="rowFlex">
          <div class="actionButton" @click="lockSales">Lock sales</div>
          <div class="actionButton" @click="refundUnsold">Refund unsold</div>
        </div>
      </div>
    </template>

    <div class="gameInfo sqStatusLine">{{ blockchainStatus }}</div>
  </div>
</template>

<style scoped>
/* ─── Layout root ─────────────────────────────────────────────────────── */
.squaresRoot {
  font-family: 'EB Garamond';
  color: #efeae2;
}

/* ─── Primary CTAs ───────────────────────────────────────────────────── */
.sqPrimary {
  background: linear-gradient(135deg, #1f5c3a 0%, #0e3b22 100%);
  border-color: #f5c451;
  color: #fff;
  font-weight: 700;
  letter-spacing: 1px;
  text-transform: uppercase;
}
.sqPrimaryDisabled {
  opacity: 0.4;
  cursor: not-allowed;
  filter: grayscale(0.4);
}

/* ─── Quick-buy (N random squares) ───────────────────────────────────── */
.sqQuickBuy {
  margin: 10px 4px 4px;
  padding: 10px 12px;
  border-radius: 8px;
  background: rgba(245, 196, 81, 0.05);
  border: 1px solid rgba(245, 196, 81, 0.25);
}
.sqQuickBuyLabel {
  font-size: 10px;
  letter-spacing: 3px;
  text-transform: uppercase;
  color: #f5c451;
  font-weight: 700;
  margin-bottom: 8px;
}
.sqQuickBuyRow { align-items: center; gap: 8px; }
.sqBuyInput {
  width: 80px;
  padding: 8px 10px;
  font-family: 'EB Garamond';
  font-size: 16px;
  background: rgba(0, 0, 0, 0.35);
  color: #efeae2;
  border: 1px solid rgba(245, 196, 81, 0.35);
  border-radius: 6px;
  text-align: center;
}
.sqBuyInput:disabled { opacity: 0.4; cursor: not-allowed; }
.sqMaxBtn { flex: 0 0 auto; }
.sqQuickBuyHint {
  margin-top: 6px;
  font-size: 11px;
  color: rgba(255, 255, 255, 0.55);
  font-style: italic;
}

/* ─── Create-game panel (open to all users) ─────────────────────────── */
.sqCreatePanel {
  margin: 8px 4px 4px;
}
.sqCreateToggle {
  flex: 0 0 auto;
}
.sqCreateForm {
  margin-top: 6px;
  padding: 8px 10px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.08);
}
/* Action buttons inside the create form / quick-buy row break their
   text instead of overflowing — dynamic content ("Buy 50 squares —
   5.000 ꜩ", "Start game — 0.100 ꜩ / square", etc.) is long enough to
   blow out the button on narrower viewports without this. */
.sqCreateForm .actionButton,
.sqQuickBuyRow .actionButton {
  white-space: normal;
  word-break: break-word;
  text-align: center;
  line-height: 1.25;
  min-width: 0;
  flex-shrink: 1;
}
/* Confirmation tile after a successful card create. Green accent so it
   reads as "✓ done", and sits right below where the form was. */
.sqCreatedTile {
  margin-top: 12px;
  padding: 12px 14px;
  border-radius: 8px;
  background: linear-gradient(180deg, rgba(74, 222, 128, 0.14), rgba(74, 222, 128, 0.04));
  border: 1px solid rgba(74, 222, 128, 0.45);
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.sqCreatedHead {
  font-weight: 800;
  color: #4ade80;
  font-size: 14px;
  letter-spacing: 0.04em;
}
.sqCreatedBody {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  font-size: 14px;
  color: rgba(255, 255, 255, 0.92);
}
.sqCreatedBody strong {
  color: #f5c451;
  font-weight: 700;
}
.sqCreatedHint {
  font-size: 12px;
  font-style: italic;
  color: rgba(255, 255, 255, 0.65);
}
.sqCreateField {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin-bottom: 6px;
}
.sqCreateLabel {
  font-size: 11px;
  letter-spacing: 1.6px;
  text-transform: uppercase;
  color: rgba(255, 255, 255, 0.7);
  font-weight: 700;
}
.sqCreateInput {
  padding: 6px 10px;
  font-family: 'EB Garamond';
  font-size: 15px;
  background: rgba(0, 0, 0, 0.35);
  color: #efeae2;
  border: 1px solid rgba(245, 196, 81, 0.25);
  border-radius: 6px;
}
.sqCreateHint {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.7);
  font-style: italic;
  margin-bottom: 4px;
  line-height: 1.3;
}
/* Compact mode used for the "new card for an existing game" path —
   collapses the New card header + game-label into one row, and runs
   the ꜩ/square label inline with the input instead of stacked. */
.sqCreateHeader {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-bottom: 6px;
  flex-wrap: wrap;
}
.sqCreateHeaderGame {
  font-size: 13px;
  color: rgba(255, 255, 255, 0.85);
  font-weight: 600;
  min-width: 0;
  flex: 1 1 auto;
}
.sqCreateField--inline {
  flex-direction: row;
  align-items: center;
  gap: 8px;
}
.sqCreateField--inline .sqCreateLabel {
  flex: 0 0 auto;
}
.sqCreateInput--compact {
  flex: 1 1 100px;
  min-width: 0;
  padding: 5px 8px;
  font-size: 14px;
}

/* ─── NBA game picker (inside the create-game form) ──────────────────── */
.sqEspnDateRow {
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}
.sqEspnRefresh { flex: 0 0 auto; }
/* ─── DraftKings/FanDuel-style game lobby ────────────────────────────
   Each matchup is a tappable card: matchup title + status pill up
   top, then an away row and a home row with logo, abbr, and full name.
   Uniform-size grid that wraps onto more rows as the slate grows —
   every tile shares one width (auto-fill + minmax) and one height
   (grid-auto-rows), so adding games never reflows the existing cards. */
.sqEspnList {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  grid-auto-rows: 130px;
  gap: 8px;
  max-height: 420px;
  overflow-y: auto;
  margin-bottom: 4px;
  padding-right: 2px;
}
.sqGameCard {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 10px 12px;
  border-radius: 10px;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.04), rgba(0, 0, 0, 0.35));
  border: 1px solid rgba(255, 255, 255, 0.10);
  cursor: pointer;
  user-select: none;
  /* Pin to the grid cell so every tile is exactly the same size,
     regardless of whether linescores are present yet. */
  height: 100%;
  overflow: hidden;
  transition: border-color 0.15s ease, transform 0.1s ease, box-shadow 0.15s ease;
}
.sqGameCard:hover {
  border-color: rgba(245, 196, 81, 0.5);
  transform: translateY(-1px);
  box-shadow: 0 4px 14px rgba(0, 0, 0, 0.35);
}
.sqGameCard--active {
  border-color: #f5c451;
  background: linear-gradient(180deg, rgba(245, 196, 81, 0.14), rgba(245, 196, 81, 0.04));
  box-shadow: 0 0 0 1px rgba(245, 196, 81, 0.35);
}
.sqGameCardTop {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.sqGameTitleRow {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}
.sqGameTitleStack {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
}
.sqGameTitle {
  font-weight: 700;
  font-size: 16px;
  color: #f5c451;
  letter-spacing: 0.01em;
}
.sqGameWhen {
  font-size: 13px;
  font-weight: 500;
  color: rgba(255, 255, 255, 0.78);
  letter-spacing: 0.02em;
}
/* League pill on each game card. Colors echo each league's brand so
   the merged lobby's entries read as visually distinct. */
.sqLeague {
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.08em;
  padding: 3px 8px;
  border-radius: 4px;
  flex: 0 0 auto;
}
.sqLeague--nba {
  background: rgba(245, 132, 31, 0.18);
  color: #ff9a3c;
  border: 1px solid rgba(245, 132, 31, 0.5);
}
.sqLeague--epl {
  background: rgba(95, 0, 156, 0.22);
  color: #c89aff;
  border: 1px solid rgba(95, 0, 156, 0.55);
}
/* Inline window hint on the picker header row. */
.sqEspnWindowHint {
  flex: 1;
  align-self: center;
  margin: 0;
}
.sqGameStatus {
  font-size: 12px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: rgba(255, 255, 255, 0.75);
  background: rgba(0, 0, 0, 0.35);
  border: 1px solid rgba(255, 255, 255, 0.10);
  border-radius: 999px;
  padding: 3px 10px;
  white-space: nowrap;
}
.sqGameTeam {
  display: flex;
  align-items: center;
  gap: 8px;
}
.sqGameLogo {
  width: 26px;
  height: 26px;
  object-fit: contain;
  flex: 0 0 auto;
}
.sqGameAbbr {
  font-weight: 800;
  font-size: 13px;
  width: 38px;
  flex: 0 0 auto;
}
.sqGameTeamName {
  flex: 1;
  font-size: 12px;
  color: rgba(255, 255, 255, 0.85);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.sqGameSide {
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.08em;
  color: rgba(255, 255, 255, 0.4);
  flex: 0 0 auto;
}
/* ─── Box-score (per-period scores + final) ───────────────────────── */
.sqBox {
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}
.sqBoxRow {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 14px;
  color: rgba(255, 255, 255, 0.95);
}
.sqBoxHeader {
  font-size: 12px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: rgba(255, 255, 255, 0.6);
}
.sqBoxTeam {
  flex: 0 0 86px;
  display: flex;
  align-items: center;
  gap: 6px;
}
.sqBoxLogo {
  width: 22px;
  height: 22px;
  object-fit: contain;
}
.sqBoxAbbr {
  font-weight: 800;
  font-size: 14px;
}
.sqBoxCell {
  flex: 0 0 30px;
  text-align: center;
  font-variant-numeric: tabular-nums;
}
.sqBoxFinal {
  font-weight: 800;
  color: #f5c451;
}
.sqGamePicked {
  font-size: 13px;
  font-weight: 700;
  color: #f5c451;
  text-align: center;
  padding-top: 4px;
  border-top: 1px solid rgba(245, 196, 81, 0.25);
}

/* ─── Admin panel ────────────────────────────────────────────────────── */
.sqAdminPanel {
  margin: 14px 4px;
  padding: 10px 12px;
  border-radius: 8px;
  background: rgba(196, 82, 79, 0.08);
  border: 1px dashed rgba(196, 82, 79, 0.45);
}
.sqAdminLabel {
  font-size: 10px;
  letter-spacing: 3px;
  text-transform: uppercase;
  color: #c4524f;
  font-weight: 700;
  margin-bottom: 6px;
}

/* ─── Rules drawer ───────────────────────────────────────────────────── */
.sqRules {
  margin: 8px 4px 12px;
  padding: 12px 16px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.08);
}
.sqRules ol {
  margin: 0;
  padding-left: 20px;
  color: rgba(255, 255, 255, 0.85);
  font-size: 13px;
  line-height: 1.55;
}
.sqRules li { margin: 4px 0; }

.sqStatusLine {
  font-size: 14px;
  color: #d4a24e;
  font-style: italic;
}

/* ─── Play view header ───────────────────────────────────────────────── */
/* ─── Game-selector bar ───────────────────────────────────────────── */
/* Lobby carousel — arrows flank a 2-tile pagination strip. visibleLobby
   slices exactly two entries; tiles split the strip width 50/50 with no
   scrolling or overflow. */
.sqLobbyCarousel {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  margin: 4px 0 8px;
}
.sqGameBar {
  flex: 1;
  min-width: 0;
  flex-wrap: nowrap;
  overflow: hidden;
  gap: 6px;
}
.navArrow--disabled {
  opacity: 0.35;
  cursor: default;
  pointer-events: none;
}
.sqGameBtn {
  /* Pagination: only two entries rendered at a time, each takes equal
     half of the strip's available width. min-width: 0 lets flex shrink
     past the content's natural width so nothing spills to the right. */
  flex: 1 1 0;
  min-width: 0;
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 3px;
  line-height: 1.2;
  padding: 8px 10px;
  text-align: left;
}
/* Hover-preview state — gold-tinted border + subtle lift, lighter than
   the active state so the currently-selected tile still wins visually. */
.sqGameBtn:hover {
  border-color: rgba(245, 196, 81, 0.55);
  background: rgba(245, 196, 81, 0.06);
  transform: translateY(-1px);
}
.sqGameBtnHead {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
}
.sqGameBtnTag {
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.08em;
  padding: 3px 8px;
  border-radius: 999px;
}
.sqGameBtnTag--pool {
  background: rgba(74, 222, 128, 0.18);
  color: #4ade80;
  border: 1px solid rgba(74, 222, 128, 0.45);
}
.sqGameBtnTag--mine {
  background: rgba(74, 222, 128, 0.22);
  color: #4ade80;
  border: 1px solid rgba(74, 222, 128, 0.55);
}
.sqGameBtnTag--new {
  background: rgba(255, 255, 255, 0.06);
  color: rgba(255, 255, 255, 0.65);
  border: 1px solid rgba(255, 255, 255, 0.15);
}
.sqGameBtnMain {
  font-size: 15px;
  font-weight: 700;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 100%;
}
.sqGameBtnWhen {
  font-size: 12.5px;
  font-weight: 600;
  letter-spacing: 0.04em;
  color: rgba(255, 255, 255, 0.78);
  white-space: nowrap;
}
.sqGameBtn--active {
  border-color: #f5c451;
  background: linear-gradient(180deg, rgba(245, 196, 81, 0.18), rgba(245, 196, 81, 0.06));
  box-shadow:
    0 0 0 2px rgba(245, 196, 81, 0.55),
    0 4px 14px rgba(245, 196, 81, 0.25);
  color: #f5c451;
  transform: translateY(-1px);
}
.sqGameBtn--active .sqGameBtnMain,
.sqGameBtn--active .sqGameBtnWhen { color: #f5c451; }
/* Tile for pools the connected wallet is betting on — green accent so
   the user can spot at a glance which cards they're already in. */
.sqGameBtn--mine {
  border-color: rgba(74, 222, 128, 0.55);
  box-shadow: 0 0 0 1px rgba(74, 222, 128, 0.3) inset;
}
.sqGameBtn--mine.sqGameBtn--active {
  /* When a "you're in" pool is also currently active, gold takes the
     outer ring and green stays as a subtle inner accent. */
  box-shadow:
    0 0 0 2px rgba(245, 196, 81, 0.55),
    0 0 0 1px rgba(74, 222, 128, 0.55) inset,
    0 4px 14px rgba(245, 196, 81, 0.25);
}
.sqGameBtnCreator {
  font-size: 10px;
  font-style: italic;
  color: rgba(255, 255, 255, 0.55);
  letter-spacing: 0.02em;
}
.sqGameBarEmpty { flex: 1; opacity: 0.7; }

/* ─── 10×10 grid (existing styles, kept) ──────────────────────────── */
.squaresWrap {
  width: 100%;
  overflow-x: auto;
  padding: 4px 0;
}
.squaresGrid {
  border-collapse: collapse;
  margin: 0 auto;
  font-family: 'EB Garamond';
}
.squaresGrid th {
  color: #d4a24e;
  font-weight: bold;
  padding: 6px 8px;
  font-size: 16px;
  border: 1px solid #2d2a26;
}
.square {
  width: 38px;
  height: 38px;
  text-align: center;
  vertical-align: middle;
  border: 1px solid #2d2a26;
  font-size: 13px;
  cursor: default;
  user-select: none;
}
.square.open { background-color: #16382a; color: #efeae2; }
.square.taken { background-color: #4a2c20; color: #efeae2; }
.square.taken.mine { background-color: #d4a24e; color: #0e1116; font-weight: bold; }
/* Center cell — house / TXL holders. Distinct fill + bold "TXL" label so
   it reads as "you can't buy this one, it pays the holder pool". */
.square.house {
  background: linear-gradient(135deg, #5b3a1a, #8a6328);
  color: #ffe7a1;
  border-color: rgba(245, 196, 81, 0.55);
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.06);
}
.houseLabel {
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.04em;
}
.ownerInitial { font-size: 11px; }

/* ─── Mobile ─────────────────────────────────────────────────────────── */
@media (max-width: 480px) {
  .square { width: 30px; height: 30px; font-size: 11px; }
}
</style>
