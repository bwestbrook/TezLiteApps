<script>
// Plinko 3D — single-player luck against the house pot.
//
// Flow:
//   1. Player picks (rows, risk) and a bet size, clicks DROP.
//   2. Contract's play(rows, risk) records a pending round + holder fee.
//   3. Oracle worker observes the new round, calls
//      resolve(roundId, xBits, zBits, seed) — `rows` coin-flips on each
//      of two axes. Contract derives finalX/finalZ, the Chebyshev `ring`
//      distance from centre, looks up the radial multiplier, settles.
//   4. UI polls every 5s; when our round flips roundStatus 0 → 1/2/3 we
//      animate the 3D drop and show the payout.
//
// 3D model: the ball tumbles down a peg pyramid. Each layer it deflects
// ±1 on X AND ±1 on Z, so after `rows` layers it sits on a
// (rows+1)×(rows+1) grid — centre bin overwhelmingly likely, corners
// exponentially rare. Payout is RADIAL: it depends only on the ring
// distance from centre. On-chain is the source of truth; the animation
// always lands on whatever (finalX,finalZ) the contract recorded.
//
// Rendering: SVG with software 3D projection — same approach as
// tttGameGrid.vue (Three.js was dropped for WebGL-sandbox flakiness).

import {
  PLINKO_CONTRACT_ADDRESS,
  PLINKO_GAME_INFO,
  PLINKO_MULTIPLIERS,
  BLOCKCHAIN_ENABLED,
} from '../constants'
import { getContractStorage } from '../services/tzkt'

const ROW_OPTIONS = [8, 12, 16]
const RISK_LABELS = { 0: 'Low', 1: 'Medium', 2: 'High' }

// World-space layout constants (lattice units → SVG units). The viewBox
// is auto-fitted to the projected geometry, so these only set the
// relative proportions of the board.
const SP = 10    // horizontal spacing between adjacent lattice columns
const LH = 12    // vertical drop per pyramid layer
const BIN_DROP = 9 // extra fall from the last layer down into the bin tray

// Camera angles (radians). Pitch is FIXED — it tilts the pyramid
// forward so you see down into it, and never changes. Drag rotates
// `yaw` only: the board spins about its vertical axis like a Christmas
// tree on a turntable, never tumbling or rolling.
const FIXED_PITCH = 0.52
const DEFAULT_YAW = -0.42
const DRAG_SENSITIVITY = 0.011   // radians of yaw per pixel dragged

function easeOutCubic(t) { return 1 - Math.pow(1 - t, 3) }

// Decode a per-layer bit map from contract storage into a flat 0/1
// array. tzkt returns map values as strings — coerce to numbers.
function bitsFromStoragePath(rawPath, rows) {
  const out = []
  const src = rawPath || {}
  for (let i = 0; i < rows; i++) {
    const v = src[i] != null ? src[i] : src[String(i)]
    out.push(Number(v || 0))
  }
  return out
}

export default {
  name: 'plinkoGame',
  props: ['socket', 'wallet', 'tezos'],
  data() {
    return {
      info: PLINKO_GAME_INFO,
      showInfo: false,
      rowOptions: ROW_OPTIONS,
      RISK_LABELS,
      rows: 8,
      risk: 0,
      bet: 0.1,
      fee: 0.1,
      minBet: 0.1,
      maxBet: 10.0,
      potBalance: 0,
      reserveBalance: 0,
      myAddress: '',
      rounds: {},
      myRoundIds: [],
      activeRoundId: null,
      lastSeenStatus: 0,
      // ball: { rows, xBits, zBits, finalX, finalZ, t0 } | null
      ball: null,
      ballSettleAt: 0,
      ballLanded: false,
      animationFrame: 0,
      ballTick: 0,
      blockchainStatus: 'Idle.',
      dropping: false,
      pollInterval: null,
      pollLastAt: 0,
      pollCountdownInterval: null,
      pollSecondsUntilNext: 5,
      // ── Camera — drag spins the board on its vertical axis ───────
      // pitch is fixed; only yaw changes (turntable rotation).
      pitch: FIXED_PITCH,
      yaw: DEFAULT_YAW,
      drag: null,   // { startX, startYaw } while dragging
    }
  },
  computed: {
    riskLabel() { return RISK_LABELS[this.risk] || '?' },
    // Ring-indexed multiplier array: index 0 = centre bin … rows/2 = corner.
    multipliers() {
      return (PLINKO_MULTIPLIERS[this.rows] || {})[this.risk] || []
    },
    half() { return Math.floor(this.rows / 2) },
    canDrop() {
      return (
        !this.dropping &&
        BLOCKCHAIN_ENABLED &&
        !!this.wallet &&
        this.bet >= this.minBet &&
        this.bet <= this.maxBet
      )
    },
    cantDropReason() {
      if (this.dropping) return 'Drop already in flight…'
      if (!BLOCKCHAIN_ENABLED) return 'Blockchain calls disabled in constants.js.'
      if (!this.wallet) return 'Connect your wallet to drop.'
      if (this.bet < this.minBet) return `Bet too small — min ${this.minBet} ꜩ.`
      if (this.bet > this.maxBet) return `Bet too big — max ${this.maxBet} ꜩ.`
      return ''
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
    pegRadius() { return Math.max(1.1, 2.4 - this.rows * 0.05) },
    // 20% smaller than the previous sizing — still scales down on the
    // denser 12/16-row boards. The sparse 8-row board gets a further 20%
    // trim so the ball doesn't read as oversized against the wide gaps.
    ballRadius() {
      const base = Math.max(2.08, (5.6 - this.rows * 0.13) * 0.8)
      return this.rows === 8 ? base * 0.8 : base
    },
    // ── Pyramid skin pegs ──────────────────────────────────────────
    // Rendering every lattice point of every layer would be ~1800
    // circles for 16 rows. We render only the "skin" — the perimeter
    // of each layer's grid — which reads as a clean 3D pyramid lattice
    // at a fraction of the element count. Sorted far→near so SVG paints
    // back-to-front.
    pegs3d() {
      const out = []
      for (let d = 1; d <= this.rows; d++) {
        for (let c = 0; c <= d; c++) {
          for (let e = 0; e <= d; e++) {
            // skin only: on the boundary of this layer's c×e grid
            if (c !== 0 && c !== d && e !== 0 && e !== d) continue
            const p = this.project(...this.worldOf(c, e, d))
            out.push({ x: p.x, y: p.y, depth: p.depth })
          }
        }
      }
      out.sort((a, b) => a.depth - b.depth)
      return out
    },
    // ── Bin grid ───────────────────────────────────────────────────
    // (rows+1)×(rows+1) cells at the bottom. Each is a projected quad
    // filled with its ring's rainbow hue. On land the WHOLE winning
    // ring lights up — payout is radial, so the ring is what you won.
    bins3d() {
      const out = []
      const a = this.activeRound
      const hitRing = a ? Number(a.ring) : -1
      const hitLive = !!a && Number(a.roundStatus) !== 0 && this.ballLanded
      for (let X = 0; X <= this.rows; X++) {
        for (let Z = 0; Z <= this.rows; Z++) {
          const ring = Math.max(Math.abs(X - this.half), Math.abs(Z - this.half))
          // four corners of the cell, projected
          const corners = [
            [X - 0.5, Z - 0.5], [X + 0.5, Z - 0.5],
            [X + 0.5, Z + 0.5], [X - 0.5, Z + 0.5],
          ].map(([cx, cz]) => {
            const p = this.project(...this.worldOf(cx, cz, this.rows, BIN_DROP))
            return `${p.x.toFixed(2)},${p.y.toFixed(2)}`
          })
          const center = this.project(...this.worldOf(X, Z, this.rows, BIN_DROP))
          out.push({
            X, Z, ring,
            points: corners.join(' '),
            cx: center.x, cy: center.y, depth: center.depth,
            mult: this.multipliers[ring],
            hit: hitLive && ring === hitRing,
          })
        }
      }
      out.sort((a, b) => a.depth - b.depth)
      return out
    },
    // Rotation-INVARIANT viewBox. As yaw spins, every world point
    // traces a circle of radius hypot(wx,wz) about the central axis
    // (the vertical line through the apex AND the centre bin — both sit
    // at world x=z=0). If we re-fit the box to the current yaw the
    // board appears to zoom/drift; instead we size the box to hold the
    // geometry at ANY yaw, so rotation is pure spin-in-place.
    //   x  ∈ [-R, +R]                    R = max hypot(wx,wz)
    //   y2 = wy·cosP − z1·sinP,  z1 ∈ [-r, r]  → y2 ∈ [wy·cosP ± r·sinP]
    // Depends only on `rows` + the fixed pitch — never on yaw.
    viewBox() {
      const cpit = Math.cos(this.pitch), spit = Math.sin(this.pitch)
      let maxR = 0, yMin = Infinity, yMax = -Infinity
      const consider = (wx, wy, wz) => {
        const r = Math.hypot(wx, wz)
        if (r > maxR) maxR = r
        const yc = wy * cpit
        if (yc - r * spit < yMin) yMin = yc - r * spit
        if (yc + r * spit > yMax) yMax = yc + r * spit
      }
      // The envelope is pinned by the apex (top, narrowest) and the bin
      // tray's outer-corner cells (bottom, widest) — every peg layer
      // sits inside that.
      consider(0, 0, 0)
      for (const X of [-0.5, this.rows + 0.5]) {
        for (const Z of [-0.5, this.rows + 0.5]) {
          const w = this.worldOf(X, Z, this.rows, BIN_DROP)
          consider(w[0], w[1], w[2])
        }
      }
      const pad = 8
      const xExt = maxR + pad
      const h = (yMax - yMin) + pad * 2
      return `${(-xExt).toFixed(1)} ${(yMin - pad).toFixed(1)} ${(2 * xExt).toFixed(1)} ${h.toFixed(1)}`
    },
    // Screen-space basis vectors for the bin floor plane, given the
    // current camera. eX/eZ are where one WORLD unit along the floor's
    // X / Z axes lands on screen. Used as an affine transform so the
    // payout labels are skewed INTO the floor plane — they read as
    // painted on the board, foreshortening + flipping as it spins.
    //   screen.x = wx·cosY + wz·sinY
    //   screen.y = wy·cosP + wx·sinY·sinP − wz·cosY·sinP
    planeBasis() {
      const cyaw = Math.cos(this.yaw), syaw = Math.sin(this.yaw)
      const spit = Math.sin(this.pitch)
      return {
        ex: { x: cyaw, y: syaw * spit },
        ez: { x: syaw, y: -cyaw * spit },
      }
    },
    // Two payout labels per ring, on opposite (east/west) sides — ring
    // 0 is the single centre cell. Each is anchored in its cell's
    // low-X/low-Z corner (where two sides meet) and gets skewed into
    // the floor plane via planeBasis in the template.
    binLabels3d() {
      const out = []
      for (let ring = 0; ring <= this.half; ring++) {
        const mult = this.multipliers[ring]
        if (mult == null) continue
        const cells = ring === 0
          ? [[this.half, this.half]]
          : [[this.half + ring, this.half], [this.half - ring, this.half]]
        for (const [X, Z] of cells) {
          const a = this.project(
            ...this.worldOf(X - 0.46, Z - 0.42, this.rows, BIN_DROP),
          )
          out.push({ lx: a.x, ly: a.y, mult })
        }
      }
      return out
    },
    // Tiny label font (world units — the plane transform scales it).
    // Deliberately small per the spec; nudges up a hair on denser
    // boards since the viewBox grows with row count.
    labelFontSize() { return 1.9 + this.rows * 0.05 },
    // ── Ball position — projected, per frame ───────────────────────
    ballPosition() {
      this.ballTick // eslint-disable-line no-unused-expressions
      // Resting: parked at the pyramid apex.
      if (!this.ball) {
        const p = this.project(...this.worldOf(0, 0, 0))
        return { sx: p.x, sy: p.y, depth: p.depth, scale: 1, spin: 0, resting: true, done: true }
      }
      const { xBits, zBits, rows, t0 } = this.ball
      const elapsed = (performance.now() - t0) / 1000
      // ~0.30s per layer + a 0.6s tail. 16-row drop ≈ 5.4s.
      const totalDuration = 0.30 * rows + 0.6
      const tNorm = Math.min(1, elapsed / totalDuration)
      const SETTLE = 0.6                       // fraction of a layer for the tray drop
      const u = tNorm * (rows + SETTLE)         // 0 .. rows+SETTLE

      let world
      if (u <= rows) {
        // Walking the pyramid. Which layer-segment are we in?
        const layer = Math.min(rows - 1, Math.floor(u))
        const intra = u - layer
        const ease = easeOutCubic(intra)
        // accumulated grid position at the top of this segment
        let xc = 0, zc = 0
        for (let i = 0; i < layer; i++) { xc += xBits[i]; zc += zBits[i] }
        const nx = xBits[layer], nz = zBits[layer]
        const w0 = this.worldOf(xc, zc, layer)
        const w1 = this.worldOf(xc + nx, zc + nz, layer + 1)
        // X/Z ease smoothly toward the next column; Y is the literal
        // fall plus a small mid-segment hop so it reads as a bounce.
        const wx = w0[0] + (w1[0] - w0[0]) * ease
        const wz = w0[2] + (w1[2] - w0[2]) * ease
        const hop = Math.sin(intra * Math.PI) * LH * 0.16
        const wy = w0[1] + (w1[1] - w0[1]) * intra - hop
        world = [wx, wy, wz]
      } else {
        // Settling into the bin tray at (finalX, finalZ).
        const s = Math.min(1, (u - rows) / SETTLE)
        const top = this.worldOf(this.ball.finalX, this.ball.finalZ, rows)
        const wy = top[1] + BIN_DROP * (1 - Math.pow(1 - s, 2))
        world = [top[0], wy, top[2]]
      }
      const p = this.project(...world)
      // Subtle depth perspective + a spin that runs while it falls.
      const scale = 1 + p.depth * 0.012
      const spin = (elapsed * 540) % 360       // 1.5 rev/s — "for fun"
      return {
        sx: p.x, sy: p.y, depth: p.depth, scale, spin,
        resting: false, done: tNorm >= 1,
      }
    },
    // Pegs split at the ball's depth so the ball is correctly occluded:
    // pegs further from the camera render BEFORE the ball, nearer pegs
    // render AFTER it. pegs3d is already depth-sorted ascending, so this
    // is a cheap filter. Recomputes per frame via ballTick (in
    // ballPosition) — fine, it's just comparisons over ~550 entries.
    pegsBehindBall() {
      const bd = this.ballPosition.depth
      return this.pegs3d.filter((p) => p.depth <= bd)
    },
    pegsInFrontBall() {
      const bd = this.ballPosition.depth
      return this.pegs3d.filter((p) => p.depth > bd)
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
    // World coords for lattice point (c,e) at pyramid depth `d`. The
    // layer is centred on the Y axis so the pyramid is symmetric; the
    // optional `yExtra` pushes a point further down (used for the bin
    // tray sitting below the last peg layer).
    worldOf(c, e, d, yExtra = 0) {
      return [
        (c - d / 2) * SP,        // wx
        d * LH + yExtra,         // wy (down is +)
        (e - d / 2) * SP,        // wz
      ]
    },
    // Software 3D projection: yaw about the vertical axis, then pitch
    // about the horizontal. Orthographic — `depth` is the rotated Z,
    // used for back-to-front sort, ball occlusion, and a faint
    // perspective scale. pitch/yaw are reactive (drag to rotate).
    project(wx, wy, wz) {
      const cyaw = Math.cos(this.yaw), syaw = Math.sin(this.yaw)
      const cpit = Math.cos(this.pitch), spit = Math.sin(this.pitch)
      const x1 = wx * cyaw + wz * syaw
      const z1 = -wx * syaw + wz * cyaw
      const y2 = wy * cpit - z1 * spit
      const z2 = wy * spit + z1 * cpit
      return { x: x1, y: y2, depth: z2 }
    },
    // ── Drag-to-rotate (turntable: yaw only) ───────────────────────
    // Pointer events cover mouse + touch. We capture the pointer so the
    // drag keeps tracking even if it leaves the SVG. Only horizontal
    // movement matters — it spins the board about its vertical axis.
    onBoardPointerDown(ev) {
      this.drag = { startX: ev.clientX, startYaw: this.yaw }
      try { ev.target.setPointerCapture(ev.pointerId) } catch (_e) { /* noop */ }
    },
    onBoardPointerMove(ev) {
      if (!this.drag) return
      const dx = ev.clientX - this.drag.startX
      // Turntable spin: horizontal drag → yaw. Pitch never changes, so
      // the board rotates like a Christmas tree on a stand.
      this.yaw = this.drag.startYaw + dx * DRAG_SENSITIVITY
    },
    onBoardPointerUp(ev) {
      this.drag = null
      try { ev.target.releasePointerCapture(ev.pointerId) } catch (_e) { /* noop */ }
    },
    resetCamera() {
      this.yaw = DEFAULT_YAW
    },
    // Full-rainbow colour per ring: red at the centre ring, sweeping
    // through orange/yellow/green/blue to magenta at the corners. Every
    // ring gets its own clearly-distinct hue.
    ringColor(ring, alpha = 0.85) {
      const span = Math.max(1, this.half)
      const t = Math.min(1, ring / span)          // 0 = centre … 1 = corner
      const hue = t * 300                         // 0° red → 300° magenta
      return `hsla(${hue.toFixed(0)}, 80%, 55%, ${alpha})`
    },
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
      this.maxBet = Number((Number(storage.maxBet || 10000000) * 1e-6).toFixed(3))
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
            const rows = Number(active.rows)
            // Snap the board to the round's geometry so the projected
            // pyramid + bin grid match the path being replayed.
            if (this.rows !== rows) this.rows = rows
            const r = Number(active.risk)
            if (Number.isFinite(r) && this.risk !== r) this.risk = r
            this.animateBall(
              rows,
              bitsFromStoragePath(active.xPath, rows),
              bitsFromStoragePath(active.zPath, rows),
            )
            this.blockchainStatus = this.summarizeResolve(active)
          }
          this.lastSeenStatus = status
        }
      }
    },
    // Click handler for the "recent drops" list — selects the round and
    // replays its 3D drop. Pending rounds (status 0) just get selected.
    replayRound(id) {
      this.activeRoundId = id
      const r = this.rounds[id]
      if (!r) return
      const status = Number(r.roundStatus)
      this.lastSeenStatus = status
      if (status === 0) {
        this.blockchainStatus = `Round #${id} still pending oracle resolve.`
        return
      }
      const rows = Number(r.rows)
      if (this.rows !== rows) this.rows = rows
      const rsk = Number(r.risk)
      if (Number.isFinite(rsk) && this.risk !== rsk) this.risk = rsk
      this.animateBall(
        rows,
        bitsFromStoragePath(r.xPath, rows),
        bitsFromStoragePath(r.zPath, rows),
      )
      this.blockchainStatus = `Replaying round #${id} — ${this.summarizeResolve(r)}`
    },
    summarizeResolve(r) {
      const status = Number(r.roundStatus)
      const payout = Number(r.payout || 0) * 1e-6
      const bet = Number(r.bet || 0) * 1e-6
      const at = `(${r.finalX},${r.finalZ}) ring ${r.ring}`
      if (status === 1) {
        const ratio = (bet > 0 ? payout / bet : 0).toFixed(2)
        return `Win! Landed ${at} for ${payout.toFixed(3)} ꜩ (${ratio}×).`
      }
      if (status === 2) return `Push — got your bet back (${payout.toFixed(3)} ꜩ).`
      if (status === 3) return `Loss. ${at} paid ${payout.toFixed(3)} ꜩ.`
      return 'Resolved.'
    },
    setBetPercent(pct) {
      const max = this.betSliderMax
      const val = Number(((max - this.minBet) * (pct / 100) + this.minBet).toFixed(3))
      this.bet = Math.max(this.minBet, Math.min(max, val))
    },
    // User picked a new board size. Drop any parked / in-flight ball so it
    // isn't left rendered against the old row geometry.
    setRows(r) {
      if (this.rows === r) return
      this.rows = r
      this.resetBall()
    },
    // Stop the rAF loop and clear all ball state back to "no ball".
    resetBall() {
      cancelAnimationFrame(this.animationFrame)
      this.animationFrame = 0
      this.ball = null
      this.ballLanded = false
      this.ballSettleAt = 0
    },
    animateBall(rows, xBits, zBits) {
      const finalX = xBits.reduce((a, b) => a + b, 0)
      const finalZ = zBits.reduce((a, b) => a + b, 0)
      this.ballLanded = false
      this.ball = { rows, xBits, zBits, finalX, finalZ, t0: performance.now() }
      this.ballSettleAt = performance.now() + (0.30 * rows + 0.6) * 1000
      const tick = () => {
        if (!this.ball) return
        this.ballTick++
        const pos = this.ballPosition
        if (pos?.done) {
          if (performance.now() > this.ballSettleAt + 500) {
            // Touchdown: stop the rAF loop but keep `this.ball` set so
            // the ball stays parked in its bin. Flipping ballLanded
            // lights the winning cell.
            this.ballLanded = true
            this.animationFrame = 0
            return
          }
        }
        this.animationFrame = requestAnimationFrame(tick)
      }
      cancelAnimationFrame(this.animationFrame)
      this.animationFrame = requestAnimationFrame(tick)
    },
    useWalletProvider() { this.tezos.setWalletProvider(this.wallet) },
    async drop() {
      console.debug('[plinko] drop clicked', {
        canDrop: this.canDrop,
        wallet: !!this.wallet,
        bet: this.bet, fee: this.fee, rows: this.rows, risk: this.risk,
      })
      if (!this.canDrop) {
        this.blockchainStatus = this.cantDropReason || 'Drop unavailable right now.'
        return
      }
      this.blockchainStatus = 'Reading wallet…'
      let acct
      try {
        acct = await this.wallet.client.getActiveAccount()
      } catch (e) {
        console.error('[plinko] getActiveAccount failed:', e)
        this.blockchainStatus = 'Wallet read failed — try Reset wallet.'
        return
      }
      if (!acct) {
        this.blockchainStatus = 'Connect your wallet first (click the SYNC WALLET button).'
        return
      }
      const totalTez = Number(this.bet) + Number(this.fee)
      const totalStr = totalTez.toFixed(6)
      this.dropping = true
      this.blockchainStatus = `Submitting drop (${totalStr} ꜩ)… check your wallet to approve.`
      try {
        this.useWalletProvider()
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
        console.error('[plinko] drop failed:', err)
        if (/aborted|cancel|denied/i.test(msg)) {
          this.blockchainStatus = 'Drop cancelled in wallet.'
        } else if (/bet too big/i.test(msg)) {
          this.blockchainStatus = 'Bet too big — try lower.'
        } else if (/bet too small/i.test(msg)) {
          this.blockchainStatus = `Bet too small — min ${this.minBet} ꜩ.`
        } else if (/setWalletProvider|not a function/i.test(msg)) {
          this.blockchainStatus = 'Wallet provider missing — refresh the page.'
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
      <div class="plinkoTitle">PLINKO 3D</div>
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
            @click="setRows(r)"
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
      <svg
        :viewBox="viewBox"
        :class="['board', drag ? 'board--dragging' : '']"
        @pointerdown="onBoardPointerDown"
        @pointermove="onBoardPointerMove"
        @pointerup="onBoardPointerUp"
        @pointercancel="onBoardPointerUp"
      >
        <defs>
          <!-- Pegs: a soft neutral gray, lightly domed (not gold). -->
          <radialGradient id="pegGlow" cx="42%" cy="38%" r="62%">
            <stop offset="0%" stop-color="#c2c6cf" />
            <stop offset="100%" stop-color="#6b7180" />
          </radialGradient>
          <!-- Ball: matte red. Gentle top-light, no bright white
               hotspot — keeps it from looking glossy/plastic. -->
          <radialGradient id="ballGrad" cx="40%" cy="36%" r="68%">
            <stop offset="0%" stop-color="#f0726f" />
            <stop offset="55%" stop-color="#d63b38" />
            <stop offset="100%" stop-color="#8f201d" />
          </radialGradient>
        </defs>

        <!-- Bin grid (drawn first — it's the floor; the pyramid + ball
             sit above it). Each cell filled with its ring's hue. -->
        <polygon
          v-for="b in bins3d"
          :key="`bin-${b.X}-${b.Z}`"
          :points="b.points"
          :fill="ringColor(b.ring)"
          :class="['bin', b.hit ? 'bin--hit' : '']"
        />

        <!-- Two payout labels per ring (opposite sides), tucked into a
             cell corner. The matrix maps text-local axes onto the floor
             plane's screen basis (planeBasis) so each reads as painted
             on the board — foreshortening + flipping as it spins.
             text-local x runs along world-X, local y along world-Z. -->
        <text
          v-for="(l, i) in binLabels3d"
          :key="`lbl-${i}`"
          :transform="`matrix(${planeBasis.ex.x.toFixed(4)} ${planeBasis.ex.y.toFixed(4)} ${planeBasis.ez.x.toFixed(4)} ${planeBasis.ez.y.toFixed(4)} ${l.lx.toFixed(2)} ${l.ly.toFixed(2)})`"
          x="0"
          y="0"
          :font-size="labelFontSize"
          text-anchor="start"
          dominant-baseline="hanging"
          class="binLabel"
        >{{ Number(l.mult).toString().replace(/\.0$/, '') }}×</text>

        <!-- Pegs are split at the ball's depth so the ball is correctly
             occluded — pegs further from the camera draw BEHIND it,
             nearer pegs draw IN FRONT. Both lists stay depth-sorted. -->
        <circle
          v-for="(p, i) in pegsBehindBall"
          :key="`pegB-${i}`"
          :cx="p.x"
          :cy="p.y"
          :r="pegRadius"
          fill="url(#pegGlow)"
          class="peg"
        />

        <!-- The ball. The <g> carries position + a spin transform; the
             two dark spots make the rotation visible. The glint is a
             separate, NON-rotating highlight so the light stays put. -->
        <g
          :transform="`translate(${ballPosition.sx} ${ballPosition.sy}) rotate(${ballPosition.spin}) scale(${ballPosition.scale})`"
          :class="['ballG', ballPosition.resting ? 'ballG--resting' : '']"
        >
          <circle :r="ballRadius" fill="url(#ballGrad)" class="ball" />
          <circle
            :cx="ballRadius * 0.34" :cy="ballRadius * 0.30"
            :r="ballRadius * 0.26" fill="#7f1d1d" opacity="0.85"
          />
          <circle
            :cx="-ballRadius * 0.40" :cy="ballRadius * 0.10"
            :r="ballRadius * 0.20" fill="#a52121" opacity="0.8"
          />
        </g>
        <!-- Faint top-light glint — kept subtle so the ball reads matte
             rather than glossy. -->
        <circle
          :cx="ballPosition.sx - ballRadius * 0.30 * ballPosition.scale"
          :cy="ballPosition.sy - ballRadius * 0.34 * ballPosition.scale"
          :r="ballRadius * 0.17 * ballPosition.scale"
          fill="#fff" opacity="0.2"
        />

        <!-- Pegs nearer the camera than the ball — drawn last so they
             overlap (occlude) it. -->
        <circle
          v-for="(p, i) in pegsInFrontBall"
          :key="`pegF-${i}`"
          :cx="p.x"
          :cy="p.y"
          :r="pegRadius"
          fill="url(#pegGlow)"
          class="peg"
        />
      </svg>
      <div class="boardHint">
        <span>drag the board to rotate</span>
        <button type="button" class="boardReset" @click="resetCamera">reset view</button>
      </div>
    </div>

    <!-- Ring → multiplier legend. With up to 289 bins we don't label
         each cell; this compact strip maps every ring to its payout,
         colour-matched to the board. -->
    <div class="ringLegend">
      <div
        v-for="(m, ring) in multipliers"
        :key="`ring-${ring}`"
        class="ringChip"
        :style="{ background: ringColor(ring, 0.32), borderColor: ringColor(ring, 0.7) }"
      >
        <span class="ringIdx">ring {{ ring }}</span>
        <span class="ringMult">{{ Number(m).toString().replace(/\.0$/, '') }}×</span>
      </div>
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
          @click="replayRound(id)"
          :title="rounds[id]?.roundStatus != 0 ? 'Click to replay this drop' : ''"
        >
          <span class="recentId">#{{ id }}</span>
          <span class="recentSpec">{{ rounds[id]?.rows }}r · {{ RISK_LABELS[Number(rounds[id]?.risk)] || '?' }}</span>
          <span class="recentSlot">
            <template v-if="rounds[id]?.roundStatus != 0">
              ({{ rounds[id]?.finalX }},{{ rounds[id]?.finalZ }}) r{{ rounds[id]?.ring }}
            </template>
            <template v-else>pending</template>
          </span>
          <span class="recentPay">{{ ((Number(rounds[id]?.payout || 0)) * 1e-6).toFixed(3) }} ꜩ</span>
        </div>
      </div>
    </div>

    <button
      type="button"
      class="howToBtn"
      :aria-expanded="showInfo"
      @click="showInfo = !showInfo"
    >
      How to play <span aria-hidden="true">{{ showInfo ? '▲' : '▼' }}</span>
    </button>
    <div v-if="showInfo" class="infoBlock">
      <div v-for="(line, i) in info" :key="i" class="infoLine">· {{ line }}</div>
    </div>
  </div>
</template>

<style scoped>
.plinkoRoot {
  display: flex; flex-direction: column; gap: 14px;
  padding: 16px;
  max-width: 680px; width: 100%; margin: 0 auto;
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
  background:
    radial-gradient(ellipse at 50% 0%, rgba(124, 58, 237, 0.14) 0%, transparent 62%),
    var(--ad-bg-elev-1);
  border: 1px solid var(--ad-border-soft);
  border-radius: var(--ad-r-lg);
  padding: 10px;
}
.board {
  width: 100%; display: block;
  cursor: grab;
  touch-action: none;   /* let pointer-drag rotate instead of scrolling */
}
.board--dragging { cursor: grabbing; }
/* Neutral soft shadow — pegs are gray now, not glowing gold. */
.peg { filter: drop-shadow(0 0.5px 1px rgba(0, 0, 0, 0.45)); }

/* Bin grid cells — fill is set inline per ring (ringColor). */
.bin {
  stroke: rgba(0, 0, 0, 0.5);
  stroke-width: 0.5;
  transition: filter 0.2s ease;
}
/* Payout labels skewed into the board plane. Small + near-black; a
   faint light halo lifts them off the darker rainbow cells. */
.binLabel {
  fill: #161616;
  stroke: rgba(255, 255, 255, 0.5);
  stroke-width: 0.16;
  paint-order: stroke;
  font-family: var(--ad-font-mono);
  font-weight: 700;
  pointer-events: none;
}
/* forwards: the winning ring stays lit until the next drop. */
.bin--hit { animation: binHit 0.9s ease-out forwards; }
@keyframes binHit {
  0%   { filter: brightness(1.0) drop-shadow(0 0 0 transparent); }
  25%  { filter: brightness(2.9) drop-shadow(0 0 10px var(--ad-gold-1)); }
  100% { filter: brightness(1.8) drop-shadow(0 0 5px var(--ad-gold-1)); }
}

/* Plain dark drop-shadow — no red glow — so the ball reads matte. */
.ball { filter: drop-shadow(0 1.5px 3px rgba(0, 0, 0, 0.45)); }
.ballG--resting {
  animation: ballRest 2.4s ease-in-out infinite;
  transform-box: fill-box;
  transform-origin: center;
}
@keyframes ballRest {
  0%, 100% { filter: drop-shadow(0 1.5px 2px rgba(0, 0, 0, 0.4)); }
  50%      { filter: drop-shadow(0 1.5px 5px rgba(0, 0, 0, 0.55)); }
}

/* Ring → multiplier legend strip. */
.ringLegend {
  display: flex; flex-wrap: wrap; gap: 5px; justify-content: center;
  background: var(--ad-bg-elev-1);
  border: 1px solid var(--ad-border-soft);
  border-radius: var(--ad-r-md);
  padding: 8px 10px;
}
.ringChip {
  display: flex; flex-direction: column; align-items: center;
  min-width: 52px;
  padding: 4px 8px;
  border-radius: var(--ad-r-sm);
  border: 1px solid transparent;   /* colour set inline via ringColor */
  font-family: var(--ad-font-mono);
}
.ringIdx {
  font-size: 9px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--ad-text-3);
}
.ringMult {
  font-size: 13px;
  font-weight: 700;
  color: #fff;
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.6);
}

/* Drag-to-rotate hint + reset-view control under the board. */
.boardHint {
  display: flex; align-items: center; justify-content: center; gap: 10px;
  margin-top: 6px;
  font-family: var(--ad-font-mono);
  font-size: 10px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--ad-text-3);
}
.boardReset {
  background: var(--ad-bg-elev-2);
  border: 1px solid var(--ad-border-soft);
  border-radius: var(--ad-r-sm);
  color: var(--ad-text-2);
  font-family: var(--ad-font-mono);
  font-size: 10px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  padding: 3px 9px;
  cursor: pointer;
  transition: background 0.15s ease, color 0.15s ease, border-color 0.15s ease;
}
.boardReset:hover {
  background: var(--ad-bg-elev-3);
  color: var(--ad-gold-1);
  border-color: var(--ad-gold-3);
}

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
.recentSlot { min-width: 86px; }
.recentPay  { margin-left: auto; }
.recent--1 { color: var(--ad-green-1); }
.recent--3 { color: var(--ad-red-1); }
.recent--2 { color: var(--ad-text-2); }
.recent--0 { color: var(--ad-violet-1); font-style: italic; }

.howToBtn {
  align-self: center;
  background: var(--ad-bg-elev-2);
  border: 1px solid var(--ad-border-soft);
  border-radius: var(--ad-r-sm);
  color: var(--ad-text-2);
  font-family: var(--ad-font-mono);
  font-size: 11px;
  letter-spacing: 0.04em;
  padding: 5px 14px;
  cursor: pointer;
  transition: background 0.15s ease, color 0.15s ease, border-color 0.15s ease;
}
.howToBtn:hover {
  background: var(--ad-bg-elev-3);
  color: var(--ad-gold-1);
  border-color: var(--ad-gold-3);
}
.howToBtn span { font-size: 9px; margin-left: 4px; }
.infoBlock {
  font-family: var(--ad-font-mono);
  font-size: 11px;
  color: var(--ad-text-3);
  line-height: 1.55;
}
.infoLine { padding: 1px 0; }
</style>
