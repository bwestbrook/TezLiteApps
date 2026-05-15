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
    id: '401871337',
    awayAbbr: 'CLE', homeAbbr: 'DET',
    awayName: 'Cleveland Cavaliers', homeName: 'Detroit Pistons',
    awayLogo: 'https://a.espncdn.com/i/teamlogos/nba/500/cle.png',
    homeLogo: 'https://a.espncdn.com/i/teamlogos/nba/500/det.png',
    statusDetail: 'Final/OT',
  },
  {
    id: '401871336',
    awayAbbr: 'DET', homeAbbr: 'CLE',
    awayName: 'Detroit Pistons', homeName: 'Cleveland Cavaliers',
    awayLogo: 'https://a.espncdn.com/i/teamlogos/nba/500/det.png',
    homeLogo: 'https://a.espncdn.com/i/teamlogos/nba/500/cle.png',
    statusDetail: 'Final',
  },
  // More real 2025 playoff games — a fuller lobby to pick from while
  // testing, and contrast for the "Cavs Vs." labeling.
  {
    id: '401768057',
    awayAbbr: 'LAL', homeAbbr: 'MIN',
    awayName: 'Los Angeles Lakers', homeName: 'Minnesota Timberwolves',
    awayLogo: 'https://a.espncdn.com/i/teamlogos/nba/500/lal.png',
    homeLogo: 'https://a.espncdn.com/i/teamlogos/nba/500/min.png',
    statusDetail: 'Final',
  },
  {
    id: '401768043',
    awayAbbr: 'NY', homeAbbr: 'DET',
    awayName: 'New York Knicks', homeName: 'Detroit Pistons',
    awayLogo: 'https://a.espncdn.com/i/teamlogos/nba/500/ny.png',
    homeLogo: 'https://a.espncdn.com/i/teamlogos/nba/500/det.png',
    statusDetail: 'Final',
  },
  {
    id: '401768031',
    awayAbbr: 'BOS', homeAbbr: 'ORL',
    awayName: 'Boston Celtics', homeName: 'Orlando Magic',
    awayLogo: 'https://a.espncdn.com/i/teamlogos/nba/500/bos.png',
    homeLogo: 'https://a.espncdn.com/i/teamlogos/nba/500/orl.png',
    statusDetail: 'Final',
  },
  {
    id: '401768049',
    awayAbbr: 'IND', homeAbbr: 'MIL',
    awayName: 'Indiana Pacers', homeName: 'Milwaukee Bucks',
    awayLogo: 'https://a.espncdn.com/i/teamlogos/nba/500/ind.png',
    homeLogo: 'https://a.espncdn.com/i/teamlogos/nba/500/mil.png',
    statusDetail: 'Final',
  },
]

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
      blockchainStatus: 'idle',
      selectedSquare: null,
      buyCount: 1,
      myAddress: '',
      // Create-game form. Anyone can start a new pool; admin still
      // owns scoring (reportQuarter) and randomization (setAxes).
      newGameName: '',
      newGameTicketTez: 1.0,
      showCreateForm: false,
      // ─── NBA game picker for createGame ─────────────────────────
      // Lets the creator bind a pool to a real ESPN event. The chosen
      // id is encoded into the on-chain game name as "ESPN:<id>"; the
      // oracle (scripts/oracle_worker.py) parses that tag to auto-report
      // quarter scores. Convention lives in scripts/sports_api.py.
      espnDate: new Date().toISOString().slice(0, 10), // YYYY-MM-DD
      espnGames: [],
      espnLoading: false,
      selectedEspnId: null,
      // ─── ESPN-derived live scoreboard for the active grid ───────
      // Populated by refreshSports() when the active game.name carries
      // an "ESPN:<event_id>" tag. Stays null otherwise.
      sports: null,
      sportsLastFetched: 0,
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
      // Indices (0..99) that no one has bought yet.
      const owned = this.game?.squares || {}
      const open = []
      for (let i = 0; i < 100; i++) {
        if (!owned[i]) open.push(i)
      }
      return open
    },
    maxBuy() {
      // Cannot exceed remaining open squares; hard cap at 100 by definition.
      return Math.max(0, Math.min(100, 100 - this.sold))
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
    // Match the Python-side parse_espn_id() regex. Pulls the ESPN event
    // id out of a grid name like "ESPN:401871337  ·  Cavs vs Pistons G6".
    espnEventId() {
      const m = /\bESPN:(\d{6,})\b/.exec(this.game?.name || '')
      return m ? m[1] : null
    },
    // Human label for the grid name with the ESPN tag stripped. Falls
    // back to the raw name when there's no tag.
    gridDisplayName() {
      const name = this.game?.name || ''
      return name.replace(/\bESPN:\d{6,}\b/, '').replace(/^\s*[·•|\-—]\s*/, '').trim() || name
    },
    sportsStatusLabel() {
      if (!this.sports) return ''
      const t = this.sports.statusType || {}
      // ESPN's `detail` is nicely human ('Final/OT', 'End 3rd Quarter', etc).
      return t.detail || t.shortDetail || t.description || ''
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
  },
  created() {
    this.socket.on('newWallet', (w) => {
      this.walletAddress = w
    })
    this.refreshState()
    if (BLOCKCHAIN_ENABLED) {
      this.pollInterval = setInterval(() => this.refreshState(), 8000)
    }
  },
  beforeUnmount() {
    if (this.pollInterval) clearInterval(this.pollInterval)
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
        // Refresh ESPN scoreboard for the active grid, if any.
        this.refreshSports()
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
      this.selectedSquare = null
      this.refreshSports()
    },
    // Short label for a game-selector button: the matchup (ESPN tag
    // stripped) when the pool is linked to an NBA game, else "Game #id".
    gameButtonLabel(id) {
      const name = this.allGames?.[id]?.name || ''
      const matchup = name
        .replace(/\bESPN:\d{6,}\b/, '')
        .replace(/^[\s\-–—·|]+/, '')
        .trim()
      if (!matchup) return `Game #${id}`
      // Cavs pools read as "Cavs Vs. <opponent>" — matches the NBA picker.
      const m = /^(\w+)\s*@\s*(\w+)$/.exec(matchup)
      if (m && m[1] === 'CLE') return `#${id} · Cavs Vs. ${m[2]}`
      if (m && m[2] === 'CLE') return `#${id} · Cavs Vs. ${m[1]}`
      return `#${id} · ${matchup}`
    },
    async refreshSports() {
      // Read the ESPN event id from the active grid's name. If there
      // isn't one, clear any stale scoreboard data and bail.
      const eid = this.espnEventId
      if (!eid) {
        if (this.sports) this.sports = null
        return
      }
      // Cap fetch frequency at ~12/min so the chain poll doesn't drag
      // ESPN with it. Storage refresh runs every 8s; gating here at 5s
      // means we'll skip every other tick.
      const now = Date.now()
      if (now - this.sportsLastFetched < 5000) return
      this.sportsLastFetched = now
      try {
        const url = `https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event=${eid}`
        const res = await fetch(url, { headers: { Accept: 'application/json' } })
        if (!res.ok) return
        const json = await res.json()
        const header = json.header || {}
        const comp = (header.competitions || [])[0] || {}
        const competitors = comp.competitors || []
        const home = competitors.find((c) => c.homeAway === 'home') || competitors[0] || {}
        const away = competitors.find((c) => c.homeAway === 'away') || competitors[1] || {}
        const readLines = (c) =>
          (c.linescores || []).map((ls) => Number(ls.value ?? ls.displayValue ?? 0))
        this.sports = {
          eventId: eid,
          shortName: header.shortName || header.name || '',
          statusType: (comp.status || header.status || {}).type || {},
          home: {
            abbr: home.team?.abbreviation || '?',
            name: home.team?.displayName || home.team?.name || '?',
            score: Number(home.score || 0),
            quarters: readLines(home),
            logo: home.team?.logo || home.team?.logos?.[0]?.href || '',
          },
          away: {
            abbr: away.team?.abbreviation || '?',
            name: away.team?.displayName || away.team?.name || '?',
            score: Number(away.score || 0),
            quarters: readLines(away),
            logo: away.team?.logo || away.team?.logos?.[0]?.href || '',
          },
        }
      } catch (e) {
        // Best-effort. Next tick retries; don't spam the console.
      }
    },
    selectSquare(idx) {
      if (!this.canBuy) return
      if (this.game?.squares?.[idx]) return
      this.selectedSquare = idx
    },
    async buySelected() {
      if (this.selectedSquare == null) return
      const activeAccount = await this.wallet.client.getActiveAccount()
      if (!activeAccount) return
      this.tezos.setWalletProvider(this.wallet)
      this.blockchainStatus = `Buying square ${this.selectedSquare}...`
      const total = Number(this.game.ticketPrice) + Number(this.game.holderFee)
      try {
        const contract = await this.tezos.wallet.at(SQUARES_CONTRACT_ADDRESS)
        const op = await contract.methodsObject
          .buySquare({ gameId: this.activeGameId, squareIdx: this.selectedSquare })
          .send({ amount: total / 1_000_000 })
        this.blockchainStatus = `Submitted (${op.opHash}) — waiting for confirmation`
        await op.confirmation()
        this.blockchainStatus = `Bought square ${this.selectedSquare}.`
        this.selectedSquare = null
        await this.refreshState()
      } catch (err) {
        console.error('buySquare failed:', err)
        this.blockchainStatus = 'buy failed — see console'
      }
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
        this.selectedSquare = null
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
    // Fetch the NBA slate for `espnDate` from ESPN's open scoreboard API.
    // Same endpoint family scripts/sports_api.py uses on the oracle side.
    async fetchEspnGames() {
      this.espnLoading = true
      this.espnGames = []
      try {
        const ymd = this.espnDate.replace(/-/g, '')
        const url = `https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates=${ymd}`
        const res = await fetch(url, { headers: { Accept: 'application/json' } })
        if (!res.ok) return
        const json = await res.json()
        this.espnGames = (json.events || []).map((ev) => {
          const comp = (ev.competitions || [])[0] || {}
          const cs = comp.competitors || []
          const home = cs.find((c) => c.homeAway === 'home') || cs[0] || {}
          const away = cs.find((c) => c.homeAway === 'away') || cs[1] || {}
          const t = (ev.status || {}).type || {}
          return {
            id: String(ev.id),
            homeAbbr: home.team?.abbreviation || '?',
            awayAbbr: away.team?.abbreviation || '?',
            homeName: home.team?.displayName || home.team?.shortDisplayName || '?',
            awayName: away.team?.displayName || away.team?.shortDisplayName || '?',
            homeLogo: home.team?.logo || '',
            awayLogo: away.team?.logo || '',
            statusDetail: t.shortDetail || t.detail || t.description || '',
          }
        })
      } catch (e) {
        console.warn('ESPN scoreboard fetch failed:', e?.message)
      } finally {
        // Fall back to the Cavs test fixtures when the live slate is
        // empty (off-season date, fetch failure, etc.) so the picker is
        // never a dead end during testing.
        if (!this.espnGames.length) {
          this.espnGames = TEST_NBA_GAMES.slice()
        }
        this.espnLoading = false
      }
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
      if (this.selectedEspnId === g.id) {
        // Re-click = unbind. Strip the tag, keep any trailing label.
        this.selectedEspnId = null
        this.newGameName =
          this.newGameName.replace(/\bESPN:\d{6,}\b\s*·?\s*/, '').trim() ||
          `Squares #${this.currentGameId}`
        return
      }
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
      const ticketTez = Math.max(0.001, Number(this.newGameTicketTez) || 1)
      const ticketMutez = Math.round(ticketTez * 1_000_000)
      const holderFeeMutez = 50_000 // 0.05 ꜩ — matches AD / Plinko convention
      // 15/15/15/55 is the standard Super-Bowl-Squares split. Sum is
      // validated on-chain to equal 100.
      const quarterWeights = { 0: 15, 1: 15, 2: 15, 3: 55 }
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
      } catch (err) {
        console.error('createGame failed:', err)
        this.blockchainStatus = 'createGame failed — see console'
      }
    },
    // A "card" is another Squares pool bound to the SAME NBA game as the
    // one currently selected: it reuses that pool's ESPN-tagged name so the
    // oracle reports identical quarter scores. The creator only picks the
    // per-square price; everything else matches createGame().
    async createCard() {
      if (!this.game) {
        this.blockchainStatus = 'Select a game first.'
        return
      }
      const activeAccount = await this.wallet.client.getActiveAccount()
      if (!activeAccount) return
      const ticketTez = Math.max(0.001, Number(this.newGameTicketTez) || 1)
      const ticketMutez = Math.round(ticketTez * 1_000_000)
      const holderFeeMutez = 50_000 // 0.05 ꜩ — matches createGame()
      const quarterWeights = { 0: 15, 1: 15, 2: 15, 3: 55 }
      // Same ASCII-only guard as createGame() — Michelson rejects unicode.
      // eslint-disable-next-line no-control-regex
      const name = (this.game.name || `Squares #${this.currentGameId}`)
        .replace(/[^\x20-\x7E]/g, '')
        .trim()
        .slice(0, 64)
      this.tezos.setWalletProvider(this.wallet)
      this.blockchainStatus = `Creating a new card for "${name}"...`
      try {
        const contract = await this.tezos.wallet.at(SQUARES_CONTRACT_ADDRESS)
        const op = await contract.methodsObject
          .createGame({
            name,
            ticketPrice: ticketMutez,
            holderFee: holderFeeMutez,
            quarterWeights,
          })
          .send()
        this.blockchainStatus = `Submitted (${op.opHash}) — waiting for confirmation`
        await op.confirmation()
        this.blockchainStatus = `New card created for "${name}".`
        this.showCreateForm = false
        // Jump the selector bar to the just-created card.
        this.gameSelected = false
        await this.refreshState()
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
    isMine(owner) {
      if (!owner) return false
      if (this.myAddress) return owner === this.myAddress
      // Fallback for sessions where myAddress hasn't loaded yet.
      return this.walletAddress?.endsWith(owner.slice(-4))
    },
  },
}
</script>

<template>
  <div class="gameManagement squaresRoot">
    <!-- Available games — one button per Squares pool on chain. Click to
         load it. Newest first. Replaces the old back/title/refresh bar;
         app-level nav lives in the top carousel now. -->
    <div class="rowFlex sqGameBar">
      <div
        v-for="id in gameIds"
        :key="id"
        :class="['actionButton', 'sqGameBtn', activeGameId === id ? 'sqGameBtn--active' : '']"
        @click="selectGameId(id)"
      >
        {{ gameButtonLabel(id) }}
      </div>
      <div v-if="!gameIds.length" class="gameInfo sqGameBarEmpty">
        No games yet — start one below.
      </div>
    </div>

    <!-- ESPN scoreboard for the active grid (only when the grid name
         carries an ESPN:<id> tag and refreshSports() has data). -->
    <div v-if="sports" class="sqScoreboard">
      <div class="sqScoreSide">
        <img
          v-if="sports.away.logo"
          class="sqScoreLogo"
          :src="sports.away.logo"
          :alt="sports.away.name"
        />
        <div class="sqScoreText">
          <div class="sqScoreTeam">{{ sports.away.name }}</div>
          <div class="sqScoreAbbr">{{ sports.away.abbr }}</div>
        </div>
        <div class="sqScorePts">{{ sports.away.score }}</div>
      </div>
      <div class="sqScoreMid">
        <div class="sqScoreStatus">{{ sportsStatusLabel || '—' }}</div>
        <div class="sqScoreQuarters" v-if="sports.home.quarters.length">
          <span
            v-for="(q, idx) in sports.home.quarters"
            :key="`hq-${idx}`"
            class="sqScoreQ"
          >Q{{ idx + 1 }}: {{ sports.away.quarters[idx] ?? 0 }} – {{ q }}</span>
        </div>
        <div v-if="gridDisplayName" class="sqScoreSubtitle">{{ gridDisplayName }}</div>
      </div>
      <div class="sqScoreSide sqScoreSide--right">
        <div class="sqScorePts">{{ sports.home.score }}</div>
        <div class="sqScoreText sqScoreText--right">
          <div class="sqScoreTeam">{{ sports.home.name }}</div>
          <div class="sqScoreAbbr">{{ sports.home.abbr }}</div>
        </div>
        <img
          v-if="sports.home.logo"
          class="sqScoreLogo"
          :src="sports.home.logo"
          :alt="sports.home.name"
        />
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

    <!-- The 10×10 board always renders — blank (numbered, no owners)
         when no game is loaded, live once one is. -->
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
                cell.owner ? 'taken' : 'open',
                selectedSquare === cell.idx ? 'selected' : '',
                isMine(cell.owner) ? 'mine' : '',
              ]"
              @click="selectSquare(cell.idx)"
            >
              <span v-if="cell.owner" class="ownerInitial">
                {{ cell.owner.slice(-3) }}
              </span>
              <span v-else>{{ cell.idx }}</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Buy + admin controls only make sense once a game is loaded. -->
    <template v-if="game">
      <div class="rowFlex">
        <div
          :class="['actionButton', 'sqPrimary', !canBuy || selectedSquare == null ? 'sqPrimaryDisabled' : '']"
          @click="buySelected"
        >
          {{ selectedSquare == null ? 'Pick a square' : `Buy square ${selectedSquare}` }}
        </div>
        <div class="actionButton" @click="claimAll">Claim winnings</div>
      </div>

      <!-- Quick buy: N random squares -->
      <div v-if="canBuy" class="sqQuickBuy">
        <div class="sqQuickBuyLabel">Or buy random squares</div>
        <div class="rowFlex sqQuickBuyRow">
          <input
            class="sqBuyInput"
            type="number"
            min="1"
            :max="maxBuy"
            v-model.number="buyCount"
            :disabled="maxBuy === 0"
          />
          <div class="actionButton sqMaxBtn" @click="setBuyMax">Max ({{ maxBuy }})</div>
          <div
            :class="['actionButton', 'sqPrimary', maxBuy === 0 ? 'sqPrimaryDisabled' : '']"
            @click="maxBuy > 0 && buyRandomMany()"
          >
            Buy {{ clampedBuyCount }} OK — {{ buyTotalTez }} ꜩ
          </div>
        </div>
        <div class="sqQuickBuyHint">
          Squares are picked at random from the open pool. Max 100 per game.
        </div>
      </div>

      <!-- Admin actions — score reporting + sales lock stay restricted. -->
      <div v-if="isAdmin" class="sqAdminPanel">
        <div class="sqAdminLabel">Admin</div>
        <div class="rowFlex">
          <div class="actionButton" @click="lockSales">Lock sales</div>
        </div>
      </div>
    </template>

    <!-- Start a new card (for the selected game) or — when nothing is
         selected — a brand-new game. Open to any user, always reachable. -->
    <div class="sqCreatePanel">
      <div class="rowFlex">
        <div class="actionButton sqCreateToggle" @click="toggleCreateForm">
          {{ showCreateForm
              ? 'Cancel'
              : (game ? `Start a new card for ${gridDisplayName}` : 'Start a new game') }}
        </div>
      </div>

      <!-- A "card" is another pool bound to the SAME NBA game as the one
           currently selected — so it only needs a per-square price. -->
      <div v-if="showCreateForm && game" class="sqCreateForm">
        <div class="sqCreateField">
          <span class="sqCreateLabel">New card for</span>
          <div class="sqCreateHint">
            {{ gridDisplayName }} — same NBA game, a fresh 10×10 board.
          </div>
        </div>
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
        <div class="rowFlex">
          <div class="actionButton sqPrimary" @click="createCard">
            Create card — {{ Number(newGameTicketTez).toFixed(3) }} ꜩ / square
          </div>
        </div>
      </div>

      <!-- No game selected yet → full new-game flow: pick the NBA matchup. -->
      <div v-else-if="showCreateForm" class="sqCreateForm">
        <!-- NBA game picker. Binding to a real ESPN event writes an
             "ESPN:<id>" tag into the on-chain name, which the oracle
             reads to auto-report quarter scores. -->
        <div class="sqCreateField">
          <span class="sqCreateLabel">Pick an NBA game (required)</span>
          <div class="rowFlex sqEspnDateRow">
            <input
              type="date"
              v-model="espnDate"
              class="sqCreateInput sqEspnDate"
              @change="fetchEspnGames"
            />
            <div class="actionButton sqEspnRefresh" @click="fetchEspnGames">
              {{ espnLoading ? 'Loading…' : 'Refresh slate' }}
            </div>
          </div>
          <div v-if="espnLoading" class="sqCreateHint">Loading NBA slate…</div>
          <div v-else-if="!espnGames.length" class="sqCreateHint">
            No NBA games on {{ espnDate }}.
          </div>
          <div v-else class="sqEspnList">
            <div
              v-for="g in espnGames"
              :key="g.id"
              :class="['sqGameCard', selectedEspnId === g.id ? 'sqGameCard--active' : '']"
              @click="pickEspnGame(g)"
            >
              <div class="sqGameCardTop">
                <span class="sqGameTitle">{{ espnGameLabel(g) }}</span>
                <span class="sqGameStatus">{{ g.statusDetail }}</span>
              </div>
              <div class="sqGameTeam">
                <img v-if="g.awayLogo" :src="g.awayLogo" :alt="g.awayAbbr" class="sqGameLogo" />
                <span class="sqGameAbbr">{{ g.awayAbbr }}</span>
                <span class="sqGameTeamName">{{ g.awayName }}</span>
                <span class="sqGameSide">AWAY</span>
              </div>
              <div class="sqGameTeam">
                <img v-if="g.homeLogo" :src="g.homeLogo" :alt="g.homeAbbr" class="sqGameLogo" />
                <span class="sqGameAbbr">{{ g.homeAbbr }}</span>
                <span class="sqGameTeamName">{{ g.homeName }}</span>
                <span class="sqGameSide">HOME</span>
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
          Defaults: 0.05 ꜩ holder fee, 15/15/15/55 quarter split. Sales
          auto-lock at 100 squares; admin reports the scores.
          <template v-if="selectedEspnId">
            Linked to ESPN game {{ selectedEspnId }} — the oracle will
            auto-report quarter scores.
          </template>
          <template v-else>
            Select a game above to enable "Start game".
          </template>
        </div>
        <div class="rowFlex">
          <div
            :class="['actionButton', 'sqPrimary', canCreateGame ? '' : 'sqPrimaryDisabled']"
            @click="createGame"
          >
            <template v-if="canCreateGame">
              Start game — {{ Number(newGameTicketTez).toFixed(3) }} ꜩ / square
            </template>
            <template v-else>
              Pick an NBA game first
            </template>
          </div>
        </div>
      </div>
    </div>

    <div class="gameInfo sqStatusLine">{{ blockchainStatus }}</div>
  </div>
</template>

<style scoped>
/* ─── Layout root ─────────────────────────────────────────────────────── */
.squaresRoot {
  font-family: 'EB Garamond';
  color: #efeae2;
}

/* ─── ESPN scoreboard ────────────────────────────────────────────────
   Renders above the status-pill row when the active grid name carries
   an `ESPN:<event_id>` tag and refreshSports() has data. Mirrors the
   ESPN classic side-by-side scorebar: away team left, home right,
   status + per-quarter breakdown in the middle. */
.sqScoreboard {
  display: flex;
  align-items: stretch;
  gap: 10px;
  margin: 6px 4px 12px;
  padding: 12px 14px;
  border-radius: 10px;
  background:
    radial-gradient(ellipse at 50% 0%, rgba(245, 196, 81, 0.10) 0%, transparent 70%),
    linear-gradient(135deg, rgba(25, 8, 87, 0.65) 0%, rgba(7, 4, 30, 0.85) 100%);
  border: 1px solid rgba(245, 196, 81, 0.25);
  box-shadow:
    inset 0 0 0 1px rgba(255, 255, 255, 0.05),
    0 4px 12px rgba(0, 0, 0, 0.35);
}
.sqScoreSide {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}
.sqScoreSide--right { justify-content: flex-end; }
.sqScoreLogo {
  width: 36px;
  height: 36px;
  object-fit: contain;
  filter: drop-shadow(0 1px 2px rgba(0, 0, 0, 0.4));
}
.sqScoreText { min-width: 0; }
.sqScoreText--right { text-align: right; }
.sqScoreTeam {
  font-size: 13px;
  font-weight: 700;
  color: #fff;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 120px;
}
.sqScoreAbbr {
  font-size: 10px;
  letter-spacing: 2px;
  color: rgba(255, 255, 255, 0.55);
}
.sqScorePts {
  font-size: 28px;
  font-weight: 800;
  color: #f5c451;
  font-variant-numeric: tabular-nums;
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.5);
  min-width: 44px;
  text-align: center;
}
.sqScoreMid {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 4px;
  min-width: 0;
  text-align: center;
}
.sqScoreStatus {
  font-size: 11px;
  letter-spacing: 2px;
  font-weight: 700;
  color: rgba(245, 196, 81, 0.85);
  text-transform: uppercase;
}
.sqScoreQuarters {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 10px;
  justify-content: center;
  font-size: 11px;
  color: rgba(255, 255, 255, 0.75);
  font-variant-numeric: tabular-nums;
}
.sqScoreQ {
  white-space: nowrap;
  padding: 1px 6px;
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.05);
}
.sqScoreSubtitle {
  font-size: 11px;
  color: rgba(255, 255, 255, 0.55);
  font-style: italic;
}
@media (max-width: 480px) {
  .sqScoreboard { flex-direction: column; gap: 8px; padding: 10px; }
  .sqScoreSide,
  .sqScoreSide--right { justify-content: space-between; width: 100%; }
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
  margin: 12px 4px 4px;
}
.sqCreateToggle {
  flex: 0 0 auto;
}
.sqCreateForm {
  margin-top: 10px;
  padding: 12px 14px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.08);
}
.sqCreateField {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-bottom: 10px;
}
.sqCreateLabel {
  font-size: 10px;
  letter-spacing: 2px;
  text-transform: uppercase;
  color: rgba(255, 255, 255, 0.55);
}
.sqCreateInput {
  padding: 8px 10px;
  font-family: 'EB Garamond';
  font-size: 14px;
  background: rgba(0, 0, 0, 0.35);
  color: #efeae2;
  border: 1px solid rgba(245, 196, 81, 0.25);
  border-radius: 6px;
}
.sqCreateHint {
  font-size: 11px;
  color: rgba(255, 255, 255, 0.55);
  font-style: italic;
  margin-bottom: 8px;
}

/* ─── NBA game picker (inside the create-game form) ──────────────────── */
.sqEspnDateRow {
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}
.sqEspnDate { flex: 0 0 auto; }
.sqEspnRefresh { flex: 0 0 auto; }
/* ─── DraftKings/FanDuel-style game lobby ────────────────────────────
   Each NBA matchup is a tappable card: matchup title + status pill up
   top, then an away row and a home row with logo, abbr, and full name. */
.sqEspnList {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 340px;
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
.sqGameTitle {
  font-weight: 700;
  font-size: 13px;
  color: #f5c451;
  letter-spacing: 0.01em;
}
.sqGameStatus {
  font-size: 10px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: rgba(255, 255, 255, 0.6);
  background: rgba(0, 0, 0, 0.35);
  border: 1px solid rgba(255, 255, 255, 0.10);
  border-radius: 999px;
  padding: 2px 8px;
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
.sqGamePicked {
  font-size: 11px;
  font-weight: 700;
  color: #f5c451;
  text-align: center;
  padding-top: 2px;
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
  font-size: 12px;
  color: #d4a24e;
  font-style: italic;
}

/* ─── Play view header ───────────────────────────────────────────────── */
/* ─── Game-selector bar ───────────────────────────────────────────── */
.sqGameBar {
  margin: 4px 0 8px;
  flex-wrap: nowrap;
  overflow-x: auto;
  gap: 6px;
  scrollbar-width: none;
  -ms-overflow-style: none;
}
.sqGameBar::-webkit-scrollbar { display: none; }
.sqGameBtn {
  flex: 0 0 auto;
  max-width: 220px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.sqGameBtn--active {
  border-color: #f5c451;
  box-shadow: 0 0 0 1px rgba(245, 196, 81, 0.55) inset;
  color: #f5c451;
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
  padding: 4px 6px;
  font-size: 13px;
  border: 1px solid #2d2a26;
}
.square {
  width: 32px;
  height: 32px;
  text-align: center;
  vertical-align: middle;
  border: 1px solid #2d2a26;
  font-size: 10px;
  cursor: pointer;
  user-select: none;
}
.square.open { background-color: #16382a; color: #efeae2; }
.square.taken { background-color: #4a2c20; color: #efeae2; cursor: not-allowed; }
.square.taken.mine { background-color: #d4a24e; color: #0e1116; font-weight: bold; }
.square.selected { outline: 2px solid #d4a24e; outline-offset: -2px; }
.ownerInitial { font-size: 9px; }

/* ─── Mobile ─────────────────────────────────────────────────────────── */
@media (max-width: 480px) {
  .square { width: 26px; height: 26px; font-size: 9px; }
}
</style>
