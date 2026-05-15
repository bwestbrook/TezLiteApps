<script>
import { toRaw } from 'vue'
import { AD_CONTRACT_ADDRESS, AD_GAME_INFO, BLOCKCHAIN_ENABLED } from '../constants'
import { getContractStorage } from '../services/tzkt'

// Deck index ↔ rank/suit helpers. Indices are 0..51:
//   rank = Math.floor(i / 4) + 2   (2..14, where 11=J 12=Q 13=K 14=A)
//   suit = i % 4                   (0=♣ 1=♦ 2=♥ 3=♠)
const SUIT_GLYPHS = ['♣', '♦', '♥', '♠']
const RANK_LABELS = { 11: 'J', 12: 'Q', 13: 'K', 14: 'A' }

function rankOf(deckIndex) {
  if (deckIndex == null || deckIndex < 0) return null
  return Math.floor(deckIndex / 4) + 2
}
function suitOf(deckIndex) {
  if (deckIndex == null || deckIndex < 0) return null
  return deckIndex % 4
}
function shortLabel(deckIndex) {
  const r = rankOf(deckIndex)
  const s = suitOf(deckIndex)
  if (r == null) return ''
  return `${RANK_LABELS[r] || r}${SUIT_GLYPHS[s]}`
}

export default {
  name: 'aceyDuecey',
  props: ['socket', 'wallet', 'tezos'],
  data() {
    return {
      // ─── Blockchain / game state (unchanged from original) ──────────────
      pollInterval: null,
      gameInfo: AD_GAME_INFO,
      showInfo: false,
      needsLastCard: false,
      blockChainStatus: '',
      tezosSymbol: 'ꜩ',
      gameId: 'NA',
      lastGameId: -1,
      firstCard: -1,
      secondCard: -1,
      lastCard: 0,
      potBalance: 0,
      ante: 0.2, // ꜩ — matches AD storage's `ante` (200000 mutez)
      fee: 0.1,  // ꜩ — matches AD storage's `fee`  (100000 mutez)
      thisBet: 0.1,
      myPendingGames: {},
      myOldGames: {},
      myGames: {},
      gameCount: -1,
      thisBets: [0.1, 0.5, 1, 5, 10],
      loadGame: true,
      hideOldGames: true,
      hideOldGamesStatus: 'Hide Old Games',
      // ─── Visual state (new — drives the CSS 3D flip) ───────────────────
      // flipped[i] === true → card i shows its face. Driven from firstCard /
      // secondCard / lastCard via revealCards(), with small stagger so the
      // deal feels like a deal.
      flipped: [false, false, false],
      // Final resting tilt (degrees) per card slot. Re-randomized each
      // time a card is dealt so cards never land at the exact same angle
      // twice — feels like a real deal instead of a perfectly aligned
      // grid. Indexed [low(card1), high(card2), target(card3)].
      dealAngles: [0, 0, 0],
      verdict: null, // 'win' | 'pair' | 'loss' | 'rail' | null — sets table glow
      // ─── Demo loop (idle landing animation) ─────────────────────────
      // When the user lands on AD with no active game, we cycle through
      // three pre-scripted deals so the table never reads as "empty".
      // Each scenario ends with a different outcome — WIN, LOSS, RAIL.
      // Stops the moment the user antes up or selects a real game.
      demoActive: false,
      demoStep: 0,
      demoTimers: [],
      // Cache of the deck so the template can resolve face images by index.
      deck: [],
      // ─── Polling indicator state ───────────────────────────────────
      pollSecondsUntilNext: 6, // 6-second poll cadence, counts down to 0
      pollLastAt: 0, // ms timestamp of the most recent successful poll
      pollHeartbeat: 0, // bumped each tick so the template reacts
      pollCountdownInterval: null,
      // ─── Oracle role + contract metadata read from chain ──────────
      adOracleAddress: '', // configured oracle for this AD contract
      adAdminAddress: '',
      myAddress: '', // active wallet, populated when wallet connects
      // ─── In-flight oracle action state (greys buttons during call) ─
      dealing: '', // '' | 'firstCard' | 'secondCard' | 'lastCard'
    }
  },
  created() {
    // Webpack picks these up at build time via require(); the array is the
    // same one the original Three.js implementation used as a texture lookup.
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

    // Socket: original code listened for 'resizeGame' to resize the WebGL
    // canvas. CSS (clamp + flex) handles all of that now, so the handler is a
    // no-op — but we keep the subscription so the server-side fanout still
    // resolves cleanly without errors.
    this.socket.on('resizeGame', (width) => {
      this.resizeGameRender(width)
    })
  },
  mounted() {
    this.blockChainStatus = 'None'
    this.captureMyAddress()
    this.myGameHub()
    this.monitorContract()
    const n_games = Object.keys(toRaw(this.myGames)).length + 1
    this.lastGameId = n_games

    // 1-second ticker that drives the "updated Xs ago · next in Ys"
    // status line under the poker table — purely cosmetic but it
    // reassures the user the dApp is alive during the multi-second
    // gap between chain polls.
    this.pollCountdownInterval = setInterval(() => {
      if (this.pollSecondsUntilNext > 0) this.pollSecondsUntilNext -= 1
      this.pollHeartbeat += 1
    }, 1000)

    if (BLOCKCHAIN_ENABLED) {
      this.pollInterval = setInterval(() => {
        this.monitorContract()
      }, 6000)
    }

    // Start the idle demo loop after the initial chain check has had a
    // moment to settle. If a game is already in progress, startDemo
    // bails out — the player picks up where they left off instead.
    setTimeout(() => this.startDemo(), 1200)
  },
  beforeUnmount() {
    if (this.pollInterval) {
      clearInterval(this.pollInterval)
      this.pollInterval = null
    }
    if (this.pollCountdownInterval) {
      clearInterval(this.pollCountdownInterval)
      this.pollCountdownInterval = null
    }
    this.stopDemo()
  },
  computed: {
    // Active game record (from myGames map keyed by UI gameId).
    activeGame() {
      if (this.gameId === 'NA' || this.gameId == null) return null
      return this.myGames[this.gameId] || null
    },
    // 0=bet placed (no cards), 1=both cards shown, 2=ready for 3rd card,
    // 3=Win, 4=Loss, 5=Pair (half-back refund). Derived from cards/state.
    currentGameStatus() {
      if (this.firstCard < 0 && this.secondCard < 0) return 0
      if (this.lastCard > 0) {
        if (this.verdict === 'win') return 3
        if (this.verdict === 'loss') return 4
        if (this.verdict === 'pair') return 5
        return 2
      }
      // First card dealt but not yet second
      if (this.firstCard >= 0 && this.secondCard < 0) return 0
      return 1
    },
    // True when the connected wallet is the oracle for this contract.
    // Lets us show / hide the manual "Deal card" controls.
    isOracle() {
      return !!this.myAddress && !!this.adOracleAddress &&
        this.myAddress.toLowerCase() === this.adOracleAddress.toLowerCase()
    },
    // True when we have an active game and there's still work for the
    // oracle to do (cards left to deal).
    oracleHasWorkToDo() {
      if (!this.activeGame) return false
      const status = Number(this.activeGame.gameStatus)
      // 0 = need first + second card.  2 = need last card.
      return status === 0 || status === 2
    },
    // Step-by-step prompt that updates as the game progresses.
    statusBanner() {
      const g = this.activeGame
      if (!g) return 'Place a bet to start a game.'
      const status = Number(g.gameStatus)
      if (status === 0) {
        if (this.firstCard < 0) return 'Waiting for the oracle to deal the first card.'
        if (this.secondCard < 0) return 'First card revealed — waiting for the second card.'
        return 'First two cards revealed.'
      }
      if (status === 1) return 'Both cards out. Place your Acey-Duecey bet to draw the third.'
      if (status === 2) return 'Bet locked in. Waiting for the oracle to deal the final card.'
      if (status === 3) return 'You win! Winnings sent to your wallet.'
      if (status === 4) return 'You lost. The pot keeps your bet.'
      if (status === 5) return 'Pair drawn — ante forfeit to the pot.'
      return `Game status: ${status}`
    },
    // Bet sizing — slider runs from 0.1 ꜩ up to 30% of the current pot.
    // The cap mirrors the contract's "Bet Too Big" guard
    // (sp.amount - fee <= self.data.pot) and gives the player a safe
    // ceiling so they don't try to bet more than the contract will
    // accept. 30% is the rule-of-thumb cap suggested by the user.
    betMinTez() {
      return 0.1
    },
    betMaxTez() {
      // potBalance is a formatted string ("0.500"); coerce. Floor at
      // betMinTez so a freshly-deployed contract with a tiny pot still
      // lets you place the minimum bet.
      const pot = Number(this.potBalance) || 0
      const cap = pot * 0.3
      return Math.max(this.betMinTez, Number(cap.toFixed(3)))
    },
    betStepTez() {
      // 100,000 mutez (0.1 ꜩ) increments — matches the contract's
      // mutez precision-of-interest. Slider feels smooth without being
      // sub-millitez precise.
      return 0.05
    },
    // "Updated 2s ago · next check in 4s" — refreshes via pollHeartbeat.
    // When the recurring poll isn't running (BLOCKCHAIN_ENABLED=false or
    // pollInterval never started for any reason), say so explicitly
    // instead of letting the "updated Xs ago" counter run away.
    pollHintText() {
      void this.pollHeartbeat // reactive trigger
      if (!this.pollLastAt) return 'waiting for first poll…'
      const ago = Math.max(0, Math.floor((Date.now() - this.pollLastAt) / 1000))
      if (!this.pollInterval) {
        return `updated ${ago}s ago · auto-polling off`
      }
      const nx = Math.max(0, this.pollSecondsUntilNext)
      return `updated ${ago}s ago · next check in ${nx}s`
    },
    // Card slot ordering left → middle → right: low (firstCard), target
    // (lastCard), high (secondCard). Same on-screen order as the original
    // Three.js scene (card1 at -spacing, card3 at 0, card2 at +spacing).
    slots() {
      return [
        { key: 'low',    deckIdx: this.firstCard,  flipped: this.flipped[0], tilt: this.dealAngles[0] },
        { key: 'target', deckIdx: this.lastCard,   flipped: this.flipped[2], tilt: this.dealAngles[2] },
        { key: 'high',   deckIdx: this.secondCard, flipped: this.flipped[1], tilt: this.dealAngles[1] },
      ]
    },
    // The window of ranks the player needs the third card to land inside.
    // Returns null until both anchor cards are revealed.
    rangeText() {
      const a = rankOf(this.firstCard)
      const b = rankOf(this.secondCard)
      if (a == null || b == null) return null
      const lo = Math.min(a, b)
      const hi = Math.max(a, b)
      const fmt = (r) => RANK_LABELS[r] || r
      if (lo === hi) return `Pair of ${fmt(lo)}s`
      return `Need: between ${fmt(lo)} and ${fmt(hi)}`
    },
    rangeWidthPct() {
      // How wide the in-between range is, as a fraction of the 2..14 span
      // (Aces are always high). Drives the highlighted segment width.
      const a = rankOf(this.firstCard)
      const b = rankOf(this.secondCard)
      if (a == null || b == null) return 0
      const span = Math.max(0, Math.abs(a - b) - 1)
      return Math.round((span / 11) * 100)
    },
    rangeOffsetPct() {
      const a = rankOf(this.firstCard)
      const b = rankOf(this.secondCard)
      if (a == null || b == null) return 0
      const lo = Math.min(a, b)
      return Math.round(((lo - 2) / 12) * 100)
    },
    // Spread = number of ranks strictly between the two anchor cards.
    // 1..11 for non-pairs. The contract pays 12.35 / spread × finalBet
    // on a win (true odds with 5% rake).
    spread() {
      const a = rankOf(this.firstCard)
      const b = rankOf(this.secondCard)
      if (a == null || b == null) return null
      const s = Math.abs(a - b) - 1
      return s > 0 ? s : 0
    },
    // True-odds payout multiplier the contract will pay if card 3 lands
    // strictly between the anchors. (Pair handled separately → 0.)
    payoutMultiplier() {
      if (!this.spread || this.spread < 1) return 0
      return 12.35 / this.spread
    },
    // Expected winnings on a successful third card, given current bet.
    payoutIfWin() {
      if (this.payoutMultiplier <= 0) return 0
      return Number(this.thisBet) * this.payoutMultiplier
    },
    // Probability third card lands in-range (uniform deck draw, ~1/13
    // per rank). Same value the contract uses to set true odds.
    winProbability() {
      if (this.spread == null) return 0
      return this.spread / 13
    },
  },
  methods: {
    // ─── Visual rendering ───────────────────────────────────────────────
    // Lookup the asset URL for a given deck index (or null when face-down).
    // Snap the slider to a fraction of the current max (the 25/50/75/100
    // quick-pick buttons under the slider).
    setBetPercent(pct) {
      const max = this.betMaxTez
      const next = Math.max(this.betMinTez, Number((max * pct / 100).toFixed(3)))
      this.thisBet = next
    },
    cardFaceFor(deckIdx) {
      if (deckIdx == null || deckIdx < 0) return null
      return this.deck[deckIdx] || null
    },
    cardLabel(deckIdx) {
      return shortLabel(deckIdx)
    },
    suitColor(deckIdx) {
      const s = suitOf(deckIdx)
      return s === 1 || s === 2 ? 'red' : 'black'
    },
    // Reveal whichever cards are now known on-chain.
    //
    // CRITICAL: only animate cards that *just became* revealed since the
    // last call. The earlier version reset all three flips to false on
    // every call and then re-flipped them — so every 6-second poll
    // triggered the deal animation again, even if nothing had changed.
    //
    // Now we compute the desired state from chain data and only touch
    // the slots that need to change. Newly-revealed slots get a small
    // stagger so the deal still feels like a deal; slots that should
    // stay face-up just stay face-up (no animation).
    async flipCards() {
      const desired = [
        this.firstCard >= 0,  // slot 0 — low/left
        this.secondCard >= 0, // slot 1 — high/right
        this.lastCard > 0,    // slot 2 — target/middle
      ]

      // Apply face-down transitions immediately (e.g. when starting a new
      // game and the previous game's cards need to flip away).
      const next = [...this.flipped]
      let changed = false
      for (let i = 0; i < 3; i++) {
        if (this.flipped[i] && !desired[i]) {
          next[i] = false
          changed = true
        }
      }
      if (changed) this.flipped = next

      // Stagger any face-up reveals (cards that became known since the
      // last poll). If everything's already up, this loop is a no-op.
      const reveals = []
      for (let i = 0; i < 3; i++) {
        if (desired[i] && !this.flipped[i]) reveals.push(i)
      }
      reveals.forEach((slotIdx, order) => {
        // 250 / 600 / 950 ms — separated enough for the eye to follow,
        // tight enough that the whole deal lands in <1 second.
        const delay = 250 + 350 * order
        setTimeout(() => {
          // Random landing tilt (-9°..+9°) so each card looks tossed
          // by hand rather than snapped onto a grid.
          const tilt = Number(((Math.random() - 0.5) * 18).toFixed(2))
          this.dealAngles = this.dealAngles.map((v, j) => (j === slotIdx ? tilt : v))
          this.flipped = this.flipped.map((v, j) => (j === slotIdx ? true : v))
        }, delay)
      })
    },
    // Wipe any existing reveal — used when a new game starts. Cards
    // animate back off-screen toward the dealer; angles reset so the
    // next deal starts from a clean slate.
    async resetGame() {
      this.flipped = [false, false, false]
      this.dealAngles = [0, 0, 0]
      this.verdict = null
    },
    // ─── Demo loop ──────────────────────────────────────────────────
    // Three pre-scripted scenarios using deck indices (rank = idx/4 + 2,
    // suit = idx % 4). Each ends differently so the player sees the
    // game's full outcome space before they wager a coin.
    demoScenarios() {
      return [
        // WIN: 5♠, J♥ anchors → 8♦ lands inside → win
        { low: 15, high: 38, target: 25, verdict: 'win' },
        // LOSS: 4♣, 9♥ anchors → 2♦ falls below the low card
        { low: 8,  high: 30, target: 1,  verdict: 'loss' },
        // RAIL: 6♣, K♠ anchors → K♥ matches the high anchor exactly
        { low: 16, high: 47, target: 46, verdict: 'rail' },
      ]
    },
    startDemo() {
      // Don't paint over a real game in any state, including in-flight bets.
      if (this.activeGame || this.dealing || this.demoActive || !this.loadGame) return
      this.demoActive = true
      this.demoStep = 0
      this.runDemoStep()
    },
    stopDemo() {
      if (!this.demoActive && !this.demoTimers.length) return
      this.demoActive = false
      this.demoTimers.forEach((id) => clearTimeout(id))
      this.demoTimers = []
      // Wipe the table — the cards animate off, ready for real play.
      this.firstCard = -1
      this.secondCard = -1
      this.lastCard = 0
      this.verdict = null
      this.flipped = [false, false, false]
      this.dealAngles = [0, 0, 0]
    },
    runDemoStep() {
      if (!this.demoActive) return
      const scenarios = this.demoScenarios()
      const s = scenarios[this.demoStep % scenarios.length]
      const tilt = () => Number(((Math.random() - 0.5) * 18).toFixed(2))
      const after = (ms, fn) => {
        this.demoTimers.push(setTimeout(() => {
          if (this.demoActive) fn()
        }, ms))
      }

      // T0: clear the table — cards fly off if any were showing.
      this.firstCard = -1
      this.secondCard = -1
      this.lastCard = 0
      this.verdict = null
      this.flipped = [false, false, false]
      this.dealAngles = [0, 0, 0]

      // 0.55s deal first, 0.55s gap to second, 1.3s to the reveal third
      // — paced so each card lands clearly before the next is tossed.
      after(550, () => {
        this.firstCard = s.low
        this.dealAngles = [tilt(), this.dealAngles[1], this.dealAngles[2]]
        this.flipped = [true, this.flipped[1], this.flipped[2]]
      })
      after(1100, () => {
        this.secondCard = s.high
        this.dealAngles = [this.dealAngles[0], tilt(), this.dealAngles[2]]
        this.flipped = [this.flipped[0], true, this.flipped[2]]
      })
      after(2400, () => {
        this.lastCard = s.target
        this.dealAngles = [this.dealAngles[0], this.dealAngles[1], tilt()]
        this.flipped = [this.flipped[0], this.flipped[1], true]
        this.verdict = s.verdict
      })
      // Hold the verdict for ~3.4s, then advance.
      after(5800, () => {
        this.demoStep++
        this.runDemoStep()
      })
    },
    // Kept for the socket handler. CSS handles real sizing, so this just
    // exists so the listener resolves without throwing.
    resizeGameRender(_width) {
      // intentionally empty — CSS clamp/flex handles layout
    },
    // ─── Contract interaction ────────────────────────────────────────
    async startGameBC() {
      // First user action — kill the idle demo so its timers don't
      // overwrite real game state mid-bet.
      this.stopDemo()
      // Defensive: every bail path updates blockChainStatus so the user
      // never sees a button click produce zero feedback.
      if (!this.wallet) {
        this.blockChainStatus = 'Wallet not initialised yet — refresh the page.'
        console.warn('startGameBC: no wallet on this component')
        return
      }
      let activeAccount
      try {
        activeAccount = await this.wallet.client.getActiveAccount()
      } catch (e) {
        this.blockChainStatus = 'Could not read wallet — try Reset wallet up top.'
        console.error('startGameBC: getActiveAccount failed:', e)
        return
      }
      if (!activeAccount) {
        this.blockChainStatus = 'Connect your wallet first (top of page).'
        console.warn('startGameBC: no active account — wallet not connected')
        return
      }

      // The contract expects `ante + fee` ꜩ. Both come from data() and
      // mirror the on-chain storage values. We log the exact amount to
      // console so it's easy to verify what Taquito is signing.
      const totalBetTez = Number(this.ante) + Number(this.fee)
      const totalBetStr = totalBetTez.toFixed(6)
      console.log(
        `[AD] startGameBC: bet() with amount ${totalBetStr} ꜩ to`,
        AD_CONTRACT_ADDRESS,
      )

      this.loadGame = false
      this.blockChainStatus = `Submitting bet (${totalBetStr} ꜩ)…`
      this.resetGame()
      const n_games = Object.keys(toRaw(this.myGames)).length + 1
      this.gameId = n_games
      this.useWalletProvider()

      try {
        const contract = await this.tezos.wallet.at(AD_CONTRACT_ADDRESS)
        // Deployed AD's `bet` entrypoint takes no parameters now —
        // Aces are always high. Just send the ante + fee.
        const op = await contract.methods
          .bet()
          .send({ amount: totalBetStr })
        this.blockChainStatus = `Bet broadcast — waiting for confirmation (${op.opHash.slice(0, 12)}…)`
        console.log('[AD] startGameBC: op injected', op.opHash)
        await op.confirmation()
        this.blockChainStatus = `Bet confirmed — game ${this.gameId} now waiting for the oracle to deal the first card.`
        await this.monitorContract()
      } catch (err) {
        const msg = err?.message || String(err)
        console.error('Tezos contract call failed:', err)
        if (/aborted|cancel|rejected/i.test(msg)) {
          this.blockChainStatus = 'Bet cancelled in wallet.'
        } else if (/insufficient|balance/i.test(msg)) {
          this.blockChainStatus = 'Insufficient balance — fund the wallet at the shadownet faucet.'
        } else {
          this.blockChainStatus = `Bet failed: ${msg.slice(0, 140)}`
        }
      }
    },
    async continueBetBC() {
      this.stopDemo()
      if (!this.wallet) {
        this.blockChainStatus = 'Wallet not initialised — refresh the page.'
        return
      }
      let activeAccount
      try {
        activeAccount = await this.wallet.client.getActiveAccount()
      } catch (e) {
        this.blockChainStatus = 'Could not read wallet — Reset wallet at top.'
        console.error('continueBetBC: getActiveAccount failed:', e)
        return
      }
      if (!activeAccount) {
        this.blockChainStatus = 'Connect your wallet first.'
        return
      }
      if (!this.myGames[this.gameId]) {
        this.blockChainStatus = 'Pick an active game first.'
        return
      }

      // Entrypoint is continueBet(nat %gameId). Amount is your bet up to
      // the pot; the holder fee (0.1ꜩ) is added on top because the
      // contract subtracts it from sp.amount before crediting the pot.
      const gameBcId = Number(this.myGames[this.gameId].gameId)
      const totalBetTez = Number(this.thisBet) + Number(this.fee)
      const totalBetStr = totalBetTez.toFixed(6)
      console.log(
        `[AD] continueBetBC: continueBet(${gameBcId}) with amount ${totalBetStr} ꜩ`,
      )

      this.blockChainStatus = `Submitting Acey-Duecey bet (${totalBetStr} ꜩ)…`
      this.needsLastCard = true
      this.useWalletProvider()

      try {
        const contract = await this.tezos.wallet.at(AD_CONTRACT_ADDRESS)
        const op = await contract.methods.continueBet(gameBcId).send({ amount: totalBetStr })
        this.blockChainStatus = `Bet broadcast — waiting for confirmation (${op.opHash.slice(0, 12)}…)`
        await op.confirmation()
        this.gameId = Number(this.gameId)
        this.blockChainStatus = `Bet confirmed — game ${this.gameId} waiting for the oracle to deal the final card.`
        await this.monitorContract()
      } catch (err) {
        const msg = err?.message || String(err)
        console.error('Tezos contract call failed:', err)
        if (/aborted|cancel|rejected/i.test(msg)) {
          this.blockChainStatus = 'Bet cancelled in wallet.'
        } else if (/Bet Too Big|betTooBigError/i.test(msg)) {
          this.blockChainStatus = `Bet too big — must be ≤ pot (${this.potBalance} ꜩ).`
        } else if (/bad game/i.test(msg)) {
          this.blockChainStatus = `Game not ready for Acey-Duecey bet (status must be 1).`
        } else {
          this.blockChainStatus = `Bet failed: ${msg.slice(0, 140)}`
        }
      }
    },
    useWalletProvider() {
      this.tezos.setWalletProvider(this.wallet)
    },
    // ─── Oracle entrypoints ──────────────────────────────────────────
    // Called by the AD oracle address (which we set to the test wallet
    // for shadownet). Each call advances the game by one card.
    //
    // The contract expects (card: nat 0..51, gameId: nat, hash: string).
    // `card` is a deck-index; `hash` is whatever string the oracle wants
    // to bind to that card (the secure variant uses a hash of an RNG
    // seed; here we just stamp a random hex for traceability).
    randomCardIndex() {
      // 0..51 — guarantees `params.card` fits the contract's range checks.
      return Math.floor(Math.random() * 52)
    },
    randomHash(prefix) {
      const bytes = new Uint8Array(8)
      crypto.getRandomValues(bytes)
      const hex = Array.from(bytes).map((b) => b.toString(16).padStart(2, '0')).join('')
      return `${prefix}-${hex}`
    },
    async dealFirstCard() {
      return this.dealCard('firstCard')
    },
    async dealSecondCard() {
      return this.dealCard('secondCard')
    },
    async dealLastCard() {
      return this.dealCard('lastCard')
    },
    // Auto-deal: fire firstCard, wait for it, then secondCard. Useful
    // right after a bet so the user doesn't have to click twice.
    async dealOpeningCards() {
      await this.dealCard('firstCard')
      // monitorContract picks up the first card on its next tick; we
      // can immediately fire secondCard because the contract only
      // gates on gameStatus, not on whether card1 is set.
      await this.dealCard('secondCard')
    },
    // Shared body for the three deal-card entrypoints.
    async dealCard(entrypoint) {
      const activeAccount = await this.wallet?.client?.getActiveAccount?.()
      if (!activeAccount) {
        this.blockChainStatus = 'Connect your wallet first.'
        return
      }
      if (!this.activeGame) {
        this.blockChainStatus = 'Pick an active game first.'
        return
      }
      if (!this.isOracle) {
        this.blockChainStatus = 'Only the oracle can deal cards for this contract.'
        return
      }
      const gameBcId = Number(this.activeGame.gameId)
      const card = this.randomCardIndex()
      const hash = this.randomHash(entrypoint)
      this.dealing = entrypoint
      this.blockChainStatus = `Oracle: dealing ${entrypoint} (card #${card}) for game ${gameBcId}…`
      this.useWalletProvider()
      try {
        const contract = await this.tezos.wallet.at(AD_CONTRACT_ADDRESS)
        // All three entrypoints take the same record shape:
        //   { card: nat, gameId: nat, hash: string }
        const op = await contract.methodsObject[entrypoint]({
          card,
          gameId: gameBcId,
          hash,
        }).send()
        await op.confirmation()
        this.blockChainStatus = `Oracle: ${entrypoint} confirmed (card #${card}).`
        this.needsLastCard = entrypoint === 'lastCard' ? false : this.needsLastCard
        await this.monitorContract()
      } catch (err) {
        console.error(`${entrypoint} failed:`, err)
        this.blockChainStatus = `${entrypoint} failed — ${err?.message || 'see console'}.`
      } finally {
        this.dealing = ''
      }
    },
    fetchContractStorage() {
      return getContractStorage(AD_CONTRACT_ADDRESS)
    },
    async getPotBalance() {
      const data = await this.fetchContractStorage()
      if (!data) return
      this.potBalance = Number(data['pot'] * 1e-6).toFixed(3)
      // Keep the slider value in range. If the user picked 0.4 ꜩ but
      // the pot shrunk so max is now 0.2 ꜩ, snap them down.
      if (Number(this.thisBet) > this.betMaxTez) {
        this.thisBet = this.betMaxTez
      }
    },
    // Capture our own active wallet address — used to decide whether
    // we're allowed to act as the oracle for this contract.
    async captureMyAddress() {
      try {
        const account = await this.wallet?.client?.getActiveAccount?.()
        this.myAddress = account?.address || ''
      } catch (_e) {
        this.myAddress = ''
      }
    },
    async getGamesFromContractBC() {
      const activeAccount = await this.wallet.client.getActiveAccount()
      if (!activeAccount) return
      const data = await this.fetchContractStorage()
      if (!data) return
      // Pick up admin / oracle from the contract storage so the UI knows
      // whether to expose the manual deal-card controls.
      this.adAdminAddress = data['admin'] || ''
      this.adOracleAddress = data['oracle'] || ''
      // Stamp the successful poll so the "updated Ns ago" indicator
      // can show fresh time even when no game state changed.
      this.pollLastAt = Date.now()
      this.pollSecondsUntilNext = 6
      this.myGames = {}
      this.myOldGames = {}
      this.myPendingGames = {}
      let i = 0
      // Iterate every on-chain game; keep the ones owned by the active
      // wallet, plus split into pending vs old by gameStatus.
      // (Field name is `gameStatus`, NOT `status` — that was the legacy
      // schema and read as undefined here for months.)
      for (const game in data['games']) {
        const g = data['games'][game]
        if (g.player !== activeAccount.address) continue
        i++
        this.gameCount = i
        const statusN = Number(g.gameStatus)
        const record = {
          gameId: game,
          gameStatus: statusN,
          flipped: false,
        }
        this.myGames[this.gameCount] = record
        if (statusN === 0 || statusN === 1 || statusN === 2) {
          // 0 = bet placed; 1 = cards out, awaiting AD bet; 2 = awaiting final card.
          this.myPendingGames[this.gameCount] = record
        } else if (statusN >= 3) {
          this.myOldGames[this.gameCount] = record
        }
      }
    },
    async loadGameInfo() {
      const data = await this.fetchContractStorage()
      if (!data) return
      const gameBcId = this.myGames[this.gameId]?.gameId
      if (gameBcId == null) return
      const game = data['games'][gameBcId]
      if (!game) return

      // The deployed contract stores cards in a `hand` map keyed by
      // 1/2/3 (NOT card1/card2/card3 — that was the legacy schema).
      // tzkt returns map keys as strings, so index with both shapes
      // to be defensive. `-1` is the contract's "not yet dealt" sentinel.
      const hand = game.hand || {}
      const readSlot = (idx) => {
        const raw = hand[idx] ?? hand[String(idx)]
        const n = Number(raw)
        return Number.isFinite(n) ? n : -1
      }
      this.firstCard = readSlot(1)
      this.secondCard = readSlot(2)
      // Third card: contract uses -1 for "not dealt", but the rest of
      // this component uses `lastCard <= 0` as the gating condition,
      // so flatten -1 → 0 to keep that logic intact.
      const third = readSlot(3)
      this.lastCard = third < 0 ? 0 : third

      // gameStatus (NOT `status` — that field doesn't exist on this contract).
      // Encoded as a number on chain; tzkt returns as a string.
      const status = String(game.gameStatus)
      let gameStatus = ''
      if (status === '0') {
        gameStatus = `Waiting for the oracle to deal cards · game ${this.gameId}`
        this.verdict = null
      } else if (status === '1') {
        gameStatus = `Both cards out · place your Acey-Duecey bet · game ${this.gameId}`
        this.verdict = null
      } else if (status === '2') {
        gameStatus = `Waiting for the oracle to deal the final card · game ${this.gameId}`
        this.verdict = null
      } else if (status === '3') {
        gameStatus = `Game ${this.gameId} — YOU WIN`
        this.verdict = 'win'
      } else if (status === '4') {
        // Contract sets 4 for any non-win outcome of the third card —
        // both rail hits (third card == anchor) and generic outside-the-
        // range losses. Derive which from the actual ranks so the UI
        // labels them correctly: rail-hit ribbon for an exact anchor
        // match, plain LOSS otherwise.
        const r3 = rankOf(this.lastCard)
        const r1 = rankOf(this.firstCard)
        const r2 = rankOf(this.secondCard)
        const isRail = r3 != null && (r3 === r1 || r3 === r2)
        if (isRail) {
          gameStatus = `Game ${this.gameId} — RAIL HIT (third card matched an anchor)`
          this.verdict = 'rail'
        } else {
          gameStatus = `Game ${this.gameId} — LOSS (third card outside the range)`
          this.verdict = 'loss'
        }
      } else if (status === '5') {
        // Contract sets 5 when cards 1+2 match (pair). Ante is full
        // forfeit to the pot — no refund — per the contract's
        // secondCard logic ("# Pair: full forfeit. Ante stays in the
        // pot — no refund to the player, no fee skim.").
        gameStatus = `Game ${this.gameId} — PAIR DRAWN (ante forfeit to the pot)`
        this.verdict = 'pair'
      } else {
        gameStatus = `Game ${this.gameId} — status ${status}`
        this.verdict = null
      }
      this.blockChainStatus = gameStatus
      await this.flipCards()
    },
    async monitorContract() {
      await this.getGamesFromContractBC()
      await this.getPotBalance()
      const n_games = Object.keys(toRaw(this.myGames)).length
      if (Number.isNaN(this.gameId)) return
      if (!this.gameId) return
      if (this.gameId == 'NA') {
        return
      } else if (Number(this.gameId) > n_games) {
        return
      }
      // Refresh card slots from chain whenever the active game still has
      // cards to reveal. Without this, the per-card refresh only fired on
      // game-switch or after continueBet, so worker-dealt firstCard /
      // secondCard sat in storage but stayed hidden in the UI until the
      // user clicked into ACTIVE GAMES.
      const needCardRefresh =
        this.lastGameId !== this.gameId ||
        this.needsLastCard ||
        this.firstCard < 0 ||
        this.secondCard < 0
      if (needCardRefresh) {
        this.loadGameInfo()
      }
      this.lastGameId = this.gameId
      if (this.gameCount < 0) {
        this.blockChainStatus = 'User has no games'
      }
    },
    // ─── Render Interface ────────────────────────────────────────────────
    async setGameId(gameId) {
      this.stopDemo()
      this.gameId = gameId
      this.loadGameInfo()
    },
    async myGameHub() {
      await this.getPotBalance()
      await this.getGamesFromContractBC()
    },
    async showLearnMore() {
      this.showInfo = !this.showInfo
    },
    async toggleOldGames() {
      if (this.hideOldGames) {
        this.hideOldGames = false
        this.hideOldGamesStatus = 'Show Old Games'
      } else {
        this.hideOldGames = true
        this.hideOldGamesStatus = 'Hide Old Games'
      }
    },
    timestamp() {
      const d = new Date()
      const p = (n) => n.toString().padStart(2, '0')
      return `${d.getFullYear()}_${p(d.getMonth() + 1)}_${p(d.getDate())}_${p(d.getHours())}_${p(
        d.getMinutes()
      )}`
    },
  },
}
</script>

<template>
  <div class="canvasContainer">
    <div class="rowFlex">
      <div class="actionButtonHelp" @click="showLearnMore"> HOW TO PLAY </div>
      <div class="infoPopup" v-if="showInfo" @click="showLearnMore">
        <div>
          <ul>
            <li
              class="listItem"
              v-for="(key, value) in gameInfo"
              :key="key"
              :value="value"
            >{{ key }}</li>
          </ul>
        </div>
      </div>
    </div>

    <div class="rowFlex">
      <div class="gameInfo">Game Id: {{ gameId }}</div>
      <div class="gameInfo">Pot Balance: {{ potBalance }} {{ tezosSymbol }}</div>
    </div>
    <!-- True-odds payout preview — visible once both anchor cards are out
         (spread > 0) so the player can see what they'd win before
         clicking continueBet. Replaces the old fixed-2× payout assumption. -->
    <div v-if="spread > 0 && !demoActive" class="adOddsPanel">
      <div class="adOddsRow">
        <span class="adOddsLabel">Spread</span>
        <span class="adOddsValue">{{ spread }} rank{{ spread === 1 ? '' : 's' }}</span>
        <span class="adOddsLabel">Win prob</span>
        <span class="adOddsValue">{{ (winProbability * 100).toFixed(1) }}%</span>
      </div>
      <div class="adOddsRow adOddsRow--main">
        <span class="adOddsLabel">If you win</span>
        <span class="adOddsValuePay">
          {{ payoutMultiplier.toFixed(2) }}× · {{ payoutIfWin.toFixed(3) }} {{ tezosSymbol }}
        </span>
      </div>
      <div class="adOddsHint">
        True odds with 5% house rake. Pairs forfeit the ante outright.
      </div>
    </div>

    <div class="adBetSliderRow">
      <div class="adBetSliderHeader">
        <span class="adBetSliderLabel">Your bet</span>
        <span class="adBetSliderValue">
          {{ Number(thisBet).toFixed(3) }} {{ tezosSymbol }}
        </span>
        <span class="adBetSliderMax">
          max {{ betMaxTez }} {{ tezosSymbol }}
          <span class="adBetSliderMaxHint">(30% of pot)</span>
        </span>
      </div>
      <input
        type="range"
        class="adBetSlider"
        :min="betMinTez"
        :max="betMaxTez"
        :step="betStepTez"
        v-model.number="thisBet"
      />
      <div class="adBetSliderTicks">
        <button
          v-for="pct in [25, 50, 75, 100]"
          :key="pct"
          type="button"
          class="adBetTick"
          @click="setBetPercent(pct)"
          :title="pct + '% of max'"
        >{{ pct }}%</button>
      </div>
    </div>
    <div class="adStatusPanel">
      <div class="adStatusRow adStatusRow--banner">
        <span class="adPulse" aria-hidden="true"></span>
        <span class="adStatusBanner">{{ statusBanner }}</span>
      </div>
      <div class="adStatusRow adStatusRow--detail">
        <span class="adStatusLabel">CHAIN</span>
        <span class="adStatusDetail">{{ blockChainStatus || '—' }}</span>
        <span class="adStatusSpacer"></span>
        <span class="adPollHint">{{ pollHintText }}</span>
      </div>
      <div v-if="activeGame" class="adStatusRow adStatusRow--detail">
        <span class="adStatusLabel">GAME</span>
        <span class="adStatusDetail">
          #{{ gameId }} · status {{ activeGame.gameStatus }}
          · pot {{ potBalance }} ꜩ
        </span>
      </div>
    </div>

    <!-- Oracle controls — visible only when the wallet matches the
         contract's configured oracle address AND a game is in flight. -->
    <div v-if="isOracle && activeGame" class="adOraclePanel">
      <div class="adOracleHeader">
        <span class="adOracleDot"></span>
        <span class="adOracleLabel">ORACLE CONTROLS</span>
        <span class="adOracleHint">
          you are the oracle — advance the game by dealing cards
        </span>
      </div>
      <div class="rowFlex">
        <button
          class="actionButton"
          :disabled="dealing !== '' || Number(activeGame.gameStatus) !== 0 || firstCard >= 0"
          @click="dealFirstCard"
        >
          {{ dealing === 'firstCard' ? 'Dealing first…' : 'Deal first card' }}
        </button>
        <button
          class="actionButton"
          :disabled="dealing !== '' || Number(activeGame.gameStatus) !== 0 || firstCard < 0 || secondCard >= 0"
          @click="dealSecondCard"
        >
          {{ dealing === 'secondCard' ? 'Dealing second…' : 'Deal second card' }}
        </button>
        <button
          class="actionButton"
          :disabled="dealing !== '' || Number(activeGame.gameStatus) !== 2"
          @click="dealLastCard"
        >
          {{ dealing === 'lastCard' ? 'Dealing last…' : 'Deal last card' }}
        </button>
        <button
          class="actionButtonHelp"
          :disabled="dealing !== '' || Number(activeGame.gameStatus) !== 0"
          @click="dealOpeningCards"
          title="Fires firstCard + secondCard back-to-back"
        >
          Auto-deal openers
        </button>
      </div>
    </div>

    <!-- ─── New visual: felt table with three flippable cards ─────────── -->
    <div class="adTableWrap">
      <div :class="['adTable', verdict ? `adTable--${verdict}` : '']">
        <div class="adRail" aria-hidden="true"></div>
        <div class="adFelt">
          <div class="adBrand">ACEY · DUECEY</div>

          <div class="adCardRow">
            <div
              v-for="(slot, i) in slots"
              :key="slot.key + '-' + i"
              :class="['adCardSlot', `adCardSlot--${slot.key}`]"
            >
              <div
                :class="['adCard', { 'adCard--flipped': slot.flipped }]"
                :style="{ '--ad-card-tilt': slot.tilt + 'deg' }"
              >
                <!-- Back face: pure-CSS card back -->
                <div class="adCardFace adCardFace--back">
                  <div class="adBack">
                    <div class="adBackInner">
                      <div class="adBackMark">A<span>·</span>D</div>
                    </div>
                  </div>
                </div>
                <!-- Front face: actual card image when known.
                     The card PNG already shows the rank+suit in its own
                     upper-left corner, so we don't overlay a separate
                     label (avoids the duplicated "K♥" badge issue). -->
                <div class="adCardFace adCardFace--front">
                  <img
                    v-if="cardFaceFor(slot.deckIdx)"
                    :src="cardFaceFor(slot.deckIdx)"
                    :alt="cardLabel(slot.deckIdx)"
                    class="adCardImg"
                    draggable="false"
                  />
                </div>
              </div>
              <div class="adSlotLabel">
                <template v-if="slot.key === 'low'">LOW</template>
                <template v-else-if="slot.key === 'high'">HIGH</template>
                <template v-else>?</template>
              </div>
            </div>
          </div>

          <!-- Range bar: only meaningful once both anchors are flipped. -->
          <div class="adRangeWrap" v-if="rangeText">
            <div class="adRangeText">{{ rangeText }}</div>
            <div class="adRangeBar">
              <div
                class="adRangeFill"
                :style="{ left: rangeOffsetPct + '%', width: rangeWidthPct + '%' }"
              ></div>
              <div class="adRangeTicks">
                <span v-for="t in 14" :key="t"></span>
              </div>
            </div>
          </div>

          <div v-if="verdict === 'win'" class="adVerdict adVerdict--win">YOU WIN</div>
          <div v-else-if="verdict === 'pair'" class="adVerdict adVerdict--pair">PAIR · ANTE LOST</div>
          <div v-else-if="verdict === 'rail'" class="adVerdict adVerdict--rail">RAIL HIT</div>
          <div v-else-if="verdict === 'loss'" class="adVerdict adVerdict--loss">LOST</div>

          <!-- Demo badge — only shown while the idle landing loop runs.
               Disappears the moment the player antes up. -->
          <div v-if="demoActive" class="adDemoBadge">DEMO</div>
        </div>
      </div>
    </div>

    <div class="rowFlex">
      <div class="actionButton" @click="startGameBC">Ante up and play!</div>
      <div class="actionButton" @click="continueBetBC">Bet On Acey Deucey</div>
    </div>

    <div class="gameInfo" @click="myGameHub()">MY GAME HUB</div>
    <div class="rowFlex">
      <div class="gameInfo" v-if="gameCount < 0">No Active Games</div>
      <div class="gameInfo">
        <div class="actionButton"> Active Games </div>
        <div class="rowFlex">
          <div
            class="actionButton"
            @click="setGameId(value)"
            v-for="(key, value) in myPendingGames"
            :key="key"
            :value="value"
          > Game ID: {{ value }} </div>
        </div>
      </div>
      <div class="gameInfo">
        <div class="actionButton" v-if="gameCount >= 0" @click="toggleOldGames()"> {{ hideOldGamesStatus }} </div>
        <div v-if="hideOldGames" class="rowFlex">
          <div
            class="actionButton"
            @click="setGameId(value)"
            v-for="(key, value) in myOldGames"
            :key="key"
            :value="value"
          > Game ID: {{ value }} </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* ─── Casino "scene" ──────────────────────────────────────────────────
   The wrap is the room around the table. Layered radial + linear
   gradients fake an overhead spotlight pooling on the felt, dark wood
   paneling on the side walls, and a soft floor vignette. Sets up a
   shared `perspective` so the table inside can tilt convincingly.

   To drop in a real photo background, replace the `--ad-room-bg`
   custom property below with a `url("…")`. Everything else (rail,
   felt, lighting overlays) layers on top of it. */
.adTableWrap {
  --ad-room-bg:
    /* warm overhead spotlight */
    radial-gradient(ellipse 60% 45% at 50% -10%, rgba(255, 220, 140, 0.30) 0%, transparent 60%),
    /* lower vignette */
    radial-gradient(ellipse 80% 60% at 50% 110%, rgba(0, 0, 0, 0.55) 0%, transparent 65%),
    /* wood paneling stripes — vertical planks, faint */
    repeating-linear-gradient(90deg,
      rgba(0, 0, 0, 0.22) 0px, rgba(0, 0, 0, 0.22) 1px,
      transparent 1px, transparent 36px),
    /* room base: dark walnut */
    linear-gradient(180deg, #1a100a 0%, #2a1a10 45%, #14090a 100%);
  position: relative;
  display: flex;
  justify-content: center;
  align-items: center;
  margin: 8px 0 18px;
  padding: 36px 18px 44px;
  border-radius: 18px;
  background: var(--ad-room-bg);
  perspective: 1400px;
  perspective-origin: 50% -10%;
  overflow: hidden;
  box-shadow:
    inset 0 0 0 1px rgba(255, 255, 255, 0.04),
    inset 0 -40px 60px rgba(0, 0, 0, 0.55);
}
/* Lone overhead bulb glow — sits above the table to push the spotlit
   look. Pure decoration, no DOM node needed. */
.adTableWrap::before {
  content: '';
  position: absolute;
  top: -20px; left: 50%;
  width: 240px; height: 240px;
  transform: translateX(-50%);
  background: radial-gradient(circle, rgba(255, 220, 140, 0.22) 0%, transparent 60%);
  pointer-events: none;
}

/* ─── Table + felt ───────────────────────────────────────────────── */
.adTable {
  position: relative;
  width: clamp(280px, 92vw, 600px);
  aspect-ratio: 16 / 9;
  border-radius: 22px;
  overflow: hidden;
  /* Strong forward tilt so we're really looking down at the table.
     transform-origin pinned to the bottom edge keeps the front rail
     anchored to the floor while the back of the table recedes;
     preserve-3d lets the deal + flip transforms compose with this
     rotation instead of being flattened. */
  transform: rotateX(26deg);
  transform-origin: center bottom;
  transform-style: preserve-3d;
  box-shadow:
    /* table thickness — soft drop on the floor */
    0 26px 44px rgba(0, 0, 0, 0.65),
    0 10px 18px rgba(0, 0, 0, 0.55),
    inset 0 0 0 1px rgba(255, 255, 255, 0.06);
  transition: box-shadow 0.4s ease;
}
.adTable--win {
  box-shadow:
    0 0 0 2px #f5c451,
    0 0 28px 6px rgba(245, 196, 81, 0.55),
    0 26px 44px rgba(0, 0, 0, 0.65),
    0 10px 18px rgba(0, 0, 0, 0.55);
}
.adTable--pair {
  box-shadow:
    0 0 0 2px #d4a24e,
    0 0 22px 4px rgba(212, 162, 78, 0.45),
    0 26px 44px rgba(0, 0, 0, 0.65),
    0 10px 18px rgba(0, 0, 0, 0.55);
}
.adTable--loss {
  box-shadow:
    0 0 0 2px #c4524f,
    0 0 22px 4px rgba(196, 82, 79, 0.45),
    0 26px 44px rgba(0, 0, 0, 0.65),
    0 10px 18px rgba(0, 0, 0, 0.55);
}
/* Rail: lacquered wood ring around the felt. Three stacked layers —
   coarse grain stripes, a fine cross-grain noise, and a warm-to-dark
   diagonal gloss — sell the wood look without an actual texture file. */
.adRail {
  position: absolute;
  inset: 0;
  border-radius: 22px;
  background:
    /* corner highlight + edge shadow */
    radial-gradient(ellipse at 50% 0%, rgba(255, 220, 160, 0.18) 0%, transparent 38%),
    radial-gradient(ellipse at center, transparent 56%, rgba(0, 0, 0, 0.5) 100%),
    /* fine cross-grain */
    repeating-linear-gradient(90deg,
      rgba(0, 0, 0, 0.18) 0px, rgba(0, 0, 0, 0.18) 1px,
      transparent 1px, transparent 4px),
    /* main wood grain */
    repeating-linear-gradient(8deg,
      #3a2214 0px, #4a2c1a 6px, #3a2214 12px, #2a1810 18px),
    /* lacquer base */
    linear-gradient(135deg, #2a1810 0%, #5a3620 50%, #1f120a 100%);
  box-shadow:
    inset 0 1px 0 rgba(255, 220, 160, 0.20),
    inset 0 -2px 6px rgba(0, 0, 0, 0.55);
}
.adFelt {
  position: absolute;
  inset: 18px;
  border-radius: 14px;
  /* Felt: rich green with a hot spot under the overhead light. */
  background:
    radial-gradient(ellipse at 50% 30%, #2a7a4a 0%, #134a2a 55%, #07291a 100%);
  background-image:
    /* fine felt nap — stippled dots */
    radial-gradient(rgba(255, 255, 255, 0.030) 0.6px, transparent 0.6px),
    radial-gradient(rgba(0, 0, 0, 0.10) 0.6px, transparent 0.6px),
    radial-gradient(ellipse at 50% 30%, #2a7a4a 0%, #134a2a 55%, #07291a 100%);
  background-size: 3px 3px, 5px 5px, auto;
  background-position: 0 0, 1px 2px, 0 0;
  box-shadow:
    /* recessed felt — sunken into the wooden rail */
    inset 0 0 0 1px rgba(0, 0, 0, 0.55),
    inset 0 0 0 3px rgba(245, 196, 81, 0.10),  /* gold piping */
    inset 0 8px 22px rgba(0, 0, 0, 0.50),
    inset 0 -4px 12px rgba(0, 0, 0, 0.35);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 10px 12px;
  transform-style: preserve-3d;
}
/* Decorative house-arc on the felt — the white half-circle painted on
   real Acey-Duecey / blackjack tables to mark the dealer's reach. */
.adFelt::before {
  content: '';
  position: absolute;
  left: 50%;
  bottom: -30%;
  width: 120%;
  height: 100%;
  transform: translateX(-50%);
  border-radius: 50%;
  border: 1px solid rgba(255, 255, 255, 0.10);
  box-shadow: 0 0 0 6px rgba(0, 0, 0, 0.10);
  pointer-events: none;
}
.adBrand {
  position: absolute;
  top: 10px;
  left: 50%;
  transform: translateX(-50%);
  letter-spacing: 5px;
  font-size: 11px;
  color: rgba(245, 196, 81, 0.65);
  font-weight: 700;
  text-shadow:
    0 1px 0 rgba(0, 0, 0, 0.6),
    0 0 12px rgba(245, 196, 81, 0.35);
}

/* ─── Card row ────────────────────────────────────────────────────────── */
.adCardRow {
  display: flex;
  flex-direction: row;
  justify-content: center;
  align-items: center;
  gap: clamp(8px, 2.5vw, 22px);
  width: 100%;
  perspective: 1200px; /* shared 3D space — flips share a vanishing point */
  transform-style: preserve-3d;   /* compose with the table's rotateX */
}
.adCardSlot {
  display: flex;
  flex-direction: column;
  align-items: center;
  width: clamp(64px, 18vw, 120px);
  aspect-ratio: 2.5 / 3.5; /* real playing-card proportions */
  position: relative;
  transform-style: preserve-3d;
}
/* The "spot" on the felt — a soft gold halo showing where each card
   will land. Sits OUTSIDE the card footprint (inset: -8px, behind
   the card via z-index: -1) so there is nothing under the rotating
   card to peek through during the spin. This is exactly the geometry
   the target slot already used; we apply it to every slot so cards 1
   and 2 animate identically to card 3 (no blink). */
.adCardSlot::before {
  content: '';
  position: absolute;
  inset: -8px;
  border-radius: 50%;
  background: radial-gradient(
    ellipse at center,
    rgba(245, 196, 81, 0.18) 0%,
    transparent 70%
  );
  pointer-events: none;
  z-index: -1;
  opacity: 1;
  transition: opacity 0.25s ease;
}
.adCardSlot:has(.adCard--flipped)::before { opacity: 0.55; }
/* Soft contact shadow under each card — sells the "cards sitting on
   felt" feel by grounding them on the green surface. Hidden until the
   card has actually landed (the parent slot's adCard--flipped class). */
.adCardSlot::after {
  content: '';
  position: absolute;
  left: 8%;
  right: 8%;
  bottom: -6px;
  height: 14px;
  border-radius: 50%;
  background: radial-gradient(ellipse at center, rgba(0, 0, 0, 0.55) 0%, transparent 70%);
  filter: blur(2px);
  pointer-events: none;
  opacity: 0;
  transition: opacity 0.5s ease 0.4s;
  z-index: -1;
}
.adCardSlot:has(.adCard--flipped)::after { opacity: 1; }
.adCardSlot--target {
  /* The middle card — slightly raised + spotlit so the moment of
     reveal reads as the moment of reveal. The halo (::before) is now
     defined uniformly on .adCardSlot, so we only override the slot
     transform here. */
  transform: translateY(-4px) translateZ(6px);
}
.adSlotLabel {
  position: absolute;
  bottom: -22px;
  left: 50%;
  transform: translateX(-50%);
  font-size: 10px;
  letter-spacing: 2px;
  color: rgba(255, 255, 255, 0.6);
  font-weight: 600;
}

/* ─── The card itself: dealt onto the table ───────────────────────────
   Default state is "in the dealer's hand" — way off-screen, tilted
   sideways, face-down, and invisible. When `.adCard--flipped` is
   applied (chain confirms the card), the card sails in to its slot
   while spinning to face-up; --ad-card-tilt is set per-card so each
   one lands at a slightly different angle, like a real deal. */
.adCard {
  position: absolute;
  inset: 0;
  transform-style: preserve-3d;
  /* Pre-deal: just above and to the right of the slot, rotated ~80°
     around the depth axis (Z), invisible. We DON'T use rotateY for the
     reveal — composed with the table's rotateX(26°) tilt, the rotateY
     180° flip puts both card faces edge-on at intermediate angles
     (backface-visibility hides them simultaneously), so the card looks
     like half of it disappears mid-flip. Z-axis rotation keeps the card
     in its own plane the entire time, so it's continuously visible —
     reads as "tossed face-up onto the table" instead of a card-magic
     reveal. */
  transform:
    translate3d(60%, -60%, 30px)
    rotate(-80deg);
  opacity: 0;
  /* Opacity ramp matches the transform duration so the card doesn't
     hit full-opacity while still mid-rotation (otherwise the rotated
     fully-visible card briefly exposes the slot outline at its corners,
     reading as a flash). */
  transition:
    transform 0.7s cubic-bezier(0.22, 0.78, 0.32, 1.08),
    opacity 0.55s ease-out 0.05s;
  will-change: transform;
}
.adCard--flipped {
  transform:
    translate3d(0, 0, 0)
    rotate(var(--ad-card-tilt, 0deg));
  opacity: 1;
}
.adCardFace {
  position: absolute;
  inset: 0;
  border-radius: 8px;
  overflow: hidden;
  box-shadow:
    0 6px 14px rgba(0, 0, 0, 0.45),
    inset 0 0 0 1px rgba(255, 255, 255, 0.08);
}
/* Back face is kept in the markup (so we can re-introduce a flip later
   if we want) but hidden — the deal animation lands the card face-up
   directly and we no longer use backface-visibility to alternate. */
.adCardFace--back {
  display: none;
}
.adCardFace--front {
  background: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
}
.adCardImg {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
  user-select: none;
  -webkit-user-drag: none;
}
.adCardCorner {
  position: absolute;
  top: 4px;
  left: 6px;
  font-size: 12px;
  font-weight: 700;
  background: rgba(255, 255, 255, 0.85);
  border-radius: 3px;
  padding: 1px 4px;
  line-height: 1;
}
.adCardCorner--red { color: #c4524f; }
.adCardCorner--black { color: #1a1a1a; }
.adCardEmpty {
  font-size: 36px;
  color: #999;
  font-weight: 700;
}

/* ─── Custom CSS card back ────────────────────────────────────────────── */
.adBack {
  width: 100%;
  height: 100%;
  background:
    repeating-linear-gradient(
      45deg,
      #190857 0 8px,
      #2a1577 8px 16px
    );
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 6px;
}
.adBackInner {
  width: 100%;
  height: 100%;
  border: 2px solid rgba(245, 196, 81, 0.85);
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: radial-gradient(
    ellipse at center,
    rgba(25, 8, 87, 0.6) 0%,
    rgba(0, 0, 0, 0.5) 100%
  );
}
.adBackMark {
  font-family: 'EB Garamond', serif;
  font-weight: 700;
  letter-spacing: 2px;
  font-size: clamp(16px, 4.5vw, 28px);
  color: #f5c451;
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.55);
}
.adBackMark span {
  margin: 0 2px;
  opacity: 0.7;
}

/* ─── Range bar ───────────────────────────────────────────────────────
   Absolute-positioned so it can appear/disappear without reflowing the
   felt — otherwise the card row would jump up by ~32px every time the
   second card landed (range bar appears) and back down on demo reset. */
.adRangeWrap {
  position: absolute;
  bottom: 38px;       /* sits above the verdict ribbon at bottom: 10px */
  left: 50%;
  transform: translateX(-50%);
  width: 78%;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  pointer-events: none;
}
.adRangeText {
  font-size: 11px;
  letter-spacing: 1.5px;
  color: rgba(255, 255, 255, 0.85);
  text-transform: uppercase;
}
.adRangeBar {
  position: relative;
  width: 100%;
  height: 8px;
  border-radius: 4px;
  background: rgba(0, 0, 0, 0.35);
  overflow: hidden;
  box-shadow: inset 0 1px 2px rgba(0, 0, 0, 0.5);
}
.adRangeFill {
  position: absolute;
  top: 0;
  bottom: 0;
  background: linear-gradient(90deg, #f5c451, #d4a24e);
  border-radius: 4px;
  transition: left 0.4s ease, width 0.4s ease;
}
.adRangeTicks {
  position: absolute;
  inset: 0;
  display: flex;
  justify-content: space-between;
  pointer-events: none;
}
.adRangeTicks span {
  width: 1px;
  background: rgba(255, 255, 255, 0.1);
}

/* ─── Verdict ribbon ──────────────────────────────────────────────────── */
.adVerdict {
  position: absolute;
  bottom: 10px;
  left: 50%;
  transform: translateX(-50%);
  font-size: 13px;
  letter-spacing: 4px;
  font-weight: 700;
  padding: 4px 14px;
  border-radius: 4px;
  border: 1px solid currentColor;
  animation: adVerdictIn 0.5s ease-out both;
}
.adVerdict--win {
  color: #f5c451;
  background: rgba(245, 196, 81, 0.12);
}
.adVerdict--pair {
  color: #d4a24e;
  background: rgba(212, 162, 78, 0.12);
}
.adVerdict--loss {
  color: #c4524f;
  background: rgba(196, 82, 79, 0.12);
}
/* Rail hit — the third card landed exactly on one of the anchors.
   Distinct from a generic loss so the demo loop's three outcomes
   read as visibly different. Orange, sits between gold and red. */
.adVerdict--rail {
  color: #ff8a3d;
  background: rgba(255, 138, 61, 0.14);
}
/* Demo badge — small pill in the top-right of the felt that signals
   "this is a preview, not your money". Auto-fades alongside the
   demo loop the moment the player takes any real action. */
.adDemoBadge {
  position: absolute;
  top: 10px;
  right: 14px;
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 3px;
  color: rgba(245, 196, 81, 0.85);
  padding: 3px 8px;
  border: 1px solid rgba(245, 196, 81, 0.45);
  border-radius: 4px;
  background: rgba(0, 0, 0, 0.35);
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.6);
  animation: adDemoPulse 2.4s ease-in-out infinite;
  pointer-events: none;
}
@keyframes adDemoPulse {
  0%, 100% { opacity: 0.55; }
  50%      { opacity: 1; }
}
@keyframes adVerdictIn {
  from { opacity: 0; transform: translate(-50%, 8px); }
  to { opacity: 1; transform: translate(-50%, 0); }
}

/* Mobile: tighten the row a little so all three cards fit on a 320px screen */
@media (max-width: 380px) {
  .adCardRow { gap: 6px; }
  .adBrand { font-size: 8px; letter-spacing: 2px; }
}

/* ─── True-odds preview panel ─────────────────────────────────────── */
.adOddsPanel {
  margin: 8px 0;
  padding: 10px 14px;
  border-radius: 10px;
  background: linear-gradient(
    135deg,
    rgba(124, 58, 237, 0.10) 0%,
    rgba(245, 196, 81, 0.08) 100%
  );
  border: 1px solid rgba(245, 196, 81, 0.35);
  box-shadow: 0 0 0 1px rgba(245, 196, 81, 0.10), 0 4px 18px rgba(124, 58, 237, 0.15);
  animation: adOddsFadeIn 0.35s ease-out;
}
@keyframes adOddsFadeIn {
  from { opacity: 0; transform: translateY(-4px); }
  to   { opacity: 1; transform: translateY(0); }
}
.adOddsRow {
  display: flex;
  align-items: baseline;
  gap: 8px;
  flex-wrap: wrap;
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
}
.adOddsRow--main {
  margin-top: 4px;
  padding-top: 6px;
  border-top: 1px solid rgba(255, 255, 255, 0.08);
}
.adOddsLabel {
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: rgba(243, 241, 238, 0.55);
  font-size: 10px;
}
.adOddsValue {
  color: var(--ad-text-1, #f3f1ee);
  font-weight: 600;
  margin-right: 12px;
}
.adOddsValuePay {
  font-size: 16px;
  font-weight: 700;
  background: linear-gradient(135deg, #ffe089 0%, #f5c451 50%, #d4a24e 100%);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}
.adOddsHint {
  margin-top: 4px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  color: rgba(243, 241, 238, 0.40);
  letter-spacing: 0.04em;
}

/* ─── Bet slider ───────────────────────────────────────────────────── */
.adBetSliderRow {
  margin: 8px 0;
  padding: 10px 14px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.08);
}
.adBetSliderHeader {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin-bottom: 6px;
  font-family: 'JetBrains Mono', ui-monospace, monospace;
}
.adBetSliderLabel {
  font-size: 10px;
  letter-spacing: 2px;
  text-transform: uppercase;
  color: rgba(255, 255, 255, 0.55);
}
.adBetSliderValue {
  font-size: 18px;
  font-weight: 700;
  color: #f5c451;
  text-shadow: 0 0 12px rgba(245, 196, 81, 0.35);
}
.adBetSliderMax {
  margin-left: auto;
  font-size: 11px;
  color: rgba(255, 255, 255, 0.55);
}
.adBetSliderMaxHint {
  margin-left: 4px;
  font-size: 9px;
  letter-spacing: 1px;
  opacity: 0.65;
}
.adBetSlider {
  width: 100%;
  height: 22px;
  appearance: none;
  -webkit-appearance: none;
  background: transparent;
  cursor: pointer;
  margin: 0;
}
.adBetSlider::-webkit-slider-runnable-track {
  height: 6px;
  border-radius: 999px;
  background: linear-gradient(90deg, #f5c451, #c4524f);
  box-shadow: inset 0 1px 2px rgba(0, 0, 0, 0.6);
}
.adBetSlider::-moz-range-track {
  height: 6px;
  border-radius: 999px;
  background: linear-gradient(90deg, #f5c451, #c4524f);
  box-shadow: inset 0 1px 2px rgba(0, 0, 0, 0.6);
}
.adBetSlider::-webkit-slider-thumb {
  appearance: none;
  -webkit-appearance: none;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: radial-gradient(circle at 30% 30%, #fff4cc, #f5c451 60%, #a06c12);
  border: 1px solid #7a4f08;
  margin-top: -6px;
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.5);
  cursor: grab;
}
.adBetSlider::-moz-range-thumb {
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: radial-gradient(circle at 30% 30%, #fff4cc, #f5c451 60%, #a06c12);
  border: 1px solid #7a4f08;
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.5);
  cursor: grab;
}
.adBetSliderTicks {
  display: flex;
  gap: 6px;
  margin-top: 8px;
}
.adBetTick {
  flex: 1;
  padding: 4px 8px;
  border-radius: 6px;
  border: 1px solid rgba(255, 255, 255, 0.12);
  background: rgba(255, 255, 255, 0.03);
  color: rgba(255, 255, 255, 0.75);
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 10px;
  letter-spacing: 1px;
  cursor: pointer;
  transition: background 0.15s ease, border-color 0.15s ease;
}
.adBetTick:hover {
  background: rgba(245, 196, 81, 0.10);
  border-color: rgba(245, 196, 81, 0.55);
  color: #f5c451;
}

/* ─── Status + oracle panels ───────────────────────────────────────── */
.adStatusPanel {
  margin: 8px 0;
  padding: 10px 12px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.08);
  font-size: 12.5px;
}
.adStatusRow {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.adStatusRow + .adStatusRow {
  margin-top: 6px;
  padding-top: 6px;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
}
.adStatusRow--banner .adStatusBanner {
  font-size: 13px;
  font-weight: 600;
  color: #f3f1ee;
  flex: 1;
}
.adStatusRow--detail {
  color: rgba(255, 255, 255, 0.7);
  font-size: 11.5px;
}
.adStatusLabel {
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 9px;
  letter-spacing: 2px;
  font-weight: 700;
  color: rgba(245, 196, 81, 0.7);
  padding: 1px 6px;
  border: 1px solid rgba(245, 196, 81, 0.3);
  border-radius: 4px;
}
.adStatusDetail { flex: 0 1 auto; }
.adStatusSpacer { flex: 1; }
.adPollHint {
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 10px;
  color: rgba(255, 255, 255, 0.45);
}
.adPulse {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: #f5c451;
  box-shadow: 0 0 8px rgba(245, 196, 81, 0.8);
  animation: adPulse 1.2s ease-in-out infinite;
}
@keyframes adPulse {
  0%, 100% { opacity: 0.4; transform: scale(0.85); }
  50%      { opacity: 1;   transform: scale(1.1); }
}

.adOraclePanel {
  margin: 8px 0 12px;
  padding: 10px 12px;
  border-radius: 10px;
  background: linear-gradient(180deg, rgba(124, 58, 237, 0.12), rgba(124, 58, 237, 0.04));
  border: 1px dashed rgba(167, 139, 250, 0.55);
}
.adOracleHeader {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
  font-size: 11px;
}
.adOracleDot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #a78bfa;
  box-shadow: 0 0 6px rgba(167, 139, 250, 0.7);
}
.adOracleLabel {
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  letter-spacing: 2px;
  font-weight: 700;
  color: #a78bfa;
}
.adOracleHint {
  color: rgba(255, 255, 255, 0.5);
  font-style: italic;
  font-size: 10.5px;
}
.adOraclePanel button[disabled] {
  opacity: 0.45;
  cursor: not-allowed;
}
</style>
