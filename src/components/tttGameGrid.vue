<script>
// 3D 4-in-a-row grid, rendered as SVG with software 3D projection.
//
// We dropped Three.js because Chrome's GPU sandbox refuses WebGL contexts in
// some environments. SVG runs everywhere — and at 64 vertices + ~228 line
// segments the projection math is trivial.
//
// Coordinate convention:
//   Each axis has 4 indices: -1, 0, 1, 2.
//   World position for index i:  i * SPACING - 0.5 * SPACING.
//   So positions span -0.75 .. +0.75 (units), centered at the origin.
//
//   Rotation: rotX (pitch, around X axis) then rotY (yaw, around Y axis).
//   Projection: orthographic. Closer points (higher rotated z) render bigger.

// All 76 winning lines for 3D 4-in-a-row. Each line is 4 points in {-1..2}^3.
const gameWinners = [
  [[-1, -1, -1], [0, 0, 0], [1, 1, 1], [2, 2, 2]],
  [[-1, -1, 2], [0, 0, 1], [1, 1, 0], [2, 2, -1]],
  [[2, -1, -1], [1, 0, 0], [0, 1, 1], [-1, 2, 2]],
  [[2, -1, 2], [1, 0, 1], [0, 1, 0], [-1, 2, -1]],
  [[-1, -1, -1], [-1, 0, 0], [-1, 1, 1], [-1, 2, 2]],
  [[0, -1, -1], [0, 0, 0], [0, 1, 1], [0, 2, 2]],
  [[1, -1, -1], [1, 0, 0], [1, 1, 1], [1, 2, 2]],
  [[2, -1, -1], [2, 0, 0], [2, 1, 1], [2, 2, 2]],
  [[-1, -1, 2], [-1, 0, 1], [-1, 1, 0], [-1, 2, -1]],
  [[0, -1, 2], [0, 0, 1], [0, 1, 0], [0, 2, -1]],
  [[1, -1, 2], [1, 0, 1], [1, 1, 0], [1, 2, -1]],
  [[2, -1, 2], [2, 0, 1], [2, 1, 0], [2, 2, -1]],
  [[-1, -1, -1], [0, -1, 0], [1, -1, 1], [2, -1, 2]],
  [[-1, 0, -1], [0, 0, 0], [1, 0, 1], [2, 0, 2]],
  [[-1, 1, -1], [0, 1, 0], [1, 1, 1], [2, 1, 2]],
  [[-1, 2, -1], [0, 2, 0], [1, 2, 1], [2, 2, 2]],
  [[-1, -1, 2], [0, -1, 1], [1, -1, 0], [2, -1, -1]],
  [[-1, 0, 2], [0, 0, 1], [1, 0, 0], [2, 0, -1]],
  [[-1, 1, 2], [0, 1, 1], [1, 1, 0], [2, 1, -1]],
  [[-1, 2, 2], [0, 2, 1], [1, 2, 0], [2, 2, -1]],
  [[-1, -1, -1], [0, 0, -1], [1, 1, -1], [2, 2, -1]],
  [[-1, -1, 0], [0, 0, 0], [1, 1, 0], [2, 2, 0]],
  [[-1, -1, 1], [0, 0, 1], [1, 1, 1], [2, 2, 1]],
  [[-1, -1, 2], [0, 0, 2], [1, 1, 2], [2, 2, 2]],
  [[2, -1, -1], [1, 0, -1], [0, 1, -1], [-1, 2, -1]],
  [[2, -1, 0], [1, 0, 0], [0, 1, 0], [-1, 2, 0]],
  [[2, -1, 1], [1, 0, 1], [0, 1, 1], [-1, 2, 1]],
  [[2, -1, 2], [1, 0, 2], [0, 1, 2], [-1, 2, 2]],
  [[-1, -1, -1], [0, -1, -1], [1, -1, -1], [2, -1, -1]],
  [[-1, -1, 0], [0, -1, 0], [1, -1, 0], [2, -1, 0]],
  [[-1, -1, 1], [0, -1, 1], [1, -1, 1], [2, -1, 1]],
  [[-1, -1, 2], [0, -1, 2], [1, -1, 2], [2, -1, 2]],
  [[-1, 0, -1], [0, 0, -1], [1, 0, -1], [2, 0, -1]],
  [[-1, 0, 0], [0, 0, 0], [1, 0, 0], [2, 0, 0]],
  [[-1, 0, 1], [0, 0, 1], [1, 0, 1], [2, 0, 1]],
  [[-1, 0, 2], [0, 0, 2], [1, 0, 2], [2, 0, 2]],
  [[-1, 1, -1], [0, 1, -1], [1, 1, -1], [2, 1, -1]],
  [[-1, 1, 0], [0, 1, 0], [1, 1, 0], [2, 1, 0]],
  [[-1, 1, 1], [0, 1, 1], [1, 1, 1], [2, 1, 1]],
  [[-1, 1, 2], [0, 1, 2], [1, 1, 2], [2, 1, 2]],
  [[-1, 2, -1], [0, 2, -1], [1, 2, -1], [2, 2, -1]],
  [[-1, 2, 0], [0, 2, 0], [1, 2, 0], [2, 2, 0]],
  [[-1, 2, 1], [0, 2, 1], [1, 2, 1], [2, 2, 1]],
  [[-1, 2, 2], [0, 2, 2], [1, 2, 2], [2, 2, 2]],
  [[-1, -1, -1], [-1, 0, -1], [-1, 1, -1], [-1, 2, -1]],
  [[0, -1, -1], [0, 0, -1], [0, 1, -1], [0, 2, -1]],
  [[1, -1, -1], [1, 0, -1], [1, 1, -1], [1, 2, -1]],
  [[2, -1, -1], [2, 0, -1], [2, 1, -1], [2, 2, -1]],
  [[-1, -1, 0], [-1, 0, 0], [-1, 1, 0], [-1, 2, 0]],
  [[0, -1, 0], [0, 0, 0], [0, 1, 0], [0, 2, 0]],
  [[1, -1, 0], [1, 0, 0], [1, 1, 0], [1, 2, 0]],
  [[2, -1, 0], [2, 0, 0], [2, 1, 0], [2, 2, 0]],
  [[-1, -1, 1], [-1, 0, 1], [-1, 1, 1], [-1, 2, 1]],
  [[0, -1, 1], [0, 0, 1], [0, 1, 1], [0, 2, 1]],
  [[1, -1, 1], [1, 0, 1], [1, 1, 1], [1, 2, 1]],
  [[2, -1, 1], [2, 0, 1], [2, 1, 1], [2, 2, 1]],
  [[-1, -1, 2], [-1, 0, 2], [-1, 1, 2], [-1, 2, 2]],
  [[0, -1, 2], [0, 0, 2], [0, 1, 2], [0, 2, 2]],
  [[1, -1, 2], [1, 0, 2], [1, 1, 2], [1, 2, 2]],
  [[2, -1, 2], [2, 0, 2], [2, 1, 2], [2, 2, 2]],
  [[-1, -1, -1], [-1, -1, 0], [-1, -1, 1], [-1, -1, 2]],
  [[-1, 0, -1], [-1, 0, 0], [-1, 0, 1], [-1, 0, 2]],
  [[-1, 1, -1], [-1, 1, 0], [-1, 1, 1], [-1, 1, 2]],
  [[-1, 2, -1], [-1, 2, 0], [-1, 2, 1], [-1, 2, 2]],
  [[0, -1, -1], [0, -1, 0], [0, -1, 1], [0, -1, 2]],
  [[0, 0, -1], [0, 0, 0], [0, 0, 1], [0, 0, 2]],
  [[0, 1, -1], [0, 1, 0], [0, 1, 1], [0, 1, 2]],
  [[0, 2, -1], [0, 2, 0], [0, 2, 1], [0, 2, 2]],
  [[1, -1, -1], [1, -1, 0], [1, -1, 1], [1, -1, 2]],
  [[1, 0, -1], [1, 0, 0], [1, 0, 1], [1, 0, 2]],
  [[1, 1, -1], [1, 1, 0], [1, 1, 1], [1, 1, 2]],
  [[1, 2, -1], [1, 2, 0], [1, 2, 1], [1, 2, 2]],
  [[2, -1, -1], [2, -1, 0], [2, -1, 1], [2, -1, 2]],
  [[2, 0, -1], [2, 0, 0], [2, 0, 1], [2, 0, 2]],
  [[2, 1, -1], [2, 1, 0], [2, 1, 1], [2, 1, 2]],
  [[2, 2, -1], [2, 2, 0], [2, 2, 1], [2, 2, 2]],
]

const SPACING = 60 // world units between adjacent vertices (drives SVG scale)

// Build the gameGrid object the rest of the app expects.
function emptyGameGrid() {
  const g = {}
  for (let i = -1; i < 3; i++) {
    g[i] = {}
    for (let j = -1; j < 3; j++) {
      g[i][j] = {}
      for (let k = -1; k < 3; k++) {
        g[i][j][k] = 0
      }
    }
  }
  return g
}

// Map index {-1, 0, 1, 2} → world coord {-90, -30, 30, 90} (when SPACING=60).
function worldPos(idx) {
  return idx * SPACING - 0.5 * SPACING
}

// Rotate point [x, y, z] by ax around X axis, then ay around Y axis.
function rotate3(p, ax, ay) {
  const [x, y, z] = p
  // Rx
  const cax = Math.cos(ax),
    sax = Math.sin(ax)
  const y1 = y * cax - z * sax
  const z1 = y * sax + z * cax
  // Ry
  const cay = Math.cos(ay),
    say = Math.sin(ay)
  const x2 = x * cay + z1 * say
  const z2 = -x * say + z1 * cay
  return [x2, y1, z2]
}

function clamp(v, lo, hi) {
  return v < lo ? lo : v > hi ? hi : v
}

export default {
  name: 'gameGrid',
  props: ['socket', 'activeGameId', 'wallet'],
  data() {
    return {
      // ─── Existing game state — preserved verbatim ───────────────────
      rotate: false,
      playX: 0,
      playY: 0,
      clickX: 0,
      clickY: 0,
      cameraX: 0,
      cameraY: 0,
      playedPoint: [0, 0, 0],
      moveMade: false,
      gamePlayable: false,
      gameRefreshed: true,
      playerColor: 'red',
      playerTurn: 1,
      walletTurn: 0,
      gameId: -1,
      walletPlayerTurn1: '',
      walletPlayerTurn2: '',
      gamePaused: false,
      halfTurn: false,
      player1Plays: {},
      player2Plays: {},
      tempHighlights: [],
      playersInGame: [],
      allPaths: {},
      demoTurn: 1,
      // ─── 3D view state (replaces Three.js camera/OrbitControls) ─────
      // Initial pose: a slight tilt looking down + rotated to see all 3 axes.
      rotX: -0.45,
      rotY: 0.6,
      zoom: 1,
      isDragging: false,
      dragMoved: false,
      dragStart: null,
      hoverCoord: null,
      // gameGrid is non-reactive on the instance (Three.js code did this too)
      // but driving reactivity through computed projections is cheap enough.
      gameGridRev: 0, // bumped on every grid mutation to invalidate computeds
    }
  },
  created() {
    // Pre-populate the grid so the board is fully interactive on mount,
    // before any contract game has loaded. Demo mode handles clicks on
    // empty cells and lets the player explore positions freely.
    this.gameGrid = emptyGameGrid()
  },
  mounted() {
    // Socket: same wires as before.
    this.socket.on('updateGameGrid', (gameGrid) => {
      this.gameGrid = gameGrid
      this.gameGridRev++
    })
    this.socket.on('resizeGame', () => {
      // No-op — SVG is responsive via viewBox.
    })
    this.socket.on('updatePlayerTurn', (playerTurn) => {
      this.playerTurn = playerTurn
    })
    this.socket.on('updateGamePlayable', (gamePlayable) => {
      this.gamePlayable = gamePlayable
      this.gamePaused = !gamePlayable
    })
    this.socket.on('updateGamePaused', (gamePaused) => {
      this.gamePaused = gamePaused
    })
    this.socket.on('updateGameId', (gameId) => {
      this.gameId = gameId
    })
    this.socket.on('updatePlayersInGame', (playersInGame) => {
      this.playersInGame = playersInGame
    })

    // Idle auto-rotate: gentle Y spin until the user touches the board.
    this._idleStart = performance.now()
    this._idleRaf = requestAnimationFrame(this.idleTick)
  },
  beforeUnmount() {
    if (this._idleRaf) {
      cancelAnimationFrame(this._idleRaf)
      this._idleRaf = 0
    }
  },
  computed: {
    // 64 vertices, each projected to screen space.
    // Sorted back-to-front so the SVG renders deeper spheres first.
    projectedVertices() {
      // Touch gameGridRev so this recomputes when the grid mutates.
      void this.gameGridRev
      const out = []
      for (let i = -1; i < 3; i++) {
        for (let j = -1; j < 3; j++) {
          for (let k = -1; k < 3; k++) {
            const wp = [worldPos(i), worldPos(j), worldPos(k)]
            const [rx, ry, rz] = rotate3(wp, this.rotX, this.rotY)
            // Orthographic projection. Y flipped because SVG y grows down.
            const sx = 200 + rx * this.zoom
            const sy = 200 - ry * this.zoom
            // Closer (higher rz) → bigger and brighter.
            const depthT = (rz + 100) / 200 // 0..1 (clipped softly)
            const radius = 7 + clamp(depthT, 0, 1) * 4
            const owner = this.gameGrid?.[i]?.[j]?.[k] ?? 0
            out.push({ i, j, k, x: sx, y: sy, z: rz, radius, owner, depthT })
          }
        }
      }
      // Back to front: lower z first.
      out.sort((a, b) => a.z - b.z)
      return out
    },
    // All winning-line segments projected. Color-coded by ownership.
    projectedSegments() {
      void this.gameGridRev
      const out = []
      for (const line of gameWinners) {
        for (let s = 0; s < 3; s++) {
          const a = line[s]
          const b = line[s + 1]
          const wa = [worldPos(a[0]), worldPos(a[1]), worldPos(a[2])]
          const wb = [worldPos(b[0]), worldPos(b[1]), worldPos(b[2])]
          const ra = rotate3(wa, this.rotX, this.rotY)
          const rb = rotate3(wb, this.rotX, this.rotY)
          const oa = this.gameGrid[a[0]][a[1]][a[2]]
          const ob = this.gameGrid[b[0]][b[1]][b[2]]
          // Default: dim hint of the underlying geometry.
          let stroke = 'rgba(120, 200, 150, 0.10)'
          let width = 1
          if (Math.abs(oa) === Math.abs(ob) && oa !== 0 && ob !== 0) {
            // Both ends played by the same side — light it up.
            const owner = Math.abs(oa)
            stroke = owner === 1 ? 'rgba(196, 82, 79, 0.85)' : 'rgba(79, 108, 196, 0.85)'
            width = 2
          } else if ((oa < 0 && ob !== 0) || (ob < 0 && oa !== 0)) {
            // One end is a tentative move — preview its color.
            const owner = Math.abs(oa < 0 ? oa : ob)
            stroke =
              owner === 1 ? 'rgba(196, 82, 79, 0.45)' : 'rgba(79, 108, 196, 0.45)'
            width = 1.5
          }
          out.push({
            x1: 200 + ra[0] * this.zoom,
            y1: 200 - ra[1] * this.zoom,
            x2: 200 + rb[0] * this.zoom,
            y2: 200 - rb[1] * this.zoom,
            z: (ra[2] + rb[2]) / 2,
            stroke,
            width,
          })
        }
      }
      out.sort((a, b) => a.z - b.z)
      return out
    },
  },
  methods: {
    // ─── Mouse / touch interaction ─────────────────────────────────────
    onPointerDown(evt) {
      // Stop the idle auto-rotate the moment the user grabs the board.
      this._idleStopped = true
      this.isDragging = true
      this.dragMoved = false
      const p = this.eventPoint(evt)
      this.dragStart = {
        x: p.x,
        y: p.y,
        rotX: this.rotX,
        rotY: this.rotY,
      }
    },
    onPointerMove(evt) {
      if (!this.isDragging) return
      const p = this.eventPoint(evt)
      const dx = p.x - this.dragStart.x
      const dy = p.y - this.dragStart.y
      if (Math.abs(dx) + Math.abs(dy) > 4) this.dragMoved = true
      this.rotY = this.dragStart.rotY + dx * 0.012
      this.rotX = clamp(this.dragStart.rotX + dy * 0.012, -1.4, 1.4)
    },
    onPointerUp() {
      // If the user clicked without dragging on a hovered vertex, play it.
      if (this.isDragging && !this.dragMoved && this.hoverCoord) {
        const [i, j, k] = this.hoverCoord
        this.playAt(i, j, k)
      }
      this.isDragging = false
      this.dragMoved = false
    },
    onWheel(evt) {
      evt.preventDefault()
      this._idleStopped = true
      const next = this.zoom * (evt.deltaY < 0 ? 1.08 : 1 / 1.08)
      this.zoom = clamp(next, 0.6, 2.2)
    },
    onTouchStart(evt) {
      if (evt.touches.length !== 1) return
      this.onPointerDown(evt.touches[0])
    },
    onTouchMove(evt) {
      if (evt.touches.length !== 1) return
      evt.preventDefault()
      this.onPointerMove(evt.touches[0])
    },
    onTouchEnd() {
      this.onPointerUp()
    },
    // Translate a (mouse|touch) event into local SVG coordinates.
    eventPoint(evt) {
      const svg = this.$refs.svg
      if (!svg) return { x: evt.clientX || 0, y: evt.clientY || 0 }
      const rect = svg.getBoundingClientRect()
      const cx = evt.clientX !== undefined ? evt.clientX : evt.pageX
      const cy = evt.clientY !== undefined ? evt.clientY : evt.pageY
      // Map screen px → SVG viewBox units (viewBox is 0..400 each axis).
      return {
        x: ((cx - rect.left) / rect.width) * 400,
        y: ((cy - rect.top) / rect.height) * 400,
      }
    },
    // Hover handlers fired by each <circle> directly.
    onVertexEnter(i, j, k) {
      this.hoverCoord = [i, j, k]
    },
    onVertexLeave() {
      this.hoverCoord = null
    },
    // ─── Idle auto-rotate ────────────────────────────────────────────
    idleTick(now) {
      if (!this._idleStopped) {
        const t = (now - this._idleStart) / 1000
        // Gentle yaw around the initial pose. ±0.3 rad over ~12s.
        this.rotY = 0.6 + Math.sin(t * 0.5) * 0.3
        this.rotX = -0.45 + Math.cos(t * 0.4) * 0.1
      }
      this._idleRaf = requestAnimationFrame(this.idleTick)
    },
    // ─── Game logic ──────────────────────────────────────────────────
    isHovered(i, j, k) {
      const h = this.hoverCoord
      return !!(h && h[0] === i && h[1] === j && h[2] === k)
    },
    // Pick a fill for a vertex based on owner + depth.
    vertexFill(v) {
      // Depth-tinted base; owners get full saturated color.
      const tint = clamp(0.55 + v.depthT * 0.35, 0.5, 0.95)
      if (v.owner === 1) return `url(#vRed)`
      if (v.owner === 2) return `url(#vBlue)`
      if (v.owner === -1) return `url(#vRedTemp)`
      if (v.owner === -2) return `url(#vBlueTemp)`
      // Default: silver. Use depth to slightly darken farther spheres.
      return this.isHovered(v.i, v.j, v.k) ? 'url(#vGold)' : `rgba(220, 230, 240, ${tint})`
    },
    // Play a move at coordinates. Same semantics as before.
    playAt(i, j, k, evt) {
      // ── DEMO MODE ─────────────────────────────────────────────────
      if (!this.gamePlayable) {
        const cur = this.gameGrid[i][j][k]
        let next
        if (cur === 0) next = this.demoTurn
        else if (cur === 1) next = 2
        else next = 0
        this.gameGrid[i][j][k] = next
        if (next !== 0) this.demoTurn = next === 1 ? 2 : 1
        this.gameGridRev++
        return
      }
      // ── REAL GAME ─────────────────────────────────────────────────
      if (!this.gamePaused) {
        if (this.gameGrid[i][j][k] === 0) {
          this.socket.emit('updatePlayedPoint', [i, j, k], 'Move Selected', this.gameId)
          this.gameGrid[i][j][k] = -1 * this.playerTurn
          this.socket.emit('updateGamePaused', true, this.gameId)
          this.gamePaused = true
        }
      } else {
        if (this.gameGrid[i][j][k] < 0) {
          this.gamePaused = false
          this.socket.emit('updateGamePaused', false, this.gameId)
          this.socket.emit('updatePlayedPoint', 'NO MOVE', 'Active', this.gameId)
        } else if (this.gameGrid[i][j][k] === this.playerTurn) {
          this.socket.emit('updatePlayedPoint', 'NO MOVE', 'Active', this.gameId)
          this.socket.emit('updateGamePaused', false, this.gameId)
          this.gamePaused = false
        }
      }
      this.playedPoint = [i, j, k]
      this.socket.emit('updateGameGrid', this.gameGrid, this.gameId, true)
      this.gameGridRev++
      // Avoid unused-arg warnings while keeping signature backwards-compatible.
      void evt
    },
    resetDemo() {
      this.gameGrid = emptyGameGrid()
      this.demoTurn = 1
      this.gameGridRev++
    },
    resetView() {
      this.rotX = -0.45
      this.rotY = 0.6
      this.zoom = 1
      this._idleStopped = false
      this._idleStart = performance.now()
    },
  },
}
</script>

<template>
  <div class="gridRoot">
    <svg
      ref="svg"
      class="gridSvg"
      viewBox="0 0 400 400"
      preserveAspectRatio="xMidYMid meet"
      @mousedown="onPointerDown"
      @mousemove="onPointerMove"
      @mouseup="onPointerUp"
      @mouseleave="onPointerUp"
      @wheel.prevent="onWheel"
      @touchstart.prevent="onTouchStart"
      @touchmove.prevent="onTouchMove"
      @touchend.prevent="onTouchEnd"
    >
      <defs>
        <!-- Background gradient: deep navy → black, with a soft spotlight. -->
        <radialGradient id="gridBg" cx="50%" cy="40%" r="80%">
          <stop offset="0%" stop-color="#1a1448" />
          <stop offset="60%" stop-color="#0a0728" />
          <stop offset="100%" stop-color="#02010d" />
        </radialGradient>

        <!-- Lit-sphere gradients per vertex state. Light comes from top-left. -->
        <radialGradient id="vRed" cx="35%" cy="30%" r="70%">
          <stop offset="0%" stop-color="#ffd0cf" />
          <stop offset="35%" stop-color="#e85f5b" />
          <stop offset="100%" stop-color="#7a1e1c" />
        </radialGradient>
        <radialGradient id="vBlue" cx="35%" cy="30%" r="70%">
          <stop offset="0%" stop-color="#d6dcff" />
          <stop offset="35%" stop-color="#5d80e4" />
          <stop offset="100%" stop-color="#1d2f7a" />
        </radialGradient>
        <radialGradient id="vRedTemp" cx="35%" cy="30%" r="70%">
          <stop offset="0%" stop-color="rgba(255,208,207,0.7)" />
          <stop offset="35%" stop-color="rgba(232,95,91,0.55)" />
          <stop offset="100%" stop-color="rgba(122,30,28,0.45)" />
        </radialGradient>
        <radialGradient id="vBlueTemp" cx="35%" cy="30%" r="70%">
          <stop offset="0%" stop-color="rgba(214,220,255,0.7)" />
          <stop offset="35%" stop-color="rgba(93,128,228,0.55)" />
          <stop offset="100%" stop-color="rgba(29,47,122,0.45)" />
        </radialGradient>
        <radialGradient id="vGold" cx="35%" cy="30%" r="70%">
          <stop offset="0%" stop-color="#fff4cc" />
          <stop offset="35%" stop-color="#f5c451" />
          <stop offset="100%" stop-color="#a06c12" />
        </radialGradient>
      </defs>

      <!-- Backdrop -->
      <rect width="400" height="400" fill="url(#gridBg)" />

      <!-- Connector lines (sorted back-to-front) -->
      <g class="gridLines">
        <line
          v-for="(s, idx) in projectedSegments"
          :key="'s' + idx"
          :x1="s.x1"
          :y1="s.y1"
          :x2="s.x2"
          :y2="s.y2"
          :stroke="s.stroke"
          :stroke-width="s.width"
          stroke-linecap="round"
        />
      </g>

      <!-- Vertices (also sorted back-to-front) -->
      <g class="gridVerts">
        <circle
          v-for="v in projectedVertices"
          :key="v.i + ',' + v.j + ',' + v.k"
          :cx="v.x"
          :cy="v.y"
          :r="v.radius"
          :fill="vertexFill(v)"
          :stroke="isHovered(v.i, v.j, v.k) ? '#f5c451' : 'rgba(0,0,0,0.4)'"
          :stroke-width="isHovered(v.i, v.j, v.k) ? 2 : 0.5"
          @mouseenter="onVertexEnter(v.i, v.j, v.k)"
          @mouseleave="onVertexLeave"
        />
      </g>
    </svg>

    <!-- Demo hint: shown whenever there's no real game in progress. -->
    <div v-if="!gamePlayable" class="demoHint">
      <span class="demoHintDot"></span>
      <span class="demoHintLabel">DEMO</span>
      <span class="demoHintBody">
        Click a vertex to cycle red / blue. Drag the board to rotate. Scroll to zoom.
      </span>
      <button class="demoBtn" @click="resetDemo">Reset board</button>
      <button class="demoBtn demoBtn--ghost" @click="resetView">Reset view</button>
    </div>
  </div>
</template>

<style scoped>
.gridRoot {
  width: 100%;
  margin: 0 auto;
  padding: 0;
  display: flex;
  flex-direction: column;
  align-items: stretch;
  font-family: 'EB Garamond', serif;
}
.gridSvg {
  display: block;
  width: 100%;
  max-width: 600px;
  aspect-ratio: 1 / 1;
  margin: 0 auto;
  border-radius: 12px;
  background: #02010d;
  cursor: grab;
  user-select: none;
  touch-action: none;
  box-shadow:
    inset 0 0 0 1px rgba(255, 255, 255, 0.06),
    0 8px 22px rgba(0, 0, 0, 0.45);
}
.gridSvg:active { cursor: grabbing; }

/* Hovering a vertex changes the cursor to communicate "you can click here". */
.gridVerts circle { transition: filter 0.18s ease; cursor: pointer; }
.gridVerts circle:hover { filter: drop-shadow(0 0 4px rgba(245, 196, 81, 0.7)); }

/* Demo hint chip — same styling family as the rest of the app. */
.demoHint {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  padding: 6px 10px;
  margin: 8px auto 0;
  max-width: 600px;
  border-radius: 8px;
  background: rgba(245, 196, 81, 0.08);
  border: 1px dashed rgba(245, 196, 81, 0.45);
  color: rgba(255, 255, 255, 0.85);
  font-size: 12px;
}
.demoHintDot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #f5c451;
  box-shadow: 0 0 6px rgba(245, 196, 81, 0.8);
  animation: demoPulse 1.6s ease-in-out infinite;
}
@keyframes demoPulse {
  0%, 100% { opacity: 0.5; }
  50% { opacity: 1; }
}
.demoHintLabel {
  font-size: 10px;
  letter-spacing: 3px;
  font-weight: 700;
  color: #f5c451;
}
.demoHintBody { flex: 1; min-width: 0; }
.demoBtn {
  background: transparent;
  border: 1px solid rgba(245, 196, 81, 0.55);
  border-radius: 4px;
  color: #f5c451;
  font-family: 'EB Garamond', serif;
  font-size: 11px;
  letter-spacing: 1.5px;
  font-weight: 700;
  padding: 4px 10px;
  cursor: pointer;
  transition: background 0.15s ease;
}
.demoBtn:hover { background: rgba(245, 196, 81, 0.12); }
.demoBtn--ghost {
  border-color: rgba(255, 255, 255, 0.2);
  color: rgba(255, 255, 255, 0.7);
}
.demoBtn--ghost:hover { background: rgba(255, 255, 255, 0.06); }
</style>
