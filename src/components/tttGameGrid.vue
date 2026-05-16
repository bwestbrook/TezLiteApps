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
      // [i,j,k] of the tentatively-picked vertex, or null. One pick at a
      // time — you must deselect (click it again) before choosing another.
      selectedCoord: null,
      // True while a move is being written to chain (mirrored to both
      // players). The board is fully locked — no clicks, no rotation —
      // until the chain confirms and the turn can switch.
      movePending: false,
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
      // Re-stamp our tentative pick on top of the synced grid. A chain
      // re-sync carries only committed marks, so without this a poll
      // would wipe a selection that hasn't been submitted yet. If the
      // cell is no longer empty on-chain, the pick is stale — drop it.
      if (this.selectedCoord) {
        const [i, j, k] = this.selectedCoord
        if (this.gameGrid?.[i]?.[j]?.[k] === 0) {
          this.gameGrid[i][j][k] = -1 * this.playerTurn
        } else {
          this.selectedCoord = null
        }
      }
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
      // Turn passed (or game ended) — drop any tentative pick so it
      // can't linger as stale state into the opponent's turn.
      if (!gamePlayable) this.selectedCoord = null
    })
    this.socket.on('updateGameId', (gameId) => {
      this.gameId = gameId
      // A real game loaded — kill the idle auto-spin so the board sits
      // still (and stays in sync with the opponent's view).
      if (gameId >= 0) this._idleStopped = true
    })
    this.socket.on('updatePlayersInGame', (playersInGame) => {
      this.playersInGame = playersInGame
    })
    // Board orientation pushed by the active player. We only receive this
    // as the watcher (the server doesn't echo to the sender), so mirror
    // it straight onto our view.
    this.socket.on('updateGridView', (view) => {
      if (!view || typeof view !== 'object') return
      if (typeof view.rotX === 'number') this.rotX = view.rotX
      if (typeof view.rotY === 'number') this.rotY = view.rotY
      if (typeof view.zoom === 'number') this.zoom = view.zoom
    })
    // A move is being written to chain — lock the board for both players
    // until it confirms (canControl reads this). selectedCoord is NOT
    // cleared here: the in-flight move marker must stay visible (and
    // protected by the updateGameGrid re-stamp) until the turn actually
    // passes — updateGamePlayable(false) clears it at that point.
    this.socket.on('updateMovePending', (pending) => {
      this.movePending = !!pending
      if (this._movePendingTimer) {
        clearTimeout(this._movePendingTimer)
        this._movePendingTimer = 0
      }
      if (pending) {
        // Safety net mirroring tezTacToe.vue — never leave the board
        // locked forever if the submitter's client dies mid-write.
        this._movePendingTimer = setTimeout(() => {
          this.movePending = false
        }, 90000)
      }
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
    if (this._movePendingTimer) {
      clearTimeout(this._movePendingTimer)
      this._movePendingTimer = 0
    }
  },
  computed: {
    // ─── Turn-gating ────────────────────────────────────────────────
    // A contract game is loaded once gameId >= 0; before that the board
    // is a free-play demo. gamePlayable (synced from the parent) is true
    // only when it's THIS wallet's turn.
    inRealGame() {
      return this.gameId >= 0
    },
    // Can this client click vertices AND rotate/zoom the board?
    //   • a move is being written to chain → no — locked for both sides
    //   • demo (no game loaded)            → yes, free play
    //   • real game, my turn               → yes
    //   • real game, not my turn           → no — watch the opponent
    canControl() {
      if (this.movePending) return false
      return !this.inRealGame || this.gamePlayable
    },
    // In a real game and it's the opponent's turn — view-only.
    isWatching() {
      return this.inRealGame && !this.gamePlayable && !this.movePending
    },
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
          let hot = false
          // Light a segment ONLY when both ends are the same colour —
          // committed or tentative, in any mix (Math.abs folds the
          // tentative -1/-2 onto 1/2). A connection between two
          // different colours is never highlighted.
          if (Math.abs(oa) === Math.abs(ob) && oa !== 0 && ob !== 0) {
            const owner = Math.abs(oa)
            stroke = owner === 1 ? 'rgba(196, 82, 79, 0.85)' : 'rgba(79, 108, 196, 0.85)'
            width = 2
            hot = true
          }
          out.push({
            x1: 200 + ra[0] * this.zoom,
            y1: 200 - ra[1] * this.zoom,
            x2: 200 + rb[0] * this.zoom,
            y2: 200 - rb[1] * this.zoom,
            z: (ra[2] + rb[2]) / 2,
            stroke,
            width,
            hot,
          })
        }
      }
      // Paint dim lattice lines first (back-to-front), then highlighted
      // segments on top (also back-to-front). Without this, a lit diagonal
      // — which threads through the middle of the structure — gets buried
      // under the dim lines crossing in front of it; axis-aligned lits sit
      // on the shell and survive, which is why only diagonals looked broken.
      out.sort((a, b) => (Number(a.hot) - Number(b.hot)) || (a.z - b.z))
      return out
    },
  },
  methods: {
    // ─── Mouse / touch interaction ─────────────────────────────────────
    onPointerDown(evt) {
      // Watching the opponent's turn — no grabbing the board.
      if (!this.canControl) return
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
      if (!this.isDragging || !this.canControl) return
      const p = this.eventPoint(evt)
      const dx = p.x - this.dragStart.x
      const dy = p.y - this.dragStart.y
      if (Math.abs(dx) + Math.abs(dy) > 4) this.dragMoved = true
      this.rotY = this.dragStart.rotY + dx * 0.012
      this.rotX = clamp(this.dragStart.rotX + dy * 0.012, -1.4, 1.4)
      this.emitView()
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
      if (!this.canControl) return
      this._idleStopped = true
      const next = this.zoom * (evt.deltaY < 0 ? 1.08 : 1 / 1.08)
      this.zoom = clamp(next, 0.6, 2.2)
      this.emitView()
    },
    // Broadcast our board orientation to the opponent — but only when
    // we're the active player (the watcher must never push its view
    // back). Throttled to ~30/s so a drag doesn't flood the socket.
    emitView() {
      if (!this.inRealGame || !this.gamePlayable) return
      const now = performance.now()
      if (now - (this._lastViewEmit || 0) < 33) return
      this._lastViewEmit = now
      this.socket.emit(
        'updateGridView',
        { rotX: this.rotX, rotY: this.rotY, zoom: this.zoom },
        this.gameId,
      )
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
    // Only spins in demo (no game loaded). Inside a real game the board
    // stays put so it can't fight the synced opponent view.
    idleTick(now) {
      if (!this._idleStopped && !this.inRealGame) {
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
    // Click a vertex.
    //   • demo (no game loaded)  → free-cycle the cell's color
    //   • real game, my turn     → select / deselect a vertex (one at a time)
    //   • real game, watching    → ignored (handled by canControl, but
    //                              guarded here too in case of a stray call)
    playAt(i, j, k, evt) {
      void evt // signature kept for backwards-compat
      // ── DEMO MODE ─────────────────────────────────────────────────
      if (!this.inRealGame) {
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
      // Not my turn → no interaction (watch only).
      if (!this.gamePlayable) return

      const sel = this.selectedCoord
      const isSelectedCell =
        sel && sel[0] === i && sel[1] === j && sel[2] === k

      if (!sel) {
        // Nothing picked yet — select this empty cell.
        if (this.gameGrid[i][j][k] !== 0) return
        this.gameGrid[i][j][k] = -1 * this.playerTurn // tentative marker
        this.selectedCoord = [i, j, k]
        this.playedPoint = [i, j, k]
        this.socket.emit('updatePlayedPoint', [i, j, k], 'Move selected', this.gameId)
      } else if (isSelectedCell) {
        // Click the picked cell again → deselect.
        this.gameGrid[i][j][k] = 0
        this.selectedCoord = null
        this.socket.emit('updatePlayedPoint', 'NO MOVE', 'Active', this.gameId)
      } else {
        // A pick is already active and this is a different cell —
        // ignore. One ball at a time: deselect before choosing another.
        return
      }
      // Sync the tentative pick to the opponent's board so both see it.
      this.socket.emit('updateGameGrid', this.gameGrid, this.gameId, true)
      this.gameGridRev++
    },
  },
}
</script>

<template>
  <div class="gridRoot">
    <!-- A move is being written to chain — board locked for both
         players until the chain confirms and the turn can switch. -->
    <div v-if="movePending" class="watchBanner watchBanner--pending">
      <span class="watchDot watchDot--pending"></span>
      Writing move to blockchain…
    </div>
    <!-- Watching overlay — shown while it's the opponent's turn. The
         board still updates live (synced grid + view), it's just not
         interactive for this client. -->
    <div v-else-if="isWatching" class="watchBanner">
      <span class="watchDot"></span>
      Opponent's turn — watching live
    </div>
    <svg
      ref="svg"
      :class="['gridSvg', canControl ? '' : 'gridSvg--locked']"
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

/* Watching the opponent's turn — board is view-only. */
.gridSvg--locked,
.gridSvg--locked:active { cursor: default; }
.gridSvg--locked .gridVerts circle { cursor: default; }
.gridSvg--locked .gridVerts circle:hover { filter: none; }

/* Hovering a vertex changes the cursor to communicate "you can click here". */
.gridVerts circle { transition: filter 0.18s ease; cursor: pointer; }
.gridVerts circle:hover { filter: drop-shadow(0 0 4px rgba(245, 196, 81, 0.7)); }

/* ── Watching banner ─────────────────────────────────────────────── */
.watchBanner {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  margin: 0 auto 6px;
  max-width: 600px;
  padding: 5px 12px;
  border-radius: 8px;
  background: rgba(79, 108, 196, 0.14);
  border: 1px solid rgba(79, 108, 196, 0.5);
  color: #aebdf0;
  font-size: 12px;
  letter-spacing: 1px;
  text-transform: uppercase;
  font-weight: 700;
}
.watchDot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #5d80e4;
  box-shadow: 0 0 6px rgba(93, 128, 228, 0.9);
  animation: watchPulse 1.4s ease-in-out infinite;
}
/* Move-being-written variant — gold, matches the "writing to bc" badge. */
.watchBanner--pending {
  background: rgba(245, 196, 81, 0.14);
  border-color: rgba(245, 196, 81, 0.55);
  color: #f5c451;
}
.watchDot--pending {
  background: #f5c451;
  box-shadow: 0 0 6px rgba(245, 196, 81, 0.95);
}
@keyframes watchPulse {
  0%, 100% { opacity: 0.4; }
  50% { opacity: 1; }
}

/* ─── Mobile ─ TTT canvas already sizes via gameSize prop; rules here
   just keep the watch indicator + status chrome compact on phones. */
@media (max-width: 480px) {
  .watchDot { width: 8px; height: 8px; }
}
</style>
