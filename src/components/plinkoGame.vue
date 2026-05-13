<script>
// Plinko — single-player luck against the house pot.
//
// Flow:
//   1. Player picks (rows, risk) and a bet size, clicks DROP.
//   2. Contract's play(rows, risk) records a pending round + holder fee.
//   3. Oracle worker observes the new round, calls resolve(roundId, slot, seed)
//      with a random slot 0..rows. Contract settles inline.
//   4. UI polls the contract every 5s; when our round flips from
//      roundStatus=0 → 1/2/3, we animate the ball drop and show the payout.
//
// On-chain is the source of truth. The ball animation is decoration — it
// always lands in whatever slot the contract picked.

import {
  PLINKO_CONTRACT_ADDRESS,
  PLINKO_GAME_INFO,
  PLINKO_MULTIPLIERS,
  BLOCKCHAIN_ENABLED,
} from '../constants'
import { getContractStorage } from '../services/tzkt'

const ROW_OPTIONS = [8, 12, 16]
const RISK_LABELS = { 0: 'Low', 1: 'Medium', 2: 'High' }

function easeOutCubic(t) { return 1 - Math.pow(1 - t, 3) }
function easeInOutSine(t) { return -(Math.cos(Math.PI * t) - 1) / 2 }

// Given a final slot index and a row count, generate a plausible left/right
// path for the ball. Each row, the ball moves L (+0) or R (+1) in column.
// We shuffle so the visual path looks random.
function pathForSlot(slot, rows) {
  const moves = new Array(rows).fill(0)
  for (let i = 0; i < slot; i++) moves[i] = 1
  for (let i = moves.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1))
    ;[moves[i], moves[j]] = [moves[j], moves[i]]
  }
  return moves
}

export default {
  name: 'plinkoGame',
  props: ['socket', 'wallet', 'tezos'],
  data() {
    return {
      info: PLINKO_GAME_INFO,
      rowOptions: ROW_OPTIONS,
      RISK_LABELS,                   // exposed for template lookup
      rows: 8,
      risk: 0,
      bet: 0.1,
      fee: 0.1,
      minBet: 0.1,
      maxBet: 1.0,
      potBalance: 0,
      reserveBalance: 0,
      myAddress: '',
      rounds: {},
      myRoundIds: [],
      activeRoundId: null,
      lastSeenStatus: 0,
      ball: null,
      ballSettleAt: 0,
      animationFrame: 0,
      ballTick: 0,                   // bumped each rAF to force position recompute
      blockchainStatus: 'Idle.',
      dropping: false,
      pollInterval: null,
      pollLastAt: 0,
      pollCountdownInterval: null,
      pollSecondsUntilNext: 5,
    }
  },
  computed: {
    riskLabel() { return RISK_LABELS[this.risk] || '?' },
    multipliers() {
      return (PLINKO_MULTIPLIERS[this.rows] || {})[this.risk] || []
    },
    slots() { return this.rows + 1 },
    canDrop() {
      return (
        !this.dropping &&
        BLOCKCHAIN_ENABLED &&
        this.bet >= this.minBet &&
        this.bet <= this.maxBet
      )
    },
    betSliderMax() {
      const dyn = Number((this.potBalance * 0.3).toFixed(3))
      return Math.max(this.minBet, Math.min(this.maxBet, dyn || this.maxBet))
    },
    activeRound() {
      if (this.activeRoundId == null) return null
      return this.rounds[this.activeRoundId] || null
    },
    pollHint() {
      if (!this.pollInterval) return 'Auto-polling off.'
      return `Next chain check in ${this.pollSecondsUntilNext}s`
    },
    boardWidth() { return 380 },
    boardHeight() { return 360 },
    boardPadX() { return 26 },
    boardPadY() { return 24 },
    fieldHeight() { return this.boardHeight - this.boardPadY * 2 - 36 },
    pegRadius() { return Math.max(2.5, 7 - this.rows * 0.18) },
    rowSpacing() { return this.fieldHeight / (this.rows + 1) },
    columnSpacing() {
      return (this.boardWidth - this.boardPadX * 2) / (this.rows + 1)
    },
    pegPositions() {
      const out = []
      for (let r = 0; r < this.rows; r++) {
        const y = this.boardPadY + (r + 1) * this.rowSpacing
        const pegsThisRow = r + 2
        const rowWidth = (pegsThisRow - 1) * this.columnSpacing
        const startX = (this.boardWidth - rowWidth) / 2
        for (let p = 0; p < pegsThisRow; p++) {
          out.push({ x: startX + p * this.columnSpacing, y })
        }
      }
      return out
    },
    bucketPositions() {
      const out = []
      const totalWidth = this.slots * this.columnSpacing
      const startX = (this.boardWidth - totalWidth) / 2
      const y = this.boardPadY + (this.rows + 1) * this.rowSpacing + 8
      for (let s = 0; s < this.slots; s++) {
        out.push({
          x: startX + s * this.columnSpacing + this.columnSpacing / 2,
          y,
        })
      }
      return out
    },
    ballPosition() {
      // ballTick referenced so Vue re-evaluates each frame
      this.ballTick // eslint-disable-line no-unused-expressions
      if (!this.ball) return null
      const elapsed = (performance.now() - this.ball.t0) / 1000
      const totalRows = this.ball.path.length
      const totalDuration = 0.18 * totalRows + 0.35
      const tNorm = Math.min(1, elapsed / totalDuration)
      const rowsTraversed = Math.min(totalRows, tNorm * (totalRows + 1))
      const rowIdx = Math.floor(rowsTraversed)
      const intraRow = rowsTraversed - rowIdx
      let col = 0
      for (let i = 0; i < rowIdx; i++) col += this.ball.path[i]
      const nextStep = rowIdx < totalRows ? this.ball.path[rowIdx] : 0
      const colNow = col + nextStep * easeOutCubic(intraRow)
      const xCenter = this.boardWidth / 2
      const xOffset = (colNow - totalRows / 2) * this.columnSpacing
      const x = xCenter + xOffset
      const yStart = this.boardPadY
      const yEnd = this.boardPadY + (totalRows + 1) * this.rowSpacing
      const y = yStart + (yEnd - yStart) * easeInOutSine(tNorm)
      return { x, y, done: tNorm >= 1 }
    },
  },
  created() {
    this.captureMyAddress()
    this.refresh()
    this.startPolling()
  },
  beforeUnmount() {
    if (this.pollInterval) clearInterval(this.pollInterval)
    if (this.pollCountdownInterval) clearInterval(this.pollCountdownInterval)
    if (this.animationFrame) cancelAnimationFrame(this.animationFrame)
  },
  methods: {
    async captureMyAddress() {
      try {
        const acct = await this.wallet?.client?.getActiveAccount?.()
        this.myAddress = acct?.address || ''
      } catch (_e) { /* noop */ }
    },
    startPolling() {
      this.pollInterval = setInterval(() => this.refresh(), 5000)
      this.pollCountdownInterval = setInterval(() => {
        const elapsed = (Date.now() - (this.pollLastAt || Date.now())) / 1000
        this.pollSecondsUntilNext = Math.max(0, Math.round(5 - elapsed))
      }, 500)
    },
    async refresh() {
      this.pollLastAt = Date.now()
      this.pollSecondsUntilNext = 5
      let storage
      try {
        storage = await getContractStorage(PLINKO_CONTRACT_ADDRESS)
      } catch (e) {
        console.warn('plinko refresh failed:', e?.message)
        return
      }
      if (!storage) return
      this.rounds = storage.rounds || {}
      this.potBalance = Number((Number(storage.pot || 0) * 1e-6).toFixed(3))
      this.reserveBalance = Number((Number(storage.potReserve || 0) * 1e-6).toFixed(3))
      this.minBet = Number((Number(storage.minBet || 100000) * 1e-6).toFixed(3))
      this.maxBet = Number((Number(storage.maxBet || 1000000) * 1e-6).toFixed(3))
      this.fee = Number((Number(storage.fee || 100000) * 1e-6).toFixed(3))
      if (this.bet > this.betSliderMax) this.bet = this.betSliderMax

      if (!this.myAddress) await this.captureMyAddress()
      if (this.myAddress) {
        const ids = Object.keys(this.rounds)
          .filter((id) => this.rounds[id].player === this.myAddress)
          .map((id) => Number(id))
          .sort((a, b) => b - a)
        this.myRoundIds = ids
        if (this.activeRoundId == null && ids.length) {
          this.activeRoundId = ids[0]
          this.lastSeenStatus = Number(this.rounds[ids[0]].roundStatus)
        }
        const active = this.activeRound
        if (active) {
          const status = Number(active.roundStatus)
          if (status !== 0 && this.lastSeenStatus === 0) {
            this.animateBall(Number(active.rows), Number(active.finalSlot))
            this.blockchainStatus = this.summarizeResolve(active)
          }
          this.lastSeenStatus = status
        }
      }
    },
    summarizeResolve(r) {
      const status = Number(r.roundStatus)
      const payout = Number(r.payout || 0) * 1e-6
      const bet = Number(r.bet || 0) * 1e-6
      if (status === 1) {
        const ratio = (bet > 0 ? payout / bet : 0).toFixed(2)
        return `Win! Landed slot ${r.finalSlot} for ${payout.toFixed(3)} ꜩ (${ratio}×).`
      }
      if (status === 2) return `Push — got your bet back (${payout.toFixed(3)} ꜩ).`
      if (status === 3) return `Loss. Slot ${r.finalSlot} paid ${payout.toFixed(3)} ꜩ.`
      return 'Resolved.'
    },
    setBetPercent(pct) {
      const max = this.betSliderMax
      const val = Number(((max - this.minBet) * (pct / 100) + this.minBet).toFixed(3))
      this.bet = Math.max(this.minBet, Math.min(max, val))
    },
    animateBall(rows, slot) {
      this.ball = {
        rows,
        slot,
        path: pathForSlot(slot, rows),
        t0: performance.now(),
      }
      this.ballSettleAt = performance.now() + (0.18 * rows + 0.5) * 1000
      const tick = () => {
        if (!this.ball) return
        this.ballTick++
        const pos = this.ballPosition
        if (pos?.done) {
          if (performance.now() > this.ballSettleAt + 500) {
            this.ball = null
            this.animationFrame = 0
            return
          }
        }
        this.animationFrame = requestAnimationFrame(tick)
      }
      cancelAnimationFrame(this.animationFrame)
      this.animationFrame = requestAnimationFrame(tick)
    },
    multClassFor(i) {
      const m = this.multipliers[i]
      if (m == null) return 'mult--mid'
      if (m >= 5) return 'mult--high'
      if (m < 1) return 'mult--low'
      return 'mult--mid'
    },
    bucketFill(i) {
      const m = this.multipliers[i]
      if (m == null) return 'rgba(255,255,255,0.06)'
      if (m >= 5) return 'rgba(245, 196, 81, 0.35)'
      if (m >= 1.5) return 'rgba(167, 139, 250, 0.30)'
      if (m < 1) return 'rgba(196, 82, 79, 0.25)'
      return 'rgba(255,255,255,0.10)'
    },
    isBucketHit(i) {
      const a = this.activeRound
      if (!a) return false
      return Number(a.finalSlot) === i && Number(a.roundStatus) !== 0
    },
    useWalletProvider() { this.tezos.setWalletProvider(this.wallet) },
    async drop() {
      if (!this.canDrop) return
      if (!this.wallet) { this.blockchainStatus = 'Wallet not initialised — refresh.'; return }
      let acct
      try { acct = await this.wallet.client.getActiveAccount() }
      catch (e) { this.blockchainStatus = 'Wallet read failed — try Reset wallet.'; return }
      if (!acct) { this.blockchainStatus = 'Connect your wallet first.'; return }
      const totalTez = Number(this.bet) + Number(this.fee)
      const totalStr = totalTez.toFixed(6)
      this.useWalletProvider()
      this.dropping = true
      this.blockchainStatus = `Submitting drop (${totalStr} ꜩ)…`
      try {
        const contract = await this.tezos.wallet.at(PLINKO_CONTRACT_ADDRESS)
        const op = await contract.methodsObject.play({
          rows: this.rows,
          risk: this.risk,
        }).send({ amount: totalStr })
        this.blockchainStatus = `Broadcast — waiting for confirmation (${op.opHash.slice(0, 12)}…)`
        await op.confirmation()
        this.blockchainStatus = 'Drop confirmed — waiting for oracle to settle.'
        await this.refresh()
        if (this.myRoundIds.length) {
          this.activeRoundId = this.myRoundIds[0]
          this.lastSeenStatus = 0
        }
      } catch (err) {
        const msg = err?.message || String(err)
        console.error('plinko drop failed:', err)
        if (/aborted|cancel|denied/i.test(msg)) {
          this.blockchainStatus = 'Drop cancelled in wallet.'
        } else if (/bet too big/i.test(msg)) {
          this.blockchainStatus = 'Bet too big — try lower.'
        } else if (/bet too small/i.test(msg)) {
          this.blockchainStatus = `Bet too small — min ${this.minBet} ꜩ.`
        } else {
          this.blockchainStatus = `Drop failed: ${msg.slice(0, 140)}`
        }
      } finally {
        this.dropping = false
      }
    },
  },
}
</script>

<template>
  <div class="plinkoRoot">
    <div class="plinkoHeader">
      <div class="plinkoTitle">PLINKO</div>
      <div class="plinkoSub">{{ riskLabel }} risk · {{ rows }} rows · pot {{ potBalance }} ꜩ</div>
    </div>

    <div class="controlsGrid">
      <div class="controlRow">
        <label class="ctrlLabel">Rows</label>
        <div class="segmented">
          <button
            v-for="r in rowOptions"
            :key="r"
            :class="['segBtn', rows === r ? 'segBtn--on' : '']"
            @click="rows = r"
          >{{ r }}</button>
        </div>
      </div>

      <div class="controlRow">
        <label class="ctrlLabel">Risk</label>
        <div class="segmented">
          <button :class="['segBtn', risk === 0 ? 'segBtn--on' : '']" @click="risk = 0">Low</button>
          <button :class="['segBtn', risk === 1 ? 'segBtn--on' : '']" @click="risk = 1">Med</button>
          <button :class="['segBtn risk--hi', risk === 2 ? 'segBtn--on' : '']" @click="risk = 2">High</button>
        </div>
      </div>

      <div class="controlRow">
        <label class="ctrlLabel">Bet</label>
        <div class="betSliderWrap">
          <input
            type="range"
            class="betSlider"
            :min="minBet"
            :max="betSliderMax"
            step="0.05"
            v-model.number="bet"
          />
          <div class="betValue">{{ bet.toFixed(3) }} ꜩ</div>
        </div>
      </div>
      <div class="controlRow">
        <label class="ctrlLabel"></label>
        <div class="quickPicks">
          <button class="quickBtn" @click="setBetPercent(25)">25%</button>
          <button class="quickBtn" @click="setBetPercent(50)">50%</button>
          <button class="quickBtn" @click="setBetPercent(75)">75%</button>
          <button class="quickBtn" @click="setBetPercent(100)">Max</button>
        </div>
      </div>

      <div class="controlRow controlRow--cta">
        <button
          :class="['dropBtn', canDrop ? '' : 'dropBtn--off', dropping ? 'dropBtn--busy' : '']"
          :disabled="!canDrop"
          @click="drop"
        >
          <span v-if="dropping">DROPPING…</span>
          <span v-else>DROP BALL · {{ (bet + fee).toFixed(3) }} ꜩ</span>
        </button>
      </div>
    </div>

    <div class="boardFrame">
      <svg :viewBox="`0 0 ${boardWidth} ${boardHeight}`" class="board">
        <defs>
          <radialGradient id="boardBg" cx="50%" cy="0%" r="100%">
            <stop offset="0%" stop-color="#1a1438" />
            <stop offset="100%" stop-color="#04030f" />
          </radialGradient>
          <radialGradient id="pegGlow" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stop-color="#ffe089" />
            <stop offset="100%" stop-color="#d4a24e" />
          </radialGradient>
          <radialGradient id="ballGrad" cx="35%" cy="30%" r="65%">
            <stop offset="0%" stop-color="#ffffff" />
            <stop offset="60%" stop-color="#f5c451" />
            <stop offset="100%" stop-color="#a04300" />
          </radialGradient>
        </defs>
        <rect x="0" y="0" :width="boardWidth" :height="boardHeight" fill="url(#boardBg)" rx="14" />

        <circle
          v-for="(p, i) in pegPositions"
          :key="`peg-${i}`"
          :cx="p.x"
          :cy="p.y"
          :r="pegRadius"
          fill="url(#pegGlow)"
          class="peg"
        />

        <rect
          v-for="(b, i) in bucketPositions"
          :key="`bkt-${i}`"
          :x="b.x - columnSpacing / 2 + 2"
          :y="b.y"
          :width="columnSpacing - 4"
          height="24"
          :class="['bucket', isBucketHit(i) ? 'bucket--hit' : '']"
          :fill="bucketFill(i)"
          rx="4"
        />
        <text
          v-for="(b, i) in bucketPositions"
          :key="`mlt-${i}`"
          :x="b.x"
          :y="b.y + 16"
          text-anchor="middle"
          :class="['multLabel', multClassFor(i)]"
        >{{ (multipliers[i] != null ? multipliers[i] : 1).toString().replace(/\.0$/, '') }}×</text>

        <circle
          v-if="ballPosition"
          :cx="ballPosition.x"
          :cy="ballPosition.y"
          r="6"
          fill="url(#ballGrad)"
          class="ball"
        />
      </svg>
    </div>

    <div class="statusPanel">
      <div class="statusLine">{{ blockchainStatus }}</div>
      <div class="statusMeta">
        <span class="metaPill">{{ pollHint }}</span>
        <span class="metaPill">pot {{ potBalance }} ꜩ</span>
        <span class="metaPill">reserve {{ reserveBalance }} ꜩ</span>
      </div>
    </div>

    <div v-if="myRoundIds.length" class="recentRounds">
      <div class="recentHdr">RECENT DROPS</div>
      <div class="recentList">
        <div
          v-for="id in myRoundIds.slice(0, 8)"
          :key="id"
          :class="['recentItem', `recent--${rounds[id]?.roundStatus}`]"
          @click="activeRoundId = id"
        >
          <span class="recentId">#{{ id }}</span>
          <span class="recentSpec">{{ rounds[id]?.rows }}r · {{ RISK_LABELS[Number(rounds[id]?.risk)] || '?' }}</span>
          <span class="recentSlot">slot {{ rounds[id]?.finalSlot }}</span>
          <span class="recentPay">{{ ((Number(rounds[id]?.payout || 0)) * 1e-6).toFixed(3) }} ꜩ</span>
        </div>
      </div>
    </div>

    <div class="infoBlock">
      <div v-for="(line, i) in info" :key="i" class="infoLine">· {{ line }}</div>
    </div>
  </div>
</template>

<style scoped>
.plinkoRoot {
  display: flex; flex-direction: column; gap: 14px;
  padding: 16px;
  max-width: 480px; margin: 0 auto;
  color: var(--ad-text-1);
}

.plinkoHeader { text-align: center; }
.plinkoTitle {
  font-family: var(--ad-font-display);
  font-size: 28px;
  letter-spacing: 0.12em;
  background: var(--ad-grad-fire);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}
.plinkoSub {
  font-family: var(--ad-font-mono);
  font-size: 11px;
  color: var(--ad-text-3);
  letter-spacing: 0.08em;
  text-transform: uppercase;
  margin-top: 2px;
}

.controlsGrid {
  display: flex; flex-direction: column; gap: 8px;
  background: var(--ad-bg-elev-1);
  border: 1px solid var(--ad-border-soft);
  border-radius: var(--ad-r-md);
  padding: 12px;
}
.controlRow { display: flex; align-items: center; gap: 12px; }
.ctrlLabel {
  min-width: 50px;
  font-family: var(--ad-font-mono);
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--ad-text-3);
}
.segmented {
  display: flex; gap: 4px; flex: 1;
  background: var(--ad-bg-elev-2);
  border-radius: var(--ad-r-pill);
  padding: 3px;
}
.segBtn {
  flex: 1; border: 0;
  background: transparent;
  color: var(--ad-text-2);
  padding: 6px 10px;
  font-family: var(--ad-font-mono);
  font-size: 12px;
  border-radius: var(--ad-r-pill);
  cursor: pointer;
  transition: background 0.15s ease, color 0.15s ease, transform 0.15s ease;
}
.segBtn:hover { color: var(--ad-text-1); transform: translateY(-1px); }
.segBtn--on {
  background: var(--ad-grad-violet);
  color: #fff;
  box-shadow: var(--ad-glow-violet);
}
.segBtn.risk--hi.segBtn--on { background: var(--ad-grad-fire); box-shadow: var(--ad-glow-gold); }

.betSliderWrap { display: flex; align-items: center; flex: 1; gap: 12px; }
.betSlider {
  flex: 1; appearance: none; -webkit-appearance: none;
  height: 4px;
  background: linear-gradient(90deg, var(--ad-violet-3), var(--ad-gold-2));
  border-radius: 999px;
  outline: none;
}
.betSlider::-webkit-slider-thumb {
  -webkit-appearance: none;
  width: 18px; height: 18px;
  background: var(--ad-grad-gold);
  border-radius: 50%;
  cursor: pointer;
  box-shadow: var(--ad-glow-gold);
}
.betSlider::-moz-range-thumb {
  width: 18px; height: 18px;
  background: var(--ad-grad-gold);
  border-radius: 50%;
  cursor: pointer;
  border: 0;
}
.betValue {
  font-family: var(--ad-font-mono);
  font-size: 13px;
  color: var(--ad-gold-1);
  min-width: 76px; text-align: right;
}
.quickPicks { display: flex; gap: 6px; flex: 1; }
.quickBtn {
  flex: 1;
  background: var(--ad-bg-elev-2);
  border: 1px solid var(--ad-border-soft);
  border-radius: var(--ad-r-sm);
  color: var(--ad-text-2);
  font-family: var(--ad-font-mono);
  font-size: 11px;
  padding: 5px 0;
  cursor: pointer;
  transition: all 0.15s ease;
}
.quickBtn:hover {
  background: var(--ad-bg-elev-3);
  color: var(--ad-gold-1);
  border-color: var(--ad-gold-3);
}

.controlRow--cta { justify-content: center; }
.dropBtn {
  width: 100%;
  background: var(--ad-grad-fire);
  border: 0;
  border-radius: var(--ad-r-md);
  color: #1a0c00;
  font-family: var(--ad-font-display);
  font-size: 18px;
  letter-spacing: 0.08em;
  padding: 12px 18px;
  cursor: pointer;
  box-shadow: var(--ad-glow-gold);
  transition: transform 0.12s ease, box-shadow 0.2s ease;
}
.dropBtn:hover:not(:disabled) { transform: translateY(-1px); }
.dropBtn:active:not(:disabled) { transform: translateY(0); }
.dropBtn--off {
  background: var(--ad-bg-elev-2);
  color: var(--ad-text-3);
  box-shadow: none;
  cursor: not-allowed;
}
.dropBtn--busy { animation: dropPulse 1.2s ease-in-out infinite; }
@keyframes dropPulse {
  0%, 100% { box-shadow: 0 0 0 0 rgba(245, 196, 81, 0.6); }
  50%      { box-shadow: 0 0 0 8px rgba(245, 196, 81, 0); }
}

.boardFrame {
  background: var(--ad-bg-elev-1);
  border: 1px solid var(--ad-border-soft);
  border-radius: var(--ad-r-lg);
  padding: 8px;
}
.board { width: 100%; display: block; }
.peg { filter: drop-shadow(0 0 2px rgba(245, 196, 81, 0.4)); }
.ball { filter: drop-shadow(0 2px 6px rgba(245, 196, 81, 0.7)); }
.bucket { transition: filter 0.2s ease; }
.bucket--hit { animation: bucketHit 0.9s ease-out; }
@keyframes bucketHit {
  0%   { filter: brightness(1.0) drop-shadow(0 0 0 transparent); }
  30%  { filter: brightness(1.8) drop-shadow(0 0 12px var(--ad-gold-1)); }
  100% { filter: brightness(1.1) drop-shadow(0 0 4px var(--ad-gold-3)); }
}
.multLabel {
  font-family: var(--ad-font-mono);
  font-size: 9px;
  fill: var(--ad-text-2);
}
.mult--low  { fill: var(--ad-red-1); }
.mult--mid  { fill: var(--ad-text-2); }
.mult--high { fill: var(--ad-gold-1); font-weight: 700; }

.statusPanel {
  background: var(--ad-bg-elev-1);
  border: 1px solid var(--ad-border-soft);
  border-radius: var(--ad-r-md);
  padding: 10px 12px;
}
.statusLine {
  font-family: var(--ad-font-body);
  font-size: 13px;
  color: var(--ad-text-1);
}
.statusMeta { display: flex; gap: 6px; margin-top: 6px; flex-wrap: wrap; }
.metaPill {
  font-family: var(--ad-font-mono);
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  padding: 3px 8px;
  background: var(--ad-bg-elev-2);
  border-radius: var(--ad-r-pill);
  color: var(--ad-text-3);
}

.recentRounds {
  background: var(--ad-bg-elev-1);
  border: 1px solid var(--ad-border-soft);
  border-radius: var(--ad-r-md);
  padding: 8px 12px;
}
.recentHdr {
  font-family: var(--ad-font-mono);
  font-size: 10px;
  letter-spacing: 0.1em;
  color: var(--ad-text-3);
  text-transform: uppercase;
  margin-bottom: 6px;
}
.recentList { display: flex; flex-direction: column; gap: 4px; }
.recentItem {
  display: flex; gap: 8px; align-items: center;
  padding: 5px 8px;
  background: var(--ad-bg-elev-2);
  border-radius: var(--ad-r-sm);
  font-family: var(--ad-font-mono);
  font-size: 11px;
  color: var(--ad-text-2);
  cursor: pointer;
  transition: background 0.15s ease, transform 0.15s ease;
}
.recentItem:hover { background: var(--ad-bg-elev-3); transform: translateX(2px); }
.recentId   { min-width: 32px; color: var(--ad-text-3); }
.recentSpec { min-width: 60px; }
.recentSlot { min-width: 52px; }
.recentPay  { margin-left: auto; }
.recent--1 { color: var(--ad-green-1); }
.recent--3 { color: var(--ad-red-1); }
.recent--2 { color: var(--ad-text-2); }
.recent--0 { color: var(--ad-violet-1); font-style: italic; }

.infoBlock {
  font-family: var(--ad-font-mono);
  font-size: 11px;
  color: var(--ad-text-3);
  line-height: 1.55;
}
.infoLine { padding: 1px 0; }
</style>
