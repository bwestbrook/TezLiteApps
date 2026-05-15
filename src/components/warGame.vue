<script>
// Speed War — best-of-3 high-card showdown.
//
// Mirrors src/services/smart_contractWar.py exactly:
//
//   1. createGame(wager)    — player1 stakes wager + 0.1ꜩ fee
//   2. joinGame(gameId)     — player2 matches; gameStatus → 1 (awaiting deal)
//   3. (off-chain) oracle calls deal(gameId, cards1, cards2, seed)
//      cards1 / cards2 are 3-entry maps {0,1,2 → deck_idx}
//   4. Inline settlement: more round wins takes the pot; tied series refunds.
//
// Storage shape per game (sp.record): player1, player2, wager, cards1, cards2,
// p1Wins, p2Wins, gameStatus (0=open / 1=awaiting deal / 2=settled /
// 3=cancelled), winner, seed.
//
// Demo mode (no wallet, no contract) runs a random local 3-round draw so
// visitors can see the round-by-round 3D flip animation. 2-0 sweeps
// short-circuit before round 3 to play up the "speed" branding.

import { getContractStorage, isPlaceholderAddress } from '../services/tzkt'
import {
  BLOCKCHAIN_ENABLED,
  WAR_CONTRACT_ADDRESS,
  WAR_GAME_INFO,
} from '../constants'

// Contract constants (must match smart_contractWar.py).
const FEE_MUTEZ = 100_000          // 0.1 ꜩ holder fee per player
const MIN_WAGER_MUTEZ = 100_000    // 0.1 ꜩ
const MAX_WAGER_MUTEZ = 5_000_000  // 5 ꜩ
const BURN_ADDR = 'tz1burnburnburnburnburnburnburjAYjjX'

const SUIT_GLYPHS = ['♣', '♦', '♥', '♠']
const RANK_LABELS = { 11: 'J', 12: 'Q', 13: 'K', 14: 'A' }

function rankOf(deckIndex) {
  return Math.floor(deckIndex / 4) + 2
}
function suitOf(deckIndex) {
  return deckIndex % 4
}
function shortLabel(deckIndex) {
  if (deckIndex == null || deckIndex < 0) return ''
  const r = rankOf(deckIndex)
  const s = suitOf(deckIndex)
  return `${RANK_LABELS[r] || r}${SUIT_GLYPHS[s]}`
}
function suitColor(deckIndex) {
  const s = suitOf(deckIndex)
  return s === 1 || s === 2 ? 'red' : 'black'
}

// Phase labels keyed to contract's gameStatus values.
const PHASE_LABELS = {
  0: 'Open — waiting for opponent',
  1: 'Dealing — oracle in flight',
  2: 'Settled',
  3: 'Cancelled',
}

function pickSix() {
  // Six distinct deck indices — mirrors what the oracle daemon does
  // for an on-chain deal (one physical deck, no repeats). Returns
  // { you: [3 ints], opp: [3 ints] }.
  const deck = Array.from({ length: 52 }, (_, i) => i)
  for (let i = deck.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1))
    ;[deck[i], deck[j]] = [deck[j], deck[i]]
  }
  return { you: deck.slice(0, 3), opp: deck.slice(3, 6) }
}

// Round-by-round speed-war scoring. Returns { youWins, oppWins,
// roundOutcomes } where roundOutcomes[r] ∈ {'you','opp','wash'}.
// Caller picks the verdict via youWins vs oppWins.
function scoreRounds(youCards, oppCards) {
  let youWins = 0
  let oppWins = 0
  const roundOutcomes = []
  for (let r = 0; r < 3; r++) {
    const yr = rankOf(youCards[r])
    const or = rankOf(oppCards[r])
    if (yr > or) { youWins++; roundOutcomes.push('you') }
    else if (or > yr) { oppWins++; roundOutcomes.push('opp') }
    else { roundOutcomes.push('wash') }
  }
  return { youWins, oppWins, roundOutcomes }
}

export default {
  name: 'warGame',
  props: ['socket', 'wallet', 'tezos'],
  data() {
    return {
      info: WAR_GAME_INFO,
      walletAddress: '',
      currentGameId: 0,
      activeGameId: null,
      games: {},
      // Default 1 ꜩ wager — well within contract bounds (0.1 – 5 ꜩ).
      wagerMutez: 1_000_000,
      pollInterval: null,
      blockchainStatus: 'idle',
      // Land users straight on the table with the fake game already in
      // progress — they see the knight vs orc duel before reading copy.
      view: 'play',
      showRules: false,
      // ─── Demo / animation state (best-of-3) ──────────────────────────
      // Three cards per side. demoYouCards[r] / demoOppCards[r] are deck
      // indices; youRevealed[r] / oppRevealed[r] drive the per-round flip.
      demoYouCards: [null, null, null],
      demoOppCards: [null, null, null],
      youRevealed: [false, false, false],
      oppRevealed: [false, false, false],
      // Per-round outcomes ('you' | 'opp' | 'wash' | null) — used for the
      // running score badges and the per-round result glow.
      roundOutcomes: [null, null, null],
      // Running totals after the most recent revealed round.
      youWins: 0,
      oppWins: 0,
      demoVerdict: null, // 'win' | 'lose' | 'push'
      // Animation timers — collected so we can cancel them on unmount
      // (otherwise a half-finished deal can fire after navigation).
      demoTimeouts: [],
      // Auto-loop driver: re-deals demo cards on a cadence so the table
      // is never static. Disabled the moment a real game is active.
      demoLoopTimer: null,
      // Character lean — set briefly during reveal so the knight/orc
      // appear to crane forward as their card flips.
      knightLean: false,
      orcLean: false,
      // Lazy-built lookup of card-face image URLs (built in created()).
      deck: [],
    }
  },
  computed: {
    game() {
      return this.activeGameId == null ? null : this.games[this.activeGameId]
    },
    inRealGame() {
      return !!this.game
    },
    openGames() {
      return Object.entries(this.games)
        .filter(([, g]) => Number(g.gameStatus) === 0)
        .map(([id, g]) => ({ id: Number(id), ...g }))
    },
    phaseLabel() {
      if (!this.game) return 'Demo deal'
      return PHASE_LABELS[Number(this.game.gameStatus)] || `phase ${this.game.gameStatus}`
    },
    wagerTez() {
      if (!this.game) return (this.wagerMutez / 1_000_000).toFixed(3)
      return (Number(this.game.wager) / 1_000_000).toFixed(3)
    },
    potTez() {
      if (!this.game) return '—'
      return ((Number(this.game.wager) * 2) / 1_000_000).toFixed(3)
    },
    feeTez() {
      return (FEE_MUTEZ / 1_000_000).toFixed(2)
    },
    myCards() {
      if (!this.game) return [null, null, null]
      const mine = this.game.player1 === this.walletAddress ? this.game.cards1 : this.game.cards2
      return this.normalizeCardMap(mine)
    },
    oppCards() {
      if (!this.game) return [null, null, null]
      const theirs = this.game.player1 === this.walletAddress ? this.game.cards2 : this.game.cards1
      return this.normalizeCardMap(theirs)
    },
    // Verdict for the active *real* game, once settled.
    realVerdict() {
      if (!this.game) return null
      if (Number(this.game.gameStatus) !== 2) return null
      const w = this.game.winner
      if (!w || w === BURN_ADDR) return 'push'
      if (w === this.walletAddress) return 'win'
      return 'lose'
    },
    settledReal() {
      return !!this.game && Number(this.game.gameStatus) === 2
    },
    // Per-side card arrays + reveal flags to render — sourced from
    // contract on a settled real game, otherwise from demo state.
    displayYouCards() {
      return this.settledReal ? this.myCards : this.demoYouCards
    },
    displayOppCards() {
      return this.settledReal ? this.oppCards : this.demoOppCards
    },
    displayYouRevealed() {
      // Settled real games reveal all three at once (UI hasn't run a
      // round-by-round flip animation for them — they arrive resolved).
      if (this.settledReal) return [true, true, true]
      return this.youRevealed
    },
    displayOppRevealed() {
      if (this.settledReal) return [true, true, true]
      return this.oppRevealed
    },
    // Per-side cumulative round wins — uses contract values once
    // settled, otherwise reflects the in-flight demo count.
    displayYouScore() {
      if (this.settledReal) {
        const mine = this.game.player1 === this.walletAddress
        return Number(mine ? this.game.p1Wins : this.game.p2Wins)
      }
      return this.youWins
    },
    displayOppScore() {
      if (this.settledReal) {
        const mine = this.game.player1 === this.walletAddress
        return Number(mine ? this.game.p2Wins : this.game.p1Wins)
      }
      return this.oppWins
    },
    displayVerdict() {
      return this.realVerdict || this.demoVerdict
    },
    canCancel() {
      return (
        this.game &&
        Number(this.game.gameStatus) === 0 &&
        this.game.player1 === this.walletAddress
      )
    },
    canJoin() {
      return (
        this.game &&
        Number(this.game.gameStatus) === 0 &&
        this.game.player1 !== this.walletAddress
      )
    },
    wagerOutOfBounds() {
      return (
        this.wagerMutez < MIN_WAGER_MUTEZ ||
        this.wagerMutez > MAX_WAGER_MUTEZ
      )
    },
  },
  created() {
    this.socket.on('newWallet', (w) => {
      this.walletAddress = w
    })
    // Webpack picks these up at build time via require().
    this.deck = [
      require('../assets/02_of_clubs.png'),
      require('../assets/02_of_diamonds.png'),
      require('../assets/02_of_hearts.png'),
      require('../assets/02_of_spades.png'),
      require('../assets/03_of_clubs.png'),
      require('../assets/03_of_diamonds.png'),
      require('../assets/03_of_hearts.png'),
      require('../assets/03_of_spades.png'),
      require('../assets/04_of_clubs.png'),
      require('../assets/04_of_diamonds.png'),
      require('../assets/04_of_hearts.png'),
      require('../assets/04_of_spades.png'),
      require('../assets/05_of_clubs.png'),
      require('../assets/05_of_diamonds.png'),
      require('../assets/05_of_hearts.png'),
      require('../assets/05_of_spades.png'),
      require('../assets/06_of_clubs.png'),
      require('../assets/06_of_diamonds.png'),
      require('../assets/06_of_hearts.png'),
      require('../assets/06_of_spades.png'),
      require('../assets/07_of_clubs.png'),
      require('../assets/07_of_diamonds.png'),
      require('../assets/07_of_hearts.png'),
      require('../assets/07_of_spades.png'),
      require('../assets/08_of_clubs.png'),
      require('../assets/08_of_diamonds.png'),
      require('../assets/08_of_hearts.png'),
      require('../assets/08_of_spades.png'),
      require('../assets/09_of_clubs.png'),
      require('../assets/09_of_diamonds.png'),
      require('../assets/09_of_hearts.png'),
      require('../assets/09_of_spades.png'),
      require('../assets/10_of_clubs.png'),
      require('../assets/10_of_diamonds.png'),
      require('../assets/10_of_hearts.png'),
      require('../assets/10_of_spades.png'),
      require('../assets/11_of_clubs.png'),
      require('../assets/11_of_diamonds.png'),
      require('../assets/11_of_hearts.png'),
      require('../assets/11_of_spades.png'),
      require('../assets/12_of_clubs.png'),
      require('../assets/12_of_diamonds.png'),
      require('../assets/12_of_hearts.png'),
      require('../assets/12_of_spades.png'),
      require('../assets/13_of_clubs.png'),
      require('../assets/13_of_diamonds.png'),
      require('../assets/13_of_hearts.png'),
      require('../assets/13_of_spades.png'),
      require('../assets/14_of_clubs.png'),
      require('../assets/14_of_diamonds.png'),
      require('../assets/14_of_hearts.png'),
      require('../assets/14_of_spades.png'),
    ]
    this.dealDemo()
    this.startDemoLoop()
    this.refresh()
    if (BLOCKCHAIN_ENABLED) {
      this.pollInterval = setInterval(() => this.refresh(), 8000)
    }
  },
  beforeUnmount() {
    if (this.pollInterval) clearInterval(this.pollInterval)
    this.stopDemoLoop()
    this.cancelPendingDemo()
  },
  methods: {
    setView(v) {
      this.view = v
    },
    toggleRules() {
      this.showRules = !this.showRules
    },
    cardFace(idx) {
      if (idx == null || idx < 0) return null
      return this.deck[idx] || null
    },
    cardLabel(idx) {
      return shortLabel(idx)
    },
    suitColor(idx) {
      return suitColor(idx)
    },
    rankOf(idx) {
      return idx == null || idx < 0 ? 0 : rankOf(idx)
    },
    // Coerce a contract cards1/cards2 map (keys may be string '0' or
    // number 0 depending on the JSON path) into a 3-slot array.
    normalizeCardMap(map) {
      const out = [null, null, null]
      if (!map) return out
      for (const r of [0, 1, 2]) {
        const v = map[r] ?? map[String(r)]
        if (v != null && Number(v) >= 0) out[r] = Number(v)
      }
      return out
    },
    // ─── Demo: deal & reveal (best-of-3, with 2-0 sweep skip) ───────
    dealDemo() {
      this.cancelPendingDemo()
      const { you, opp } = pickSix()
      this.demoYouCards = you
      this.demoOppCards = opp
      this.youRevealed = [false, false, false]
      this.oppRevealed = [false, false, false]
      this.roundOutcomes = [null, null, null]
      this.youWins = 0
      this.oppWins = 0
      this.demoVerdict = null
      this.knightLean = false
      this.orcLean = false

      // Score the full match up front so we know whether to short-circuit.
      const { youWins, oppWins, roundOutcomes } = scoreRounds(you, opp)
      // Sweep = whichever side has 2 wins in the first two rounds.
      const sweepAfterRound2 =
        (roundOutcomes[0] === 'you' && roundOutcomes[1] === 'you') ||
        (roundOutcomes[0] === 'opp' && roundOutcomes[1] === 'opp')

      // Beat schedule (ms). One round ≈ 800ms total: ~300ms opp flip,
      // ~250ms gap, ~250ms knight flip. Sweep ends after round 2.
      const ROUND_GAP = 850
      const ORC_FLIP = 320
      const KNIGHT_FLIP = 560
      const RESULT = 760

      const sched = (delay, fn) => {
        this.demoTimeouts.push(setTimeout(fn, delay))
      }

      const lastRound = sweepAfterRound2 ? 1 : 2
      for (let r = 0; r <= lastRound; r++) {
        const base = r * ROUND_GAP
        sched(base + ORC_FLIP, () => {
          this.orcLean = true
          this.oppRevealed = this.oppRevealed.map((v, i) => i === r ? true : v)
        })
        sched(base + KNIGHT_FLIP, () => {
          this.knightLean = true
          this.youRevealed = this.youRevealed.map((v, i) => i === r ? true : v)
        })
        sched(base + RESULT, () => {
          this.roundOutcomes = this.roundOutcomes.map((v, i) => i === r ? roundOutcomes[r] : v)
          if (roundOutcomes[r] === 'you') this.youWins += 1
          else if (roundOutcomes[r] === 'opp') this.oppWins += 1
          this.knightLean = false
          this.orcLean = false
        })
      }

      // Verdict pass after the final revealed round.
      const endBeat = (lastRound + 1) * ROUND_GAP
      sched(endBeat, () => {
        if (youWins > oppWins) this.demoVerdict = 'win'
        else if (oppWins > youWins) this.demoVerdict = 'lose'
        else this.demoVerdict = 'push'
      })
    },
    cancelPendingDemo() {
      for (const t of this.demoTimeouts) clearTimeout(t)
      this.demoTimeouts = []
    },
    // Auto-redeal so the table is never static. Skips when a real game
    // is in flight — the on-chain state takes precedence. Sweep games
    // resolve at ~2.4s, full series at ~3.2s; the 4.5s loop leaves a
    // breath of dead air between rounds.
    startDemoLoop() {
      this.stopDemoLoop()
      this.demoLoopTimer = setInterval(() => {
        if (this.inRealGame) return
        this.dealDemo()
      }, 4500)
    },
    stopDemoLoop() {
      if (this.demoLoopTimer) {
        clearInterval(this.demoLoopTimer)
        this.demoLoopTimer = null
      }
    },
    // ─── Contract calls ────────────────────────────────────────────
    async refresh() {
      try {
        const storage = await getContractStorage(WAR_CONTRACT_ADDRESS)
        if (!storage) return
        this.currentGameId = Number(storage.currentGameId || 0)
        this.games = storage.games || {}
        if (this.activeGameId == null && this.currentGameId > 0) {
          this.activeGameId = this.currentGameId - 1
        }
      } catch (e) {
        console.warn('war refresh failed:', e?.message)
      }
    },
    // Returns false (and sets a friendly status) when WAR_CONTRACT_ADDRESS
    // is still a KT1XXX… placeholder for the active network — feeding one to
    // tezos.wallet.at() throws an uncaught InvalidContractAddressError.
    // Every write path checks this first: `if (!this.prepWallet()) return`.
    prepWallet() {
      if (isPlaceholderAddress(WAR_CONTRACT_ADDRESS)) {
        this.blockchainStatus = 'War is not deployed on this network yet.'
        return false
      }
      this.tezos.setWalletProvider(this.wallet)
      return true
    },
    async createGame() {
      try {
        if (!this.prepWallet()) return
        if (this.wagerOutOfBounds) {
          this.blockchainStatus = `wager must be ${MIN_WAGER_MUTEZ / 1_000_000} – ${MAX_WAGER_MUTEZ / 1_000_000} ꜩ`
          return
        }
        this.blockchainStatus = 'creating war game...'
        const total = this.wagerMutez + FEE_MUTEZ
        const contract = await this.tezos.wallet.at(WAR_CONTRACT_ADDRESS)
        const op = await contract.methodsObject
          .createGame({ wager: this.wagerMutez })
          .send({ amount: total / 1_000_000 })
        await op.confirmation()
        this.blockchainStatus = 'created.'
        await this.refresh()
      } catch (err) {
        console.error('war create failed:', err)
        this.blockchainStatus = 'create failed'
      }
    },
    async joinGame(gameId) {
      try {
        if (!this.prepWallet()) return
        const g = this.games[gameId]
        if (!g) return
        this.blockchainStatus = `joining #${gameId}…`
        const total = Number(g.wager) + FEE_MUTEZ
        const contract = await this.tezos.wallet.at(WAR_CONTRACT_ADDRESS)
        const op = await contract.methodsObject
          .joinGame({ gameId })
          .send({ amount: total / 1_000_000 })
        await op.confirmation()
        this.activeGameId = gameId
        this.blockchainStatus = 'joined — waiting for oracle deal…'
        await this.refresh()
      } catch (err) {
        console.error('war join failed:', err)
        this.blockchainStatus = 'join failed'
      }
    },
    async cancelGame() {
      try {
        if (!this.prepWallet()) return
        if (!this.canCancel) return
        this.blockchainStatus = 'cancelling…'
        const contract = await this.tezos.wallet.at(WAR_CONTRACT_ADDRESS)
        const op = await contract.methodsObject
          .cancelGame({ gameId: this.activeGameId })
          .send()
        await op.confirmation()
        this.blockchainStatus = 'cancelled — wager refunded.'
        await this.refresh()
      } catch (err) {
        console.error('war cancel failed:', err)
        this.blockchainStatus = 'cancel failed'
      }
    },
    selectGame(gameId) {
      this.activeGameId = gameId
      this.setView('play')
    },
  },
}
</script>

<template>
  <div class="gameManagement warRoot">
    <!-- ── Parallax background (3D depth, scoped to this component) ─── -->
    <div class="warBg" aria-hidden="true">
      <div class="warBgStars warBgStars--far"></div>
      <div class="warBgStars warBgStars--mid"></div>
      <div class="warBgStars warBgStars--near"></div>
      <div class="warBgNebula"></div>
      <div class="warBgRing warBgRing--a"></div>
      <div class="warBgRing warBgRing--b"></div>
      <div class="warBgRing warBgRing--c"></div>
      <div class="warBgCardLoop">
        <span v-for="n in 6" :key="'bg-' + n" :class="['warBgCard', 'warBgCard--' + n]"></span>
      </div>
    </div>

    <!-- ───── Landing view ────────────────────────────────────────────── -->
    <template v-if="view === 'landing'">
      <div class="warHero">
        <div class="warHeroBrand">
          <div class="warHeroEyebrow">SPEED WAR · BEST OF 3</div>
          <div class="warHeroTitle">3 rounds. Higher card wins. 50/50.</div>
          <div class="warHeroSub">
            Both players ante up. The oracle deals six cards in one tx —
            three each. Each round the higher rank scores; more rounds won
            takes the pot. 2-0 sweep ends early. Tied series refunds.
          </div>
        </div>
        <div class="warHeroBoard" aria-hidden="true">
          <div class="warHeroStage">
            <div class="warHeroCard warHeroCard--left">
              <div class="warHeroCardInner">A<span>♠</span></div>
            </div>
            <div class="warHeroCard warHeroCard--right">
              <div class="warHeroCardInner">K<span>♥</span></div>
            </div>
            <div class="warHeroSpark"></div>
          </div>
        </div>
      </div>

      <div class="warStatusRow">
        <div class="warPill">
          <div class="warPillLabel">Phase</div>
          <div class="warPillValue">{{ phaseLabel }}</div>
        </div>
        <div class="warPill">
          <div class="warPillLabel">Game</div>
          <div class="warPillValue">{{ activeGameId == null ? '—' : '#' + activeGameId }}</div>
        </div>
        <div class="warPill">
          <div class="warPillLabel">Wager</div>
          <div class="warPillValue">{{ wagerTez }} ꜩ</div>
          <div class="warPillFootnote">+ {{ feeTez }} ꜩ fee</div>
        </div>
        <div class="warPill">
          <div class="warPillLabel">Pot</div>
          <div class="warPillValue">{{ potTez }} ꜩ</div>
        </div>
        <div class="warPill">
          <div class="warPillLabel">Bounds</div>
          <div class="warPillValue">0.1 – 5 ꜩ</div>
          <div class="warPillFootnote">contract enforced</div>
        </div>
      </div>

      <div class="rowFlex warPrimaryRow">
        <div class="actionButton warPrimary" @click="setView('play')">Open table</div>
        <div class="actionButton" @click="createGame">New game ({{ (wagerMutez / 1000000).toFixed(2) }} ꜩ)</div>
        <div class="actionButtonHelp" @click="toggleRules">{{ showRules ? 'Hide rules' : 'How it works' }}</div>
      </div>

      <div v-if="openGames.length" class="rowFlex">
        <div class="gameInfo warOpenLabel">Open challenges:</div>
        <div
          v-for="g in openGames"
          :key="g.id"
          class="actionButton"
          @click="joinGame(g.id)"
        >Join #{{ g.id }} — {{ (Number(g.wager) / 1000000).toFixed(2) }} ꜩ</div>
      </div>

      <div v-if="showRules" class="warRules">
        <ol>
          <li v-for="(line, i) in info" :key="i">{{ line }}</li>
        </ol>
      </div>

      <div class="gameInfo warStatusLine">{{ blockchainStatus }}</div>
    </template>

    <!-- ───── Play view ───────────────────────────────────────────────── -->
    <template v-else>
      <div class="rowFlex warPlayHeader">
        <div class="actionButton warBackBtn" @click="setView('landing')">‹ Lobby</div>
        <div class="gameInfo">
          {{ game ? 'Game #' + activeGameId + ' · ' + phaseLabel : 'Demo deal' }}
        </div>
        <div class="actionButton" @click="refresh">Refresh</div>
      </div>

      <div class="warStageWrap">
        <div :class="['warStage', displayVerdict ? `warStage--${displayVerdict}` : '']">
          <div class="warStageFloor"></div>
          <div class="warTable">
            <div class="warRail" aria-hidden="true"></div>
            <div class="warFelt">
              <div class="warBrand">SPEED WAR · BEST OF 3</div>

              <!-- Opponent's card (top) — orc avatar leans in alongside -->
              <div class="warSide warSide--opp">
                <div :class="['warCharacter', 'warCharacter--orc', { 'warCharacter--lean': orcLean }]" aria-hidden="true">
                  <svg viewBox="0 0 100 130" class="warCharSvg">
                    <!-- Shoulders / leather pauldrons -->
                    <path d="M10,120 Q15,90 30,82 L70,82 Q85,90 90,120 Z"
                          fill="#3a2a18" stroke="#1c130a" stroke-width="1.5"/>
                    <path d="M14,98 Q20,86 32,86 L38,90 L32,108 Q22,108 14,98 Z" fill="#5a3a20"/>
                    <path d="M86,98 Q80,86 68,86 L62,90 L68,108 Q78,108 86,98 Z" fill="#5a3a20"/>
                    <!-- Neck -->
                    <rect x="42" y="74" width="16" height="12" fill="#4a7a30"/>
                    <!-- Head -->
                    <ellipse cx="50" cy="50" rx="26" ry="28" fill="#5a8a3a"/>
                    <!-- Brow ridge / shadow -->
                    <path d="M24,46 Q50,30 76,46 L74,52 Q50,40 26,52 Z" fill="#3d6824"/>
                    <!-- Spiked helmet skull cap -->
                    <path d="M20,40 Q50,12 80,40 L78,32 L72,22 L66,30 L60,18 L54,28 L50,14 L46,28 L40,18 L34,30 L28,22 L22,32 Z"
                          fill="#2a1810" stroke="#0e0805" stroke-width="1"/>
                    <!-- Eyes — angry red glow -->
                    <ellipse cx="40" cy="52" rx="3.5" ry="2.2" fill="#1a0805"/>
                    <ellipse cx="60" cy="52" rx="3.5" ry="2.2" fill="#1a0805"/>
                    <circle cx="40" cy="52" r="1.4" fill="#ff4030"/>
                    <circle cx="60" cy="52" r="1.4" fill="#ff4030"/>
                    <!-- Nose -->
                    <path d="M48,56 L50,66 L52,56 Z" fill="#3d6824"/>
                    <!-- Mouth + tusks -->
                    <path d="M40,68 Q50,74 60,68" fill="none" stroke="#1c0e08" stroke-width="2" stroke-linecap="round"/>
                    <path d="M42,68 L40,76 L44,74 Z" fill="#f1e7c8"/>
                    <path d="M58,68 L60,76 L56,74 Z" fill="#f1e7c8"/>
                    <!-- Scar across cheek -->
                    <path d="M30,58 L38,62" stroke="#3d2410" stroke-width="1.2" stroke-linecap="round"/>
                    <!-- Axe haft poking up behind shoulder -->
                    <line x1="80" y1="120" x2="92" y2="50" stroke="#3a2412" stroke-width="3"/>
                    <path d="M86,52 L96,42 L98,50 L94,58 Z" fill="#9aa0a6" stroke="#3a2412" stroke-width="1"/>
                  </svg>
                  <div class="warCharName">GROK · ORC</div>
                </div>
                <div class="warSideLabel">
                  Opponent
                  <span class="warTotal warTotal--score">{{ displayOppScore }}</span>
                </div>
                <div class="warHand">
                  <div
                    v-for="r in 3"
                    :key="'opp-' + r"
                    :class="['warCardSlot', 'warCardSlot--round', `warCardSlot--round--${roundOutcomes[r-1] || 'pending'}`]"
                  >
                    <div :class="['warCard', {
                      'warCard--flipped': displayOppRevealed[r-1],
                      'warCard--winner': displayOppRevealed[r-1] && roundOutcomes[r-1] === 'opp',
                    }]">
                      <div class="warCardFace warCardFace--back">
                        <div class="warBack"><div class="warBackInner"><div class="warBackMark">W</div></div></div>
                      </div>
                      <div class="warCardFace warCardFace--front">
                        <img
                          v-if="cardFace(displayOppCards[r-1])"
                          :src="cardFace(displayOppCards[r-1])"
                          :alt="cardLabel(displayOppCards[r-1])"
                          class="warCardImg"
                          draggable="false"
                        />
                        <div :class="['warCardCorner', `warCardCorner--${suitColor(displayOppCards[r-1])}`]">
                          {{ cardLabel(displayOppCards[r-1]) }}
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              <div class="warVs">vs</div>

              <!-- Your card (bottom) — knight avatar leans in alongside -->
              <div class="warSide warSide--you">
                <div :class="['warCharacter', 'warCharacter--knight', { 'warCharacter--lean': knightLean }]" aria-hidden="true">
                  <svg viewBox="0 0 100 130" class="warCharSvg">
                    <!-- Sword diagonal behind shoulder -->
                    <line x1="2" y1="120" x2="22" y2="22" stroke="#7c6a3f" stroke-width="2.5"/>
                    <rect x="14" y="18" width="14" height="2.5" rx="1" fill="#d4a24e"/>
                    <path d="M19,22 L23,8 L27,22 Z" fill="#dde2ea" stroke="#5a6068" stroke-width="0.8"/>
                    <!-- Shoulders / blue tabard -->
                    <path d="M10,120 Q14,92 28,84 L72,84 Q86,92 90,120 Z"
                          fill="#1d2a78" stroke="#0c1240" stroke-width="1.5"/>
                    <!-- Gold cross on tabard -->
                    <rect x="46" y="92" width="8" height="22" fill="#f5c451"/>
                    <rect x="38" y="98" width="24" height="8" fill="#f5c451"/>
                    <!-- Pauldrons (steel) -->
                    <ellipse cx="18" cy="92" rx="10" ry="8" fill="#9aa0a6" stroke="#42464d" stroke-width="1"/>
                    <ellipse cx="82" cy="92" rx="10" ry="8" fill="#9aa0a6" stroke="#42464d" stroke-width="1"/>
                    <!-- Neck guard -->
                    <rect x="42" y="74" width="16" height="12" fill="#7a8088"/>
                    <!-- Helmet — rounded great-helm -->
                    <path d="M22,60 Q22,28 50,22 Q78,28 78,60 L78,72 Q50,80 22,72 Z"
                          fill="#c4cad2" stroke="#42464d" stroke-width="1.5"/>
                    <!-- Helmet shading -->
                    <path d="M22,60 Q22,28 50,22 L50,50 Q34,52 22,60 Z" fill="#dde2ea" opacity="0.55"/>
                    <!-- Visor slit -->
                    <rect x="32" y="48" width="36" height="4" rx="1.5" fill="#0a0c12"/>
                    <!-- Eye glints behind slit -->
                    <rect x="40" y="49" width="3" height="2" fill="#f5c451"/>
                    <rect x="57" y="49" width="3" height="2" fill="#f5c451"/>
                    <!-- Cross-shaped visor stripe -->
                    <rect x="48" y="32" width="4" height="38" fill="#42464d"/>
                    <!-- Red plume -->
                    <path d="M50,22 Q44,8 50,2 Q56,8 50,22 Z" fill="#c4524f" stroke="#7a2a28" stroke-width="0.8"/>
                    <path d="M50,16 Q42,12 38,6 Q46,8 50,16 Z" fill="#a8413e"/>
                    <path d="M50,16 Q58,12 62,6 Q54,8 50,16 Z" fill="#a8413e"/>
                  </svg>
                  <div class="warCharName">SIR ELDRIC · KNIGHT</div>
                </div>
                <div class="warSideLabel">
                  You
                  <span class="warTotal warTotal--score">{{ displayYouScore }}</span>
                </div>
                <div class="warHand">
                  <div
                    v-for="r in 3"
                    :key="'you-' + r"
                    :class="['warCardSlot', 'warCardSlot--round', `warCardSlot--round--${roundOutcomes[r-1] || 'pending'}`]"
                  >
                    <div :class="['warCard', {
                      'warCard--flipped': displayYouRevealed[r-1],
                      'warCard--winner': displayYouRevealed[r-1] && roundOutcomes[r-1] === 'you',
                    }]">
                      <div class="warCardFace warCardFace--back">
                        <div class="warBack"><div class="warBackInner"><div class="warBackMark">W</div></div></div>
                      </div>
                      <div class="warCardFace warCardFace--front">
                        <img
                          v-if="cardFace(displayYouCards[r-1])"
                          :src="cardFace(displayYouCards[r-1])"
                          :alt="cardLabel(displayYouCards[r-1])"
                          class="warCardImg"
                          draggable="false"
                        />
                        <div :class="['warCardCorner', `warCardCorner--${suitColor(displayYouCards[r-1])}`]">
                          {{ cardLabel(displayYouCards[r-1]) }}
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              <!-- Awaiting-deal overlay: real game in gameStatus=1 -->
              <div
                v-if="game && Number(game.gameStatus) === 1"
                class="warAwaiting"
              >
                <div class="warAwaitingSpinner"></div>
                <div class="warAwaitingLabel">Oracle is dealing…</div>
              </div>

              <div v-if="displayVerdict === 'win'" class="warVerdict warVerdict--win">YOU WIN</div>
              <div v-else-if="displayVerdict === 'lose'" class="warVerdict warVerdict--loss">YOU LOSE</div>
              <div v-else-if="displayVerdict === 'push'" class="warVerdict warVerdict--push">PUSH · REFUND</div>
            </div>
          </div>
        </div>
      </div>

      <div v-if="!inRealGame" class="demoHint">
        <span class="demoHintDot"></span>
        <span class="demoHintLabel">DEMO</span>
        <span class="demoHintBody">Random local draw. The on-chain version uses the oracle's verifiable RNG.</span>
        <button class="demoBtn" @click="dealDemo">Deal again</button>
      </div>

      <div class="rowFlex">
        <div class="actionButton" @click="createGame">New game ({{ (wagerMutez / 1000000).toFixed(2) }} ꜩ)</div>
        <div v-if="canJoin" class="actionButton" @click="joinGame(activeGameId)">
          Join this game ({{ wagerTez }} ꜩ)
        </div>
        <div v-if="canCancel" class="actionButton" @click="cancelGame">Cancel & refund</div>
        <div class="actionButton" @click="setView('landing')">Back to lobby</div>
      </div>

      <div class="gameInfo warStatusLine">{{ blockchainStatus }}</div>
    </template>
  </div>
</template>

<style scoped>
.warRoot {
  font-family: 'EB Garamond', serif;
  color: #efeae2;
  position: relative;
  isolation: isolate; /* contain ::before stacking so bg layers don't bleed */
}

/* ────────────────────────────────────────────────────────────────────
 * 3D parallax background — fixed inside .warRoot, behind all content.
 * Stacking: nebula < star layers (parallax) < rotating rings < drifting
 * card silhouettes. Each layer animates independently to fake depth.
 * ──────────────────────────────────────────────────────────────────── */
.warBg {
  position: absolute; inset: -20px;
  z-index: -1;
  border-radius: 16px;
  overflow: hidden;
  background:
    radial-gradient(ellipse at 20% 10%, rgba(120, 60, 230, 0.18) 0%, transparent 55%),
    radial-gradient(ellipse at 80% 90%, rgba(245, 196, 81, 0.10) 0%, transparent 60%),
    linear-gradient(160deg, #0a0420 0%, #050211 60%, #02010a 100%);
  perspective: 900px;
  perspective-origin: 50% 30%;
}
.warBgNebula {
  position: absolute; inset: -30%;
  background:
    radial-gradient(ellipse at 30% 40%, rgba(80, 30, 180, 0.45) 0%, transparent 40%),
    radial-gradient(ellipse at 70% 60%, rgba(200, 60, 120, 0.20) 0%, transparent 45%);
  filter: blur(40px);
  animation: warNebula 22s ease-in-out infinite alternate;
}
@keyframes warNebula {
  0%   { transform: translate3d(-2%, -1%, 0) scale(1.02); opacity: 0.85; }
  100% { transform: translate3d(2%, 2%, 0) scale(1.08); opacity: 1; }
}

/* Three star layers — different sizes, speeds, depths. radial-gradient
 * with tiny stops gives us a "starfield" without an image asset. */
.warBgStars {
  position: absolute; inset: -10%;
  background-repeat: repeat;
}
.warBgStars--far {
  background-image:
    radial-gradient(1px 1px at 12% 18%, rgba(255,255,255,0.7), transparent 60%),
    radial-gradient(1px 1px at 28% 64%, rgba(255,255,255,0.55), transparent 60%),
    radial-gradient(1px 1px at 53% 22%, rgba(255,255,255,0.6), transparent 60%),
    radial-gradient(1px 1px at 71% 81%, rgba(255,255,255,0.5), transparent 60%),
    radial-gradient(1px 1px at 88% 33%, rgba(255,255,255,0.6), transparent 60%),
    radial-gradient(1px 1px at 41% 92%, rgba(255,255,255,0.55), transparent 60%),
    radial-gradient(1px 1px at 5%  46%, rgba(255,255,255,0.5), transparent 60%);
  background-size: 600px 600px;
  animation: warStars 120s linear infinite;
  opacity: 0.55;
}
.warBgStars--mid {
  background-image:
    radial-gradient(1.5px 1.5px at 14% 32%, rgba(255,225,180,0.85), transparent 60%),
    radial-gradient(1.5px 1.5px at 36% 78%, rgba(255,255,255,0.85), transparent 60%),
    radial-gradient(1.5px 1.5px at 62% 12%, rgba(200,200,255,0.8), transparent 60%),
    radial-gradient(1.5px 1.5px at 80% 58%, rgba(255,255,255,0.85), transparent 60%),
    radial-gradient(1.5px 1.5px at 23% 6%,  rgba(255,255,255,0.7), transparent 60%);
  background-size: 450px 450px;
  animation: warStars 80s linear infinite;
  opacity: 0.7;
}
.warBgStars--near {
  background-image:
    radial-gradient(2px 2px at 18% 50%, rgba(245,196,81,0.85), transparent 60%),
    radial-gradient(2px 2px at 70% 30%, rgba(255,255,255,0.95), transparent 60%),
    radial-gradient(2px 2px at 50% 88%, rgba(255,200,200,0.85), transparent 60%);
  background-size: 320px 320px;
  animation: warStars 50s linear infinite;
  opacity: 0.85;
}
@keyframes warStars {
  from { transform: translate3d(0, 0, 0); }
  to   { transform: translate3d(-600px, -200px, 0); }
}

/* Slowly rotating concentric rings — sit at different z-depths for
 * a real perspective parallax. */
.warBgRing {
  position: absolute;
  border: 1px solid rgba(245, 196, 81, 0.10);
  border-radius: 50%;
  transform-style: preserve-3d;
}
.warBgRing--a {
  width: 700px; height: 700px;
  top: 50%; left: 50%;
  transform: translate(-50%, -50%) translateZ(-200px) rotateX(72deg);
  animation: warRingSpin 36s linear infinite;
}
.warBgRing--b {
  width: 900px; height: 900px;
  top: 50%; left: 50%;
  transform: translate(-50%, -50%) translateZ(-340px) rotateX(72deg) rotateZ(40deg);
  border-color: rgba(150, 80, 220, 0.10);
  animation: warRingSpin 60s linear infinite reverse;
}
.warBgRing--c {
  width: 1200px; height: 1200px;
  top: 50%; left: 50%;
  transform: translate(-50%, -50%) translateZ(-520px) rotateX(72deg) rotateZ(80deg);
  border-color: rgba(245, 196, 81, 0.06);
  animation: warRingSpin 90s linear infinite;
}
@keyframes warRingSpin {
  from { transform: translate(-50%, -50%) rotateX(72deg) rotateZ(0deg); }
  to   { transform: translate(-50%, -50%) rotateX(72deg) rotateZ(360deg); }
}

/* Faint card silhouettes drifting deeper in the scene. */
.warBgCardLoop {
  position: absolute; inset: 0;
  transform-style: preserve-3d;
}
.warBgCard {
  position: absolute;
  width: 60px; height: 90px;
  border-radius: 5px;
  background: linear-gradient(135deg, rgba(245,196,81,0.10), rgba(120,40,200,0.10));
  border: 1px solid rgba(245, 196, 81, 0.18);
  opacity: 0.55;
  filter: blur(0.5px);
  animation: warCardDrift 18s ease-in-out infinite;
}
.warBgCard--1 { top: 12%; left:  8%; animation-delay:  0s;   transform: rotate(-12deg); }
.warBgCard--2 { top: 30%; left: 82%; animation-delay: -3s;   transform: rotate( 14deg); }
.warBgCard--3 { top: 64%; left: 12%; animation-delay: -6s;   transform: rotate( 18deg); }
.warBgCard--4 { top: 78%; left: 70%; animation-delay: -9s;   transform: rotate(-10deg); }
.warBgCard--5 { top: 22%; left: 48%; animation-delay: -12s;  transform: rotate(  4deg); }
.warBgCard--6 { top: 50%; left: 92%; animation-delay: -15s;  transform: rotate(-22deg); }
@keyframes warCardDrift {
  0%, 100% { transform: translate3d(0, 0, 0) rotate(var(--r, 0deg)); opacity: 0.35; }
  50%      { transform: translate3d(8px, -14px, 60px) rotate(calc(var(--r, 0deg) + 6deg)); opacity: 0.65; }
}

/* ─── Hero ─────────────────────────────────────────────────────────── */
.warHero {
  display: flex; flex-direction: row; gap: 18px;
  padding: 18px 16px; margin: 8px 4px 14px;
  border-radius: 14px;
  background:
    radial-gradient(ellipse at 80% 20%, rgba(212, 162, 78, 0.15) 0%, transparent 60%),
    linear-gradient(135deg, rgba(25, 8, 87, 0.85) 0%, rgba(7, 4, 30, 0.92) 100%);
  box-shadow:
    inset 0 0 0 1px rgba(255, 255, 255, 0.06),
    0 8px 22px rgba(0, 0, 0, 0.45);
  backdrop-filter: blur(2px);
}
.warHeroBrand { flex: 1.4; min-width: 0; }
.warHeroBoard {
  flex: 1; display: flex; align-items: center; justify-content: center;
  perspective: 800px;
}
.warHeroStage {
  position: relative;
  width: 100%; max-width: 240px; aspect-ratio: 3 / 2;
  transform-style: preserve-3d;
  transform: rotateX(8deg);
}
.warHeroCard {
  position: absolute;
  width: 38%; height: 80%;
  top: 10%;
  border-radius: 6px;
  background: linear-gradient(135deg, #fff 0%, #f1eadd 100%);
  display: flex; align-items: center; justify-content: center;
  font-size: clamp(22px, 5vw, 32px); font-weight: 700;
  box-shadow:
    0 6px 14px rgba(0,0,0,0.55),
    inset 0 0 0 1px rgba(0,0,0,0.06);
  animation: warHeroFloat 4.2s ease-in-out infinite;
}
.warHeroCardInner { display: flex; align-items: baseline; gap: 2px; }
.warHeroCardInner span { font-size: 0.75em; }
.warHeroCard--left {
  left: 6%;
  color: #1a1a1a;
  transform: rotate(-14deg) translateZ(20px);
}
.warHeroCard--right {
  right: 6%;
  color: #c4524f;
  transform: rotate(12deg) translateZ(0px);
  animation-delay: -2.1s;
}
@keyframes warHeroFloat {
  0%, 100% { transform: rotate(var(--rot, -14deg)) translate3d(0, 0, 20px); }
  50%      { transform: rotate(var(--rot, -14deg)) translate3d(0, -6px, 30px); }
}
.warHeroCard--left  { --rot: -14deg; }
.warHeroCard--right { --rot:  12deg; }
.warHeroSpark {
  position: absolute; left: 50%; top: 50%;
  width: 70px; height: 70px;
  transform: translate(-50%, -50%) translateZ(40px);
  background: radial-gradient(circle, rgba(245, 196, 81, 0.55) 0%, transparent 70%);
  border-radius: 50%;
  animation: warHeroSpark 3s ease-in-out infinite;
}
@keyframes warHeroSpark {
  0%, 100% { opacity: 0.4; transform: translate(-50%, -50%) translateZ(40px) scale(0.9); }
  50%      { opacity: 0.9; transform: translate(-50%, -50%) translateZ(40px) scale(1.15); }
}
.warHeroEyebrow { font-size: 10px; letter-spacing: 4px; font-weight: 700; color: rgba(245,196,81,0.75); margin-bottom: 6px; }
.warHeroTitle { font-size: clamp(20px, 4.5vw, 30px); line-height: 1.1; font-weight: 700; color: #fff; margin-bottom: 8px; }
.warHeroSub { font-size: 13px; line-height: 1.4; color: rgba(255, 255, 255, 0.78); }

/* ─── Status pills ──────────────────────────────────────────────────── */
.warStatusRow { display: flex; flex-wrap: wrap; gap: 6px; margin: 0 4px 12px; }
.warPill {
  flex: 1 1 110px; min-width: 110px; padding: 8px 10px; border-radius: 8px;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.08);
  backdrop-filter: blur(2px);
}
.warPillLabel { font-size: 9px; letter-spacing: 2px; text-transform: uppercase; color: rgba(255,255,255,0.55); }
.warPillValue { font-size: 16px; font-weight: 700; color: #fff; margin-top: 2px; }
.warPillFootnote { font-size: 10px; color: rgba(255,255,255,0.55); margin-top: 2px; }

.warPrimaryRow { margin-top: 4px; }
.warPrimary {
  background: linear-gradient(135deg, #2a1577 0%, #190857 100%);
  border-color: #f5c451;
  font-weight: 700; letter-spacing: 1px; text-transform: uppercase;
}
.warOpenLabel { flex: 0 0 auto; align-self: center; font-size: 12px; }

.warRules {
  margin: 8px 4px 12px; padding: 12px 16px; border-radius: 8px;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.08);
  backdrop-filter: blur(2px);
}
.warRules ol { margin: 0; padding-left: 20px; font-size: 13px; line-height: 1.55; color: rgba(255,255,255,0.85); }

.warStatusLine { font-size: 12px; color: #d4a24e; font-style: italic; min-height: 16px; }

/* ─── Play stage (3D perspective) ───────────────────────────────────── */
.warPlayHeader { margin: 4px 0 8px; }
.warBackBtn { flex: 0 0 auto; min-width: 90px; }

.warStageWrap {
  display: flex; justify-content: center;
  margin: 8px 0 12px;
  perspective: 1400px;
  perspective-origin: 50% 40%;
}
.warStage {
  position: relative;
  width: clamp(280px, 92vw, 640px);
  aspect-ratio: 4 / 3;
  transform-style: preserve-3d;
  transform: rotateX(12deg);
  transition: transform 0.6s ease;
}
.warStage--win  { transform: rotateX(10deg) scale(1.01); }
.warStage--lose { transform: rotateX(14deg) scale(0.99); }
.warStageFloor {
  position: absolute;
  left: -8%; right: -8%; bottom: -6%;
  height: 60%;
  background: radial-gradient(ellipse at 50% 0%, rgba(0,0,0,0.55) 0%, transparent 70%);
  transform: rotateX(72deg) translateY(40%);
  transform-origin: 50% 0%;
  filter: blur(8px);
  pointer-events: none;
}

.warTable {
  position: relative;
  width: 100%; height: 100%;
  border-radius: 22px;
  overflow: hidden;
  box-shadow:
    0 24px 60px rgba(0, 0, 0, 0.65),
    0 6px 18px rgba(0, 0, 0, 0.55),
    inset 0 0 0 1px rgba(255, 255, 255, 0.06);
  transform: translateZ(0);
  transition: box-shadow 0.4s ease;
}
.warStage--win  .warTable { box-shadow: 0 0 0 2px #f5c451, 0 0 40px 6px rgba(245, 196, 81, 0.50), 0 24px 60px rgba(0, 0, 0, 0.65); }
.warStage--lose .warTable { box-shadow: 0 0 0 2px #c4524f, 0 0 32px 4px rgba(196, 82, 79, 0.45), 0 24px 60px rgba(0, 0, 0, 0.65); }
.warStage--push .warTable { box-shadow: 0 0 0 2px #d4a24e, 0 0 28px 4px rgba(212, 162, 78, 0.40), 0 24px 60px rgba(0, 0, 0, 0.65); }

.warRail {
  position: absolute; inset: 0;
  background:
    radial-gradient(ellipse at center, transparent 55%, rgba(0, 0, 0, 0.35) 100%),
    linear-gradient(135deg, #3a2415 0%, #5c3823 40%, #2a1a10 100%);
  border-radius: 22px;
}
.warFelt {
  position: absolute; inset: 16px;
  border-radius: 14px;
  background:
    radial-gradient(ellipse at 50% 35%, rgba(255,255,255,0.06) 0%, transparent 50%),
    radial-gradient(ellipse at 50% 50%, #1f5c3a 0%, #0e3b22 60%, #07291a 100%);
  display: flex; flex-direction: column; justify-content: space-between;
  padding: 14px 12px 14px;
  box-shadow: inset 0 0 30px rgba(0,0,0,0.45);
}
.warBrand {
  position: absolute; top: 8px; left: 50%; transform: translateX(-50%);
  letter-spacing: 4px; font-size: 10px; color: rgba(245, 196, 81, 0.55); font-weight: 600;
}

.warSide {
  display: grid;
  grid-template-columns: 1fr auto 1fr;
  align-items: center;
  justify-items: center;
  gap: 8px;
}
/* Row layout per side:
 *   opp (top):  [orc avatar] [opp card]  [—filler—]   (label sits above card via order)
 *   you (bot):  [—filler—]   [your card] [knight avatar]
 *
 * The label rides on top of the card column via grid-column. The opposite
 * filler keeps the card visually centered between the two avatars.
 */
.warSide > .warSideLabel { grid-column: 2; grid-row: 1; order: 0; }
.warSide > .warCardSlot  { grid-column: 2; grid-row: 2; }
.warSide--opp > .warCharacter--orc     { grid-column: 1; grid-row: 1 / span 2; justify-self: end; }
.warSide--you > .warCharacter--knight  { grid-column: 3; grid-row: 1 / span 2; justify-self: start; }

.warSide--opp { transform: rotate(180deg); }
/* The img and corner get the rotate back so they read upright after the side flip. */
.warSide--opp .warSideLabel,
.warSide--opp .warCardCorner,
.warSide--opp .warCardImg,
.warSide--opp .warCharacter--orc { transform: rotate(180deg); }
.warSideLabel {
  font-size: 11px; letter-spacing: 2px; text-transform: uppercase;
  color: rgba(255, 255, 255, 0.85);
  display: flex; align-items: center; gap: 8px;
}
.warTotal {
  font-size: 14px; color: #f5c451; font-weight: 700;
  padding: 1px 8px; border-radius: 4px;
  background: rgba(0, 0, 0, 0.45);
  min-width: 22px; text-align: center;
}
.warCardSlot--big {
  width: clamp(86px, 18vw, 140px);
  aspect-ratio: 2.5 / 3.5;
  perspective: 1200px;
}
/* Three smaller slots side-by-side for the best-of-3 layout. */
.warHand {
  display: flex; flex-direction: row;
  gap: clamp(4px, 1.5vw, 12px);
}
.warCardSlot--round {
  width: clamp(56px, 12vw, 96px);
  aspect-ratio: 2.5 / 3.5;
  perspective: 1200px;
  position: relative;
  transition: filter 0.4s ease;
}
.warCardSlot--round--you  .warCard { filter: drop-shadow(0 0 8px rgba(245, 196, 81, 0.65)); }
.warCardSlot--round--opp  .warCard { filter: drop-shadow(0 0 8px rgba(196, 82, 79, 0.55)); }
.warCardSlot--round--wash .warCard { filter: grayscale(0.45) drop-shadow(0 0 5px rgba(212, 162, 78, 0.35)); }
.warTotal--score {
  font-size: 18px; padding: 1px 10px;
}

/* ─── Characters (knight & orc) ─────────────────────────────────────── */
.warCharacter {
  width: clamp(70px, 14vw, 110px);
  display: flex; flex-direction: column; align-items: center; gap: 4px;
  transform-origin: 50% 100%;
  transition: transform 0.45s cubic-bezier(0.2, 0.7, 0.2, 1);
  filter: drop-shadow(0 6px 10px rgba(0, 0, 0, 0.55));
}
.warCharSvg {
  width: 100%; height: auto;
  display: block;
}
.warCharName {
  font-size: 9px; letter-spacing: 1.5px; font-weight: 700;
  color: rgba(245, 196, 81, 0.9);
  text-align: center;
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.7);
}
/* Idle bob keeps the characters alive between deals. */
.warCharacter--knight {
  animation: warKnightIdle 4.4s ease-in-out infinite;
}
.warCharacter--orc {
  animation: warOrcIdle 5.2s ease-in-out infinite;
}
@keyframes warKnightIdle {
  0%, 100% { transform: translateY(0) rotate(-1.5deg); }
  50%      { transform: translateY(-2px) rotate(1.5deg); }
}
@keyframes warOrcIdle {
  0%, 100% { transform: translateY(0) rotate(2deg); }
  50%      { transform: translateY(-3px) rotate(-2deg); }
}
/* Lean — applied briefly during the reveal so the character cranes
 * toward the card. Overrides the idle animation via !important. */
.warCharacter--knight.warCharacter--lean {
  transform: translate(-6px, -4px) rotate(-12deg) scale(1.06) !important;
  animation: none !important;
}
.warCharacter--orc.warCharacter--lean {
  transform: translate(6px, -4px) rotate(12deg) scale(1.06) !important;
  animation: none !important;
}
.warVs {
  text-align: center;
  font-size: 11px; letter-spacing: 4px; font-weight: 700;
  color: rgba(245, 196, 81, 0.65);
  margin: 4px 0;
  text-shadow: 0 0 12px rgba(245, 196, 81, 0.4);
}

/* ─── Card 3D flip & winner lift ────────────────────────────────────── */
.warCard {
  position: relative; width: 100%; height: 100%;
  transform-style: preserve-3d;
  transition: transform 0.9s cubic-bezier(0.65, 0, 0.35, 1);
  animation: warCardDeal 0.8s cubic-bezier(0.2, 0.7, 0.2, 1) both;
}
@keyframes warCardDeal {
  0%   { transform: translate3d(0, -40px, -120px) rotateZ(-8deg); opacity: 0; }
  60%  { opacity: 1; }
  100% { transform: translate3d(0, 0, 0) rotateZ(0deg); opacity: 1; }
}
.warCard--flipped { transform: rotateY(180deg); }
.warCard--winner {
  animation: warCardWin 1.4s ease-in-out infinite alternate;
}
@keyframes warCardWin {
  from { filter: drop-shadow(0 0 0 rgba(245, 196, 81, 0)); transform: rotateY(180deg) translateZ(0); }
  to   { filter: drop-shadow(0 0 14px rgba(245, 196, 81, 0.85)); transform: rotateY(180deg) translateZ(18px); }
}
.warCardFace {
  position: absolute; inset: 0;
  border-radius: 8px;
  backface-visibility: hidden;
  -webkit-backface-visibility: hidden;
  overflow: hidden;
  box-shadow:
    0 8px 18px rgba(0, 0, 0, 0.55),
    inset 0 0 0 1px rgba(255, 255, 255, 0.10);
}
.warCardFace--back { background: #fff; }
.warCardFace--front { transform: rotateY(180deg); background: #fff; display: flex; align-items: center; justify-content: center; position: relative; }
.warCardImg { width: 100%; height: 100%; object-fit: cover; user-select: none; -webkit-user-drag: none; }
.warCardCorner {
  position: absolute; top: 4px; left: 6px;
  font-size: 11px; font-weight: 700;
  background: rgba(255, 255, 255, 0.88);
  border-radius: 3px; padding: 1px 4px; line-height: 1;
}
.warCardCorner--red { color: #c4524f; }
.warCardCorner--black { color: #1a1a1a; }

/* ─── Custom CSS card back ──────────────────────────────────────────── */
.warBack {
  width: 100%; height: 100%;
  background:
    repeating-linear-gradient(45deg, #190857 0 6px, #2a1577 6px 12px),
    radial-gradient(ellipse at center, #2a1577, #190857);
  display: flex; align-items: center; justify-content: center;
  padding: 6px;
}
.warBackInner {
  width: 100%; height: 100%;
  border: 2px solid rgba(245, 196, 81, 0.85);
  border-radius: 5px;
  display: flex; align-items: center; justify-content: center;
  background: radial-gradient(ellipse at center, rgba(25, 8, 87, 0.6) 0%, rgba(0, 0, 0, 0.55) 100%);
}
.warBackMark {
  font-family: 'EB Garamond', serif; font-weight: 700;
  font-size: clamp(28px, 7vw, 48px); color: #f5c451;
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.55), 0 0 12px rgba(245, 196, 81, 0.45);
}

/* ─── Verdict ribbon ────────────────────────────────────────────────── */
.warVerdict {
  position: absolute; bottom: 10px; left: 50%; transform: translateX(-50%) translateZ(20px);
  font-size: 13px; letter-spacing: 4px; font-weight: 700;
  padding: 5px 16px; border-radius: 4px;
  border: 1px solid currentColor;
  animation: warVerdictIn 0.5s ease-out both;
  backdrop-filter: blur(2px);
}
.warVerdict--win  { color: #f5c451; background: rgba(245, 196, 81, 0.18); text-shadow: 0 0 14px rgba(245, 196, 81, 0.55); }
.warVerdict--loss { color: #c4524f; background: rgba(196, 82, 79, 0.18); }
.warVerdict--push { color: #d4a24e; background: rgba(212, 162, 78, 0.16); }
@keyframes warVerdictIn { from { opacity: 0; transform: translate(-50%, 8px); } to { opacity: 1; transform: translate(-50%, 0); } }

/* ─── Awaiting-oracle overlay ───────────────────────────────────────── */
.warAwaiting {
  position: absolute; inset: 0;
  display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 12px;
  background: rgba(0, 0, 0, 0.45);
  backdrop-filter: blur(2px);
}
.warAwaitingSpinner {
  width: 40px; height: 40px; border-radius: 50%;
  border: 3px solid rgba(245, 196, 81, 0.2);
  border-top-color: #f5c451;
  animation: warSpin 1s linear infinite;
}
@keyframes warSpin { to { transform: rotate(360deg); } }
.warAwaitingLabel {
  font-size: 11px; letter-spacing: 3px; font-weight: 700;
  color: rgba(245, 196, 81, 0.9);
}

/* ─── Demo hint ─────────────────────────────────────────────────────── */
.demoHint {
  display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
  padding: 6px 10px; margin: 8px auto;
  max-width: 640px; border-radius: 8px;
  background: rgba(245, 196, 81, 0.08);
  border: 1px dashed rgba(245, 196, 81, 0.45);
  color: rgba(255, 255, 255, 0.85);
  font-size: 12px;
}
.demoHintDot {
  width: 8px; height: 8px; border-radius: 50%; background: #f5c451;
  box-shadow: 0 0 6px rgba(245, 196, 81, 0.8); animation: demoPulse 1.6s ease-in-out infinite;
}
@keyframes demoPulse { 0%, 100% { opacity: 0.5; } 50% { opacity: 1; } }
.demoHintLabel { font-size: 10px; letter-spacing: 3px; font-weight: 700; color: #f5c451; }
.demoBtn {
  background: transparent; border: 1px solid rgba(245, 196, 81, 0.55);
  border-radius: 4px; color: #f5c451;
  font-family: 'EB Garamond', serif; font-size: 11px; letter-spacing: 1.5px;
  font-weight: 700; padding: 4px 10px; cursor: pointer;
}
.demoBtn:hover { background: rgba(245, 196, 81, 0.12); }

@media (max-width: 480px) {
  .warHero { flex-direction: column; gap: 12px; }
  .warBgRing--a, .warBgRing--b, .warBgRing--c { display: none; }
}
@media (prefers-reduced-motion: reduce) {
  .warBgStars--far, .warBgStars--mid, .warBgStars--near,
  .warBgRing--a, .warBgRing--b, .warBgRing--c,
  .warBgNebula, .warBgCard,
  .warHeroCard, .warHeroSpark,
  .warCard, .warCard--winner,
  .warCharacter--knight, .warCharacter--orc {
    animation: none !important;
  }
}
</style>
