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
      view: 'landing', // 'landing' | 'play'
      showRules: false,
      myAddress: '',
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
        const targetId = this.activeGameId ?? Math.max(0, this.currentGameId - 1)
        this.activeGameId = targetId
        this.game = storage.games?.[targetId] || null
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
    // Admin-only: spin up a new Squares game on-chain.
    // The exact contract method shape isn't fully defined in this repo yet
    // (smart_contract_squares_v2.py lives elsewhere), so this calls the
    // most likely entrypoint name and surfaces any error to status.
    async createGame() {
      if (!this.isAdmin) return
      const activeAccount = await this.wallet.client.getActiveAccount()
      if (!activeAccount) return
      this.tezos.setWalletProvider(this.wallet)
      this.blockchainStatus = 'Creating new game...'
      try {
        const contract = await this.tezos.wallet.at(SQUARES_CONTRACT_ADDRESS)
        const op = await contract.methodsObject.createGame().send()
        await op.confirmation()
        this.blockchainStatus = 'New game created.'
        await this.refreshState()
      } catch (err) {
        console.error('createGame failed:', err)
        this.blockchainStatus = 'createGame failed — check contract entrypoint name'
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

      <!-- Past games quick-jump (only render if more than one exists). -->
      <div class="rowFlex" v-if="currentGameId > 1">
        <div class="gameInfo sqGamesLabel">Past games:</div>
        <div
          v-for="n in currentGameId"
          :key="n"
          :class="['actionButton', activeGameId === n - 1 ? 'sqGameBtnActive' : '']"
          @click="selectGameId(n - 1)"
        >
          #{{ n - 1 }}
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

      <!-- Admin actions — only shown to ADMIN_ADDRESS. -->
      <div v-if="isAdmin" class="sqAdminPanel">
        <div class="sqAdminLabel">Admin</div>
        <div class="rowFlex">
          <div class="actionButton" @click="createGame">Create new game</div>
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
