<script>
// Super-Bowl-Squares UI.
// Reads grid state from contract storage via tzkt; writes via wallet.
//
// Two-mode component:
//   • view = 'landing' — lobby/intro: hero, status, rules, CTAs.
//                        Default state when the user opens Squares.
//   • view = 'play'    — the 10×10 grid + buy controls.
//
// Phases (must match smart_contract_squares_v2.py):
//   0 = SELLING
//   1 = LOCKED
//   2 = AXES_SET
//   3 = COMPLETE

import { getContractStorage } from '../services/tzkt'
import {
  ADMIN_ADDRESS,
  BLOCKCHAIN_ENABLED,
  SQUARES_CONTRACT_ADDRESS,
  SQUARES_GAME_INFO,
} from '../constants'

const PHASE_LABELS = {
  0: 'Sales open',
  1: 'Sales closed — awaiting axis randomization',
  2: 'In play',
  3: 'Game complete',
}
const PHASE_TONES = {
  0: 'phaseOpen',
  1: 'phaseLocked',
  2: 'phaseLive',
  3: 'phaseDone',
}

export default {
  name: 'squaresGame',
  props: ['socket', 'wallet', 'tezos'],
  data() {
    return {
      info: SQUARES_GAME_INFO,
      currentGameId: 0,
      activeGameId: 0,
      game: null,
      walletAddress: '',
      pollInterval: null,
      blockchainStatus: 'idle',
      selectedSquare: null,
      buyCount: 1,
      view: 'landing', // 'landing' | 'play'
      showRules: false,
      myAddress: '',
      // Create-game form. Anyone can start a new pool; admin still
      // owns scoring (reportQuarter) and randomization (setAxes).
      newGameName: '',
      newGameTicketTez: 1.0,
      showCreateForm: false,
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
    phaseTone() {
      if (!this.game) return 'phaseNone'
      return PHASE_TONES[this.game.phase] || 'phaseNone'
    },
    canBuy() {
      return this.game && Number(this.game.phase) === 0
    },
    sold() {
      return this.game ? Number(this.game.sold) : 0
    },
    soldPct() {
      return Math.max(0, Math.min(100, this.sold))
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
    canPlay() {
      // The Play CTA is meaningful when there's a loaded game. The grid
      // itself is read-only after phase 0; users can still browse it.
      return !!this.game
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
        // Landing always reflects the most-recently-created game. The
        // past-games picker is gone, so pinning activeGameId would
        // silently strand the lobby on game #0 once newer games are
        // created. Recompute every refresh — cheap, and createGame()
        // auto-shows the new game without any extra wiring.
        const targetId = Math.max(0, this.currentGameId - 1)
        this.activeGameId = targetId
        this.game = storage.games?.[targetId] || null
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
    setView(v) {
      this.view = v
      if (v === 'landing') this.selectedSquare = null
    },
    selectSquare(idx) {
      if (!this.canBuy) return
      if (this.game?.squares?.[idx]) return
      this.selectedSquare = idx
    },
    selectGameId(id) {
      this.activeGameId = Number(id)
      this.refreshState()
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
      if (this.showCreateForm && !this.newGameName) {
        this.newGameName = `Squares #${this.currentGameId}`
      }
    },
    // Anyone can spin up a new Squares pool. The contract gates scoring
    // (reportQuarter) and randomization (setAxes) to admin, so the only
    // trust the creator earns is "I named the pool".
    async createGame() {
      const activeAccount = await this.wallet.client.getActiveAccount()
      if (!activeAccount) return
      const ticketTez = Math.max(0.001, Number(this.newGameTicketTez) || 1)
      const ticketMutez = Math.round(ticketTez * 1_000_000)
      const holderFeeMutez = 50_000 // 0.05 ꜩ — matches AD / Plinko convention
      // 15/15/15/55 is the standard Super-Bowl-Squares split. Sum is
      // validated on-chain to equal 100.
      const quarterWeights = { 0: 15, 1: 15, 2: 15, 3: 55 }
      const name = (this.newGameName || `Squares #${this.currentGameId}`).slice(0, 64)
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
        await this.refreshState()
      } catch (err) {
        console.error('createGame failed:', err)
        this.blockchainStatus = 'createGame failed — see console'
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
        const op = await contract.methodsObject.lockSales(this.activeGameId).send()
        await op.confirmation()
        this.blockchainStatus = 'Sales locked.'
        await this.refreshState()
      } catch (err) {
        console.error('lockSales failed:', err)
        this.blockchainStatus = 'lockSales failed — check contract entrypoint name'
      }
    },
    isMine(owner) {
      if (!owner) return false
      if (this.myAddress) return owner === this.myAddress
      // Fallback for sessions where myAddress hasn't loaded yet.
      return this.walletAddress?.endsWith(owner.slice(-4))
    },
    toggleRules() {
      this.showRules = !this.showRules
    },
  },
}
</script>

<template>
  <div class="gameManagement squaresRoot">
    <!-- ───── Landing / lobby view ───────────────────────────────────── -->
    <template v-if="view === 'landing'">
      <div class="sqHero">
        <div class="sqHeroBrand">
          <div class="sqHeroEyebrow">SUPER · BOWL · SQUARES</div>
          <div class="sqHeroTitle">10 × 10. Quarter payouts.</div>
          <div class="sqHeroSub">
            Pick any open square. When the digits on its row + column match
            the score's last digits at the end of a quarter, you take that
            quarter's share of the pot.
          </div>
        </div>

        <div class="sqHeroBoard" aria-hidden="true">
          <!-- Decorative mini-grid: visual hook only -->
          <div class="sqMini">
            <div
              v-for="i in 100"
              :key="i"
              :class="['sqMiniCell', i % 11 === 0 ? 'sqMiniHot' : '']"
            ></div>
          </div>
        </div>
      </div>

      <!-- ESPN scoreboard for the active grid (only when the grid name
           carries an ESPN:<id> tag and the API has returned data). -->
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

      <!-- Game selector / status pills -->
      <div class="sqStatusRow">
        <div :class="['sqPill', phaseTone]">
          <div class="sqPillLabel">Phase</div>
          <div class="sqPillValue">{{ phaseLabel }}</div>
        </div>
        <div class="sqPill">
          <div class="sqPillLabel">Game</div>
          <div class="sqPillValue">#{{ activeGameId }}</div>
        </div>
        <div class="sqPill">
          <div class="sqPillLabel">Pot</div>
          <div class="sqPillValue">{{ potTez }} ꜩ</div>
        </div>
        <div class="sqPill">
          <div class="sqPillLabel">Sold</div>
          <div class="sqPillValue">{{ sold }} / 100</div>
          <div class="sqPillBar">
            <div class="sqPillBarFill" :style="{ width: soldPct + '%' }"></div>
          </div>
        </div>
        <div class="sqPill">
          <div class="sqPillLabel">Ticket</div>
          <div class="sqPillValue">{{ ticketPriceTez }} ꜩ</div>
          <div class="sqPillFootnote">+ {{ feePriceTez }} ꜩ fee</div>
        </div>
      </div>


      <!-- Primary CTAs -->
      <div class="rowFlex sqPrimaryRow">
        <div
          :class="['actionButton', 'sqPrimary', !canPlay ? 'sqPrimaryDisabled' : '']"
          @click="canPlay && setView('play')"
        >
          {{ canBuy ? 'Pick a square' : (canPlay ? 'View board' : 'No game loaded') }}
        </div>
        <div class="actionButton" @click="claimAll">Claim winnings</div>
        <div class="actionButton" @click="refreshState">Refresh</div>
        <div class="actionButtonHelp" @click="toggleRules">
          {{ showRules ? 'Hide rules' : 'How it works' }}
        </div>
      </div>

      <!-- Quick buy: N random squares (lobby) -->
      <div v-if="canBuy" class="sqQuickBuy">
        <div class="sqQuickBuyLabel">Buy random squares</div>
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

      <!-- Start a new game — open to any user. -->
      <div class="sqCreatePanel">
        <div class="rowFlex">
          <div class="actionButton sqCreateToggle" @click="toggleCreateForm">
            {{ showCreateForm ? 'Cancel' : 'Start a new game' }}
          </div>
        </div>
        <div v-if="showCreateForm" class="sqCreateForm">
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
            <span class="sqCreateLabel">Ticket price (ꜩ)</span>
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
          </div>
          <div class="rowFlex">
            <div
              class="actionButton sqPrimary"
              @click="createGame"
            >
              Start game — {{ Number(newGameTicketTez).toFixed(3) }} ꜩ / square
            </div>
          </div>
        </div>
      </div>

      <!-- Admin actions — score reporting + sales lock stay restricted. -->
      <div v-if="isAdmin" class="sqAdminPanel">
        <div class="sqAdminLabel">Admin</div>
        <div class="rowFlex">
          <div class="actionButton" @click="lockSales">Lock sales</div>
        </div>
      </div>

      <!-- Rules drawer -->
      <div v-if="showRules" class="sqRules">
        <ol>
          <li v-for="(line, i) in info" :key="i">{{ line }}</li>
        </ol>
      </div>

      <div class="gameInfo sqStatusLine">{{ blockchainStatus }}</div>
    </template>

    <!-- ───── Play view: the 10×10 grid + buy controls ───────────────── -->
    <template v-else>
      <div class="rowFlex sqPlayHeader">
        <div class="actionButton sqBackBtn" @click="setView('landing')">‹ Lobby</div>
        <div class="gameInfo">Game #{{ activeGameId }} — {{ phaseLabel }}</div>
        <div class="actionButton" @click="refreshState">Refresh</div>
      </div>

      <div v-if="!game" class="gameInfo">No game loaded yet. Admin needs to create one.</div>

      <template v-else>
        <div class="rowFlex">
          <div class="txlRank">Sold: {{ sold }} / 100</div>
          <div class="txlRank">Pot: {{ potTez }} ꜩ</div>
          <div class="txlRank">Ticket: {{ ticketPriceTez }} ꜩ + {{ feePriceTez }} ꜩ fee</div>
        </div>

        <div class="squaresWrap">
          <table class="squaresGrid">
            <thead>
              <tr>
                <th></th>
                <th v-for="c in 10" :key="c">
                  {{ game.axesAssigned ? game.axisAway?.[c - 1] : '?' }}
                </th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(row, r) in grid" :key="r">
                <th>{{ game.axesAssigned ? game.axisHome?.[r] : '?' }}</th>
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

        <div class="rowFlex">
          <div
            :class="['actionButton', 'sqPrimary', !canBuy || selectedSquare == null ? 'sqPrimaryDisabled' : '']"
            @click="buySelected"
          >
            {{ selectedSquare == null ? 'Pick a square' : `Buy square ${selectedSquare}` }}
          </div>
          <div class="actionButton" @click="claimAll">Claim winnings</div>
          <div class="actionButton" @click="setView('landing')">Back to lobby</div>
        </div>

        <!-- Quick buy: N random squares (play view) -->
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

        <div class="gameInfo sqStatusLine">{{ blockchainStatus }}</div>
      </template>
    </template>
  </div>
</template>

<style scoped>
/* ─── Layout root ─────────────────────────────────────────────────────── */
.squaresRoot {
  font-family: 'EB Garamond';
  color: #efeae2;
}

/* ─── Hero ───────────────────────────────────────────────────────────── */
.sqHero {
  display: flex;
  flex-direction: row;
  gap: 18px;
  align-items: stretch;
  padding: 16px 14px;
  margin: 8px 4px 14px;
  border-radius: 14px;
  background:
    radial-gradient(ellipse at 80% 20%, rgba(212, 162, 78, 0.18) 0%, transparent 60%),
    linear-gradient(135deg, #0e3b22 0%, #07291a 70%);
  box-shadow:
    inset 0 0 0 1px rgba(255, 255, 255, 0.06),
    0 8px 22px rgba(0, 0, 0, 0.45);
}
.sqHeroBrand { flex: 1.4; min-width: 0; }
.sqHeroBoard {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}
.sqHeroEyebrow {
  font-size: 10px;
  letter-spacing: 4px;
  color: rgba(245, 196, 81, 0.75);
  font-weight: 700;
  margin-bottom: 6px;
}
.sqHeroTitle {
  font-size: clamp(20px, 4.5vw, 30px);
  line-height: 1.1;
  font-weight: 700;
  color: #fff;
  margin-bottom: 8px;
}
.sqHeroSub {
  font-size: 13px;
  color: rgba(255, 255, 255, 0.78);
  line-height: 1.4;
}
/* Decorative mini-grid */
.sqMini {
  display: grid;
  grid-template-columns: repeat(10, 1fr);
  gap: 2px;
  width: 100%;
  max-width: 180px;
  aspect-ratio: 1 / 1;
  padding: 6px;
  border-radius: 8px;
  background: rgba(0, 0, 0, 0.25);
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.06);
}
.sqMiniCell {
  background: rgba(22, 56, 42, 0.85);
  border-radius: 1px;
}
.sqMiniHot {
  background: linear-gradient(135deg, #f5c451, #d4a24e);
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

/* ─── Status pills ───────────────────────────────────────────────────── */
.sqStatusRow {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin: 0 4px 12px;
}
.sqPill {
  flex: 1 1 110px;
  min-width: 110px;
  padding: 8px 10px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.08);
}
.sqPillLabel {
  font-size: 9px;
  letter-spacing: 2px;
  text-transform: uppercase;
  color: rgba(255, 255, 255, 0.55);
}
.sqPillValue {
  font-size: 16px;
  font-weight: 700;
  color: #fff;
  margin-top: 2px;
  word-break: break-word;
}
.sqPillFootnote {
  font-size: 10px;
  color: rgba(255, 255, 255, 0.55);
  margin-top: 2px;
}
.sqPillBar {
  margin-top: 6px;
  height: 4px;
  border-radius: 2px;
  background: rgba(0, 0, 0, 0.35);
  overflow: hidden;
}
.sqPillBarFill {
  height: 100%;
  background: linear-gradient(90deg, #f5c451, #d4a24e);
  transition: width 0.4s ease;
}
.phaseOpen   { border-color: rgba(118, 196, 138, 0.5); }
.phaseLocked { border-color: rgba(212, 162, 78, 0.5); }
.phaseLive   { border-color: rgba(245, 196, 81, 0.6); }
.phaseDone   { border-color: rgba(196, 82, 79, 0.5); }
.phaseNone   { border-color: rgba(255, 255, 255, 0.08); }

/* ─── Past-games picker ──────────────────────────────────────────────── */
.sqGamesLabel {
  flex: 0 0 auto;
  align-self: center;
  font-size: 12px;
  color: rgba(255, 255, 255, 0.7);
}
.sqGameBtnActive {
  border-color: #f5c451 !important;
  color: #f5c451 !important;
}

/* ─── Primary CTAs ───────────────────────────────────────────────────── */
.sqPrimaryRow { margin-top: 4px; }
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
.sqPlayHeader { margin: 4px 0 8px; }
.sqBackBtn { flex: 0 0 auto; min-width: 90px; }

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
  .sqHero { flex-direction: column; gap: 12px; }
  .sqHeroBoard { justify-content: flex-start; }
  .sqMini { max-width: 140px; }
  .square { width: 26px; height: 26px; font-size: 9px; }
}
</style>
