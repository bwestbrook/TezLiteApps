<script>
// Chess H2H — UI mirrors the new gambling-aware contract.
//
// Two-mode component (lobby/landing + play view). Board ALWAYS renders with
// the standard opening position when no contract game is active so users can
// browse, learn, and try moves in demo mode before staking.
//
// Contract → UI field mapping (new gambling contract):
//   g.wager        (mutez)   — each side's locked stake
//   g.gameStatus   (nat)     — 0 open, 1 awaiting flip, 2 in-play, 3 settled, 4 cancelled
//   g.toMove       (nat)     — 1 white, 2 black (0 = awaiting flip)
//   g.board        (map)     — 64 cells, see GLYPH below
//   g.winner       (addr)    — settled winner (BURN if draw)
//   g.drawOfferedBy (nat)    — 0/1/2
//   g.houseCutBps  (nat)     — basis points snapshotted at game creation
//   g.status       (variant) — { play | finished: "player_1_won"|"player_2_won"|"draw" | ... }

import { getContractStorage, isPlaceholderAddress } from '../services/tzkt'
import {
  BLOCKCHAIN_ENABLED,
  CHESS_CONTRACT_ADDRESS,
  CHESS_GAME_INFO,
} from '../constants'

// Piece codes (must match contract): 0 empty, 1-6 white P/N/B/R/Q/K, 7-12 black p/n/b/r/q/k.
const GLYPH = {
  0: '',
  1: '♙', 2: '♘', 3: '♗', 4: '♖', 5: '♕', 6: '♔', // white
  7: '♟', 8: '♞', 9: '♝', 10: '♜', 11: '♛', 12: '♚', // black
}
const FILES = ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h']

// Standard chess starting position, ranks 0..7 with white at rank 0.
function openingBoard() {
  const b = new Array(64).fill(0)
  b[0] = 4; b[1] = 2; b[2] = 3; b[3] = 5; b[4] = 6; b[5] = 3; b[6] = 2; b[7] = 4
  for (let c = 0; c < 8; c++) b[8 + c] = 1
  for (let c = 0; c < 8; c++) b[48 + c] = 7
  b[56] = 10; b[57] = 8; b[58] = 9; b[59] = 11; b[60] = 12; b[61] = 9; b[62] = 8; b[63] = 10
  return b
}

const PHASE_LABELS = {
  0: 'Open — waiting for opponent',
  1: 'Awaiting first-move flip',
  2: 'In play',
  3: 'Settled',
  4: 'Cancelled',
}
const PHASE_TONES = {
  0: 'phaseOpen',
  1: 'phaseLive',
  2: 'phaseLive',
  3: 'phaseDone',
  4: 'phaseDone',
}

// ── Helpers to coerce contract storage values ──────────────────────────────
function nat(v) { return Number(v ?? 0) }
function mutez(v) { return Number(v ?? 0) }

// ── Piece + move helpers (demo-mode only) ──────────────────────────────────
// Demo gives the player a realistic feel without trying to replicate the
// full on-chain ruleset. We do PSEUDO-LEGAL movement (each piece moves the
// way it physically can, blocked by friendly pieces, capturing enemies) —
// no check detection, no castling, no en passant. The real contract
// enforces the full rules on submitted moves, so demo only needs to feel
// chess-shaped, not be chess-correct.

// Codes: 1-6 white P/N/B/R/Q/K, 7-12 black p/n/b/r/q/k, 0 empty.
function pieceSide(code) {
  if (code >= 1 && code <= 6) return 1
  if (code >= 7 && code <= 12) return 2
  return 0
}

// "a1" style for move-list notation.
function squareName(idx) {
  return FILES[idx % 8] + (Math.floor(idx / 8) + 1)
}

// Pseudo-legal destinations for the piece at `from` on `board` (flat 64-cell
// array indexed 0=a1, 63=h8). Returns a Set of destination indices.
function legalTargets(board, from) {
  const code = board[from]
  const out = new Set()
  if (!code) return out
  const side = pieceSide(code)
  const r = Math.floor(from / 8)
  const c = from % 8
  const onBoard = (rr, cc) => rr >= 0 && rr < 8 && cc >= 0 && cc < 8
  const cellAt = (rr, cc) => board[rr * 8 + cc]
  const isEmpty = (rr, cc) => onBoard(rr, cc) && cellAt(rr, cc) === 0
  const isEnemy = (rr, cc) =>
    onBoard(rr, cc) && cellAt(rr, cc) !== 0 && pieceSide(cellAt(rr, cc)) !== side
  // Add a square if empty or contains an enemy (i.e. legal terminal landing).
  const addLanding = (rr, cc) => {
    if (!onBoard(rr, cc)) return
    const t = cellAt(rr, cc)
    if (t === 0 || pieceSide(t) !== side) out.add(rr * 8 + cc)
  }
  // Slide in a direction until blocked. Captures the blocker if enemy.
  const ray = (dr, dc) => {
    let rr = r + dr, cc = c + dc
    while (onBoard(rr, cc)) {
      const t = cellAt(rr, cc)
      if (t === 0) { out.add(rr * 8 + cc); rr += dr; cc += dc; continue }
      if (pieceSide(t) !== side) out.add(rr * 8 + cc)
      break
    }
  }

  // White pawn: forward 1, forward 2 from rank 1, diagonal captures only.
  if (code === 1) {
    if (isEmpty(r + 1, c)) {
      out.add((r + 1) * 8 + c)
      if (r === 1 && isEmpty(r + 2, c)) out.add((r + 2) * 8 + c)
    }
    if (isEnemy(r + 1, c - 1)) out.add((r + 1) * 8 + c - 1)
    if (isEnemy(r + 1, c + 1)) out.add((r + 1) * 8 + c + 1)
  } else if (code === 7) {
    // Black pawn: same but mirrored.
    if (isEmpty(r - 1, c)) {
      out.add((r - 1) * 8 + c)
      if (r === 6 && isEmpty(r - 2, c)) out.add((r - 2) * 8 + c)
    }
    if (isEnemy(r - 1, c - 1)) out.add((r - 1) * 8 + c - 1)
    if (isEnemy(r - 1, c + 1)) out.add((r - 1) * 8 + c + 1)
  } else if (code === 2 || code === 8) {
    // Knight — 8 L-shaped jumps.
    for (const [dr, dc] of [[1,2],[2,1],[-1,2],[-2,1],[1,-2],[2,-1],[-1,-2],[-2,-1]]) {
      addLanding(r + dr, c + dc)
    }
  } else if (code === 3 || code === 9) {
    ray(1, 1); ray(1, -1); ray(-1, 1); ray(-1, -1)
  } else if (code === 4 || code === 10) {
    ray(1, 0); ray(-1, 0); ray(0, 1); ray(0, -1)
  } else if (code === 5 || code === 11) {
    ray(1, 1); ray(1, -1); ray(-1, 1); ray(-1, -1)
    ray(1, 0); ray(-1, 0); ray(0, 1); ray(0, -1)
  } else if (code === 6 || code === 12) {
    // King — 8 adjacent squares. No castling in demo.
    for (let dr = -1; dr <= 1; dr++) {
      for (let dc = -1; dc <= 1; dc++) {
        if (dr || dc) addLanding(r + dr, c + dc)
      }
    }
  }
  return out
}

// Single letter for move-list display. Pawns get '' (e2-e4, exd5 style).
const PIECE_LETTER = { 0: '', 1: '', 2: 'N', 3: 'B', 4: 'R', 5: 'Q', 6: 'K', 7: '', 8: 'N', 9: 'B', 10: 'R', 11: 'Q', 12: 'K' }

// ── Scholar's Mate (4-move checkmate) — the classic teaching example ─────
//
//   1. e2-e4   e7-e5
//   2. Bf1-c4  Nb8-c6
//   3. Qd1-h5  Ng8-f6    (black blunders by allowing Qxf7)
//   4. Qh5xf7#                ← checkmate, queen defended by the c4 bishop
//
// Each move is encoded as flat 0..63 indices (a1=0, h1=7, a8=56, h8=63).
// All seven plies pass the pseudo-legal validator in legalTargets(), so the
// same applyDemoMove path that handles user clicks can drive the animation
// without a parallel code path.
const SCHOLARS_MATE = [
  { from: 12, to: 28 }, // 1. e2-e4
  { from: 52, to: 36 }, // 1... e7-e5
  { from:  5, to: 26 }, // 2. Bf1-c4
  { from: 57, to: 42 }, // 2... Nb8-c6
  { from:  3, to: 39 }, // 3. Qd1-h5
  { from: 62, to: 45 }, // 3... Ng8-f6  (the blunder)
  { from: 39, to: 53 }, // 4. Qh5xf7#   (mate)
]
// Animation cadence (ms). FLASH highlights the source square; the move
// applies FLASH ms later and the next move starts INTERVAL after this
// move started. Keep INTERVAL > FLASH so each ply reads as discrete.
const SCHOLAR_FLASH_MS = 320
const SCHOLAR_INTERVAL_MS = 1050
const SCHOLAR_START_DELAY_MS = 700
const SCHOLAR_MATE_DELAY_MS = 600   // extra hold on the final position before banner

export default {
  name: 'chessGame',
  props: ['socket', 'wallet', 'tezos'],
  data() {
    return {
      info: CHESS_GAME_INFO,
      walletAddress: '',
      currentGameId: 0,
      activeGameId: null,
      games: {},
      // Wager (in tez) — slider-bound, clamped to contract bounds at submit.
      wagerTez: 1.0,
      minWagerTez: 0.1,
      maxWagerTez: 50.0,
      feeTez: 0.1,
      // House cut (basis points) — pulled from contract storage at refresh.
      houseCutBps: 250,
      selectedSq: null,
      pollInterval: null,
      blockchainStatus: 'idle',
      view: 'landing',
      showRules: false,
      demoBoard: openingBoard(),
      demoTurn: 1,
      lastMove: null,
      // Demo-mode capture tally per side (key = side that made the capture).
      demoCaptured: { 1: [], 2: [] },
      // Demo move history. Each entry stores the PRE-move snapshot so
      // undo can rewind in one step. We deliberately don't share this
      // stack with real-game state — on-chain moves are authoritative
      // and unundoable.
      demoHistory: [],
      // Scholar's Mate auto-play animation. demoAutoplayIdx is the
      // half-move ABOUT TO play (or just played) for progress display;
      // demoAutoplayTimer is the active setTimeout handle so we can
      // cancel cleanly on view-leave or user interaction.
      demoAutoplayActive: false,
      demoAutoplayIdx: 0,
      demoAutoplayTimer: null,
      demoCheckmate: false,
      scholarTotalPly: SCHOLARS_MATE.length,
    }
  },
  computed: {
    game() {
      return this.activeGameId == null ? null : this.games[this.activeGameId]
    },
    inRealGame() {
      return !!this.game && nat(this.game.gameStatus) === 2
    },
    displayBoard() {
      if (this.game?.board) return this.game.board
      return this.demoBoard
    },
    boardRanks() {
      const out = []
      for (let r = 7; r >= 0; r--) {
        const row = []
        for (let c = 0; c < 8; c++) {
          const idx = r * 8 + c
          const code = nat(this.displayBoard?.[idx] ?? 0)
          row.push({
            idx, r, c,
            piece: code,
            glyph: GLYPH[code] || '',
            isLight: ((r + c) % 2 === 1),
            isWhitePiece: code >= 1 && code <= 6,
            isBlackPiece: code >= 7,
          })
        }
        out.push(row)
      }
      return out
    },
    openGames() {
      return Object.entries(this.games)
        .filter(([, g]) => nat(g.gameStatus) === 0)
        .map(([id, g]) => ({ id: Number(id), ...g }))
    },
    myColor() {
      if (!this.game || !this.walletAddress) return 0
      if (this.game.white === this.walletAddress) return 1
      if (this.game.black === this.walletAddress) return 2
      // Fallback to suffix match (older record format).
      const me = this.walletAddress.slice(-4)
      if (this.game.white?.endsWith(me)) return 1
      if (this.game.black?.endsWith(me)) return 2
      return 0
    },
    myTurn() {
      if (!this.inRealGame) return true
      return nat(this.game.toMove) === this.myColor
    },
    phaseLabel() {
      if (!this.game) return 'Demo board'
      const phase = nat(this.game.gameStatus)
      if (phase === 2) {
        return `In play · ${nat(this.game.toMove) === 1 ? 'White' : 'Black'} to move`
      }
      return PHASE_LABELS[phase] || `phase ${phase}`
    },
    phaseTone() {
      if (!this.game) return 'phaseNone'
      return PHASE_TONES[nat(this.game.gameStatus)] || 'phaseNone'
    },
    turnLabel() {
      if (!this.game) return this.demoTurn === 1 ? 'White' : 'Black'
      if (nat(this.game.gameStatus) !== 2) return '—'
      return nat(this.game.toMove) === 1 ? 'White' : 'Black'
    },
    myColorLabel() {
      if (!this.inRealGame) return '—'
      if (this.myColor === 1) return 'White'
      if (this.myColor === 2) return 'Black'
      return 'Spectating'
    },
    // ── Stake / pot / house-cut math (display only) ─────────────────────
    activeWagerTez() {
      if (!this.game) return this.wagerTez
      return mutez(this.game.wager) / 1_000_000
    },
    activeHouseCutBps() {
      if (!this.game) return this.houseCutBps
      return nat(this.game.houseCutBps)
    },
    grossPotTez() {
      return this.activeWagerTez * 2
    },
    houseCutTez() {
      return this.grossPotTez * (this.activeHouseCutBps / 10000)
    },
    netPotTez() {
      return this.grossPotTez - this.houseCutTez
    },
    houseCutPercent() {
      return (this.activeHouseCutBps / 100).toFixed(2)
    },
    drawOfferedByOpponent() {
      if (!this.game) return false
      const offered = nat(this.game.drawOfferedBy)
      return offered !== 0 && offered !== this.myColor
    },
    statusBanner() {
      // Show a finished-game banner if the contract status variant is a winner.
      const s = this.game?.status
      if (!s) return ''
      if (typeof s === 'object' && s.finished) {
        if (s.finished === 'player_1_won') return 'White wins'
        if (s.finished === 'player_2_won') return 'Black wins'
        if (s.finished === 'draw') return 'Drawn game'
      }
      return ''
    },
    // ── Demo-mode UX helpers ──────────────────────────────────────────
    // Destinations for the currently-selected piece. Empty Set in real
    // games (the contract enforces legality, we don't want to mislead
    // by hiding castling/en-passant which aren't modeled here).
    legalDests() {
      if (this.inRealGame) return new Set()
      if (this.selectedSq == null) return new Set()
      return legalTargets(this.displayBoard, this.selectedSq)
    },
    demoCapturedWhite() {
      // Pieces white has captured = black pieces taken off.
      return this.demoCaptured[1].map((c) => GLYPH[c]).filter(Boolean)
    },
    demoCapturedBlack() {
      return this.demoCaptured[2].map((c) => GLYPH[c]).filter(Boolean)
    },
    // History grouped into white/black pairs for two-column rendering.
    demoMovesPaired() {
      const pairs = []
      for (let i = 0; i < this.demoHistory.length; i += 2) {
        pairs.push({
          n: Math.floor(i / 2) + 1,
          white: this.demoHistory[i]?.notation || '',
          black: this.demoHistory[i + 1]?.notation || '',
        })
      }
      return pairs
    },
    demoTurnLabel() {
      return this.demoTurn === 1 ? 'White to move' : 'Black to move'
    },
  },
  created() {
    this.socket.on('newWallet', (w) => {
      this.walletAddress = w
    })
    this.refresh()
    if (BLOCKCHAIN_ENABLED) {
      this.pollInterval = setInterval(() => this.refresh(), 8000)
    }
    // Show the Scholar's Mate showcase on first mount. We use $nextTick
    // so the DOM has painted the opening position for at least a frame
    // before the source-square flash begins — otherwise the animation
    // can start on a board that hasn't visually settled. refresh() is
    // async but the inRealGame guard inside startScholarMate() bails
    // cleanly if it resolves us into a contract-backed game.
    this.$nextTick(() => {
      if (!this.inRealGame && this.demoHistory.length === 0) {
        this.startScholarMate()
      }
    })
  },
  beforeUnmount() {
    if (this.pollInterval) clearInterval(this.pollInterval)
    this.stopScholarMate()
  },
  methods: {
    setView(v) {
      // Leaving the play view — kill any running animation so the timer
      // doesn't fire after the board has unmounted.
      if (this.view === 'play' && v !== 'play') {
        this.stopScholarMate()
      }
      this.view = v
      this.selectedSq = null
      // Entering play in demo mode with a clean slate? Show off the
      // 4-move-checkmate animation. Re-visits after the user has played
      // (demoHistory non-empty) leave the board alone.
      if (
        v === 'play' &&
        !this.inRealGame &&
        this.demoHistory.length === 0 &&
        !this.demoAutoplayActive &&
        !this.demoCheckmate
      ) {
        this.$nextTick(() => this.startScholarMate())
      }
    },
    toggleRules() {
      this.showRules = !this.showRules
    },
    sqToIJ(idx) {
      // Contract uses i = rank, j = file.
      return { i: Math.floor(idx / 8), j: idx % 8 }
    },
    async refresh() {
      try {
        const storage = await getContractStorage(CHESS_CONTRACT_ADDRESS)
        if (!storage) return
        this.currentGameId = nat(storage.currentGameId)
        this.games = storage.games || {}
        // Pull live config so UI reflects on-chain changes.
        if (storage.houseCutBps != null) this.houseCutBps = nat(storage.houseCutBps)
        if (storage.minWager != null) this.minWagerTez = mutez(storage.minWager) / 1_000_000
        if (storage.maxWager != null) this.maxWagerTez = mutez(storage.maxWager) / 1_000_000
        if (storage.fee != null) this.feeTez = mutez(storage.fee) / 1_000_000
        // Clamp slider value into bounds in case the admin moved them.
        if (this.wagerTez < this.minWagerTez) this.wagerTez = this.minWagerTez
        if (this.wagerTez > this.maxWagerTez) this.wagerTez = this.maxWagerTez
        if (this.activeGameId == null && this.currentGameId > 0) {
          this.activeGameId = this.currentGameId - 1
        }
      } catch (e) {
        console.warn('chess refresh failed:', e?.message)
      }
    },
    setWagerPercent(pct) {
      const range = this.maxWagerTez - this.minWagerTez
      this.wagerTez = +(this.minWagerTez + range * (pct / 100)).toFixed(3)
    },
    // Returns false (and sets a friendly status) when CHESS_CONTRACT_ADDRESS
    // is still a KT1XXX… placeholder for the active network — feeding one to
    // tezos.wallet.at() throws an uncaught InvalidContractAddressError.
    // Every write path checks this first: `if (!this.prepWallet()) return`.
    prepWallet() {
      if (isPlaceholderAddress(CHESS_CONTRACT_ADDRESS)) {
        this.blockchainStatus = 'Chess is not deployed on this network yet.'
        return false
      }
      this.tezos.setWalletProvider(this.wallet)
      return true
    },
    async createGame() {
      try {
        if (!this.prepWallet()) return
        this.blockchainStatus = 'creating chess game...'
        const wagerMutez = Math.round(this.wagerTez * 1_000_000)
        const feeMutez = Math.round(this.feeTez * 1_000_000)
        const totalTez = (wagerMutez + feeMutez) / 1_000_000
        const contract = await this.tezos.wallet.at(CHESS_CONTRACT_ADDRESS)
        const op = await contract.methodsObject
          .createGame({ wager: wagerMutez })
          .send({ amount: totalTez })
        await op.confirmation()
        this.blockchainStatus = `created (wager ${this.wagerTez} ꜩ).`
        await this.refresh()
      } catch (err) {
        console.error('chess create failed:', err)
        this.blockchainStatus = 'create failed'
      }
    },
    async joinGame(gameId) {
      try {
        if (!this.prepWallet()) return
        const g = this.games[gameId]
        const wagerMutez = mutez(g.wager)
        const feeMutez = Math.round(this.feeTez * 1_000_000)
        const totalTez = (wagerMutez + feeMutez) / 1_000_000
        const contract = await this.tezos.wallet.at(CHESS_CONTRACT_ADDRESS)
        const op = await contract.methodsObject
          .joinGame({ gameId })
          .send({ amount: totalTez })
        await op.confirmation()
        this.activeGameId = gameId
        this.view = 'play'
        await this.refresh()
      } catch (err) {
        console.error('chess join failed:', err)
        this.blockchainStatus = 'join failed'
      }
    },
    clickSq(cell) {
      // ── DEMO MODE: pseudo-legal moves, turn enforced, captures tracked ──
      if (!this.inRealGame) {
        // Any click during the Scholar's Mate showcase is a "let me take
        // over" gesture — kill the animation and swallow this click.
        if (this.demoAutoplayActive) {
          this.stopScholarMate()
          return
        }
        // No selection yet — pick up a piece of the side whose turn it is.
        if (this.selectedSq == null) {
          if (cell.piece === 0) return
          if (pieceSide(cell.piece) !== this.demoTurn) return
          this.selectedSq = cell.idx
          return
        }
        // Tap the same square — deselect.
        if (cell.idx === this.selectedSq) {
          this.selectedSq = null
          return
        }
        // Tap another of your own pieces — switch the selection.
        if (cell.piece !== 0 && pieceSide(cell.piece) === this.demoTurn) {
          this.selectedSq = cell.idx
          return
        }
        // Tap a destination — only allow if it's pseudo-legal.
        const targets = legalTargets(this.demoBoard, this.selectedSq)
        if (!targets.has(cell.idx)) return
        this.applyDemoMove(this.selectedSq, cell.idx)
        return
      }
      // ── REAL GAME ───────────────────────────────────────────────────
      if (!this.myTurn) return
      if (this.selectedSq == null) {
        if (cell.piece === 0) return
        const isMine =
          (this.myColor === 1 && cell.isWhitePiece) ||
          (this.myColor === 2 && cell.isBlackPiece)
        if (!isMine) return
        this.selectedSq = cell.idx
        return
      }
      if (cell.idx === this.selectedSq) {
        this.selectedSq = null
        return
      }
      this.submitMove(this.selectedSq, cell.idx)
    },
    async submitMove(fromSq, toSq) {
      try {
        if (!this.prepWallet()) return
        this.blockchainStatus = `move ${fromSq}→${toSq}...`
        // Build the new board client-side (trust-but-verify model).
        const board = { ...(this.game?.board || {}) }
        const piece = nat(board[fromSq])
        // Auto-promote pawns to queens on the back rank for now.
        const toRank = Math.floor(toSq / 8)
        let placed = piece
        if (piece === 1 && toRank === 7) placed = 5     // white pawn → queen
        if (piece === 7 && toRank === 0) placed = 11    // black pawn → queen
        board[toSq] = placed
        board[fromSq] = 0
        const move = {
          f: this.sqToIJ(fromSq),
          t: this.sqToIJ(toSq),
          promotion: placed !== piece ? 5 : null,
        }
        const contract = await this.tezos.wallet.at(CHESS_CONTRACT_ADDRESS)
        const op = await contract.methodsObject.play({
          gameId: this.activeGameId,
          newBoard: board,
          move,
        }).send()
        await op.confirmation()
        this.lastMove = { from: fromSq, to: toSq }
        this.blockchainStatus = 'moved.'
        this.selectedSq = null
        await this.refresh()
      } catch (err) {
        console.error('move failed:', err)
        this.blockchainStatus = 'illegal or failed'
        this.selectedSq = null
      }
    },
    async giveup() {
      try {
        if (!this.prepWallet()) return
        const contract = await this.tezos.wallet.at(CHESS_CONTRACT_ADDRESS)
        const op = await contract.methodsObject
          .giveup({ gameId: this.activeGameId }).send()
        await op.confirmation()
        await this.refresh()
      } catch (err) { console.error('giveup failed:', err) }
    },
    async claimCheckmate() {
      try {
        if (!this.prepWallet()) return
        const contract = await this.tezos.wallet.at(CHESS_CONTRACT_ADDRESS)
        const op = await contract.methodsObject
          .claim_checkmate({ gameId: this.activeGameId }).send()
        await op.confirmation()
        await this.refresh()
      } catch (err) { console.error('claim checkmate failed:', err) }
    },
    async offerDraw() {
      try {
        if (!this.prepWallet()) return
        const contract = await this.tezos.wallet.at(CHESS_CONTRACT_ADDRESS)
        const op = await contract.methodsObject
          .offer_draw({ gameId: this.activeGameId }).send()
        await op.confirmation()
        await this.refresh()
      } catch (err) { console.error('offerDraw failed:', err) }
    },
    async denyDraw() {
      try {
        if (!this.prepWallet()) return
        const contract = await this.tezos.wallet.at(CHESS_CONTRACT_ADDRESS)
        const op = await contract.methodsObject
          .deny_draw({ gameId: this.activeGameId }).send()
        await op.confirmation()
        await this.refresh()
      } catch (err) { console.error('denyDraw failed:', err) }
    },
    async claimStalemate() {
      try {
        if (!this.prepWallet()) return
        const contract = await this.tezos.wallet.at(CHESS_CONTRACT_ADDRESS)
        const op = await contract.methodsObject
          .claim_stalemate({ gameId: this.activeGameId }).send()
        await op.confirmation()
        await this.refresh()
      } catch (err) { console.error('claim stalemate failed:', err) }
    },
    async claimByTimeout() {
      try {
        if (!this.prepWallet()) return
        const contract = await this.tezos.wallet.at(CHESS_CONTRACT_ADDRESS)
        const op = await contract.methodsObject
          .claimByTimeout({ gameId: this.activeGameId }).send()
        await op.confirmation()
        await this.refresh()
      } catch (err) { console.error('claimByTimeout failed:', err) }
    },
    async cancelGame() {
      try {
        if (!this.prepWallet()) return
        const contract = await this.tezos.wallet.at(CHESS_CONTRACT_ADDRESS)
        const op = await contract.methodsObject
          .cancelGame({ gameId: this.activeGameId }).send()
        await op.confirmation()
        await this.refresh()
      } catch (err) { console.error('cancelGame failed:', err) }
    },
    resetDemo() {
      this.stopScholarMate()
      this.demoBoard = openingBoard()
      this.demoTurn = 1
      this.lastMove = null
      this.selectedSq = null
      this.demoCaptured = { 1: [], 2: [] }
      this.demoHistory = []
      this.demoCheckmate = false
    },
    undoDemo() {
      // Pop the last snapshot (which is the state right before that move
      // was applied) and restore everything from it.
      if (this.inRealGame) return
      this.stopScholarMate()
      const last = this.demoHistory.pop()
      if (!last) return
      this.demoBoard = last.prevBoard
      this.demoTurn = last.prevTurn
      this.demoCaptured = last.prevCaptured
      this.lastMove = last.prevLastMove
      this.selectedSq = null
      this.demoCheckmate = false
    },
    // Shared mover used by BOTH a player click and the Scholar's Mate
    // animation. Assumes the move is already validated as pseudo-legal —
    // the caller is responsible for that check.
    applyDemoMove(fromSq, toSq) {
      const fromPiece = this.demoBoard[fromSq]
      const captured = this.demoBoard[toSq]
      // Auto-promote pawns reaching the back rank to queens.
      const toRank = Math.floor(toSq / 8)
      let placed = fromPiece
      if (fromPiece === 1 && toRank === 7) placed = 5
      if (fromPiece === 7 && toRank === 0) placed = 11

      // Snapshot for undo: capture board+turn+captured BEFORE applying.
      // Notation describes the move just made (e.g. "Nxe4", "e7-e8=Q").
      const sep = captured ? 'x' : '-'
      const promo = placed !== fromPiece ? '=' + (PIECE_LETTER[placed] || 'Q') : ''
      const notation = `${PIECE_LETTER[fromPiece] || ''}${squareName(fromSq)}${sep}${squareName(toSq)}${promo}`
      this.demoHistory.push({
        prevBoard: [...this.demoBoard],
        prevTurn: this.demoTurn,
        prevCaptured: { 1: [...this.demoCaptured[1]], 2: [...this.demoCaptured[2]] },
        prevLastMove: this.lastMove,
        notation,
      })

      const next = [...this.demoBoard]
      next[fromSq] = 0
      next[toSq] = placed
      if (captured) {
        // Replace the whole object so Vue re-renders the dependent
        // computed cleanly even when we later restore via undo.
        this.demoCaptured = {
          1: this.demoTurn === 1 ? [...this.demoCaptured[1], captured] : this.demoCaptured[1],
          2: this.demoTurn === 2 ? [...this.demoCaptured[2], captured] : this.demoCaptured[2],
        }
      }
      this.demoBoard = next
      this.lastMove = { from: fromSq, to: toSq }
      this.selectedSq = null
      this.demoTurn = this.demoTurn === 1 ? 2 : 1
    },
    // ── Scholar's Mate showcase ─────────────────────────────────────────
    // Kicks off a setTimeout-driven recursion that walks SCHOLARS_MATE one
    // ply at a time: highlight source square → apply move → schedule next.
    // We use chained setTimeouts (rather than setInterval) so each cycle
    // can self-cancel cleanly if the user interrupts.
    startScholarMate() {
      // A real game outranks the showcase — don't mutate demo state when
      // a contract-backed game is loaded.
      if (this.inRealGame) return
      this.stopScholarMate()
      // Wipe to opening but DON'T call resetDemo — it calls stopScholarMate
      // back into us; safe but noisy. Inline the reset instead.
      this.demoBoard = openingBoard()
      this.demoTurn = 1
      this.lastMove = null
      this.selectedSq = null
      this.demoCaptured = { 1: [], 2: [] }
      this.demoHistory = []
      this.demoCheckmate = false
      this.demoAutoplayActive = true
      this.demoAutoplayIdx = 0
      // Pause on the opening for a beat so the user reads "this is the
      // starting position" before pieces start moving.
      this.demoAutoplayTimer = setTimeout(() => this.playScholarMove(0), SCHOLAR_START_DELAY_MS)
    },
    playScholarMove(idx) {
      if (!this.demoAutoplayActive) return
      // refresh() can flip inRealGame asynchronously while the animation
      // is in flight. Abort cleanly rather than scribbling on the demo
      // board while the user is staring at a real game.
      if (this.inRealGame) { this.stopScholarMate(); return }
      if (idx >= SCHOLARS_MATE.length) {
        // Sequence done. Final hold, then reveal the checkmate banner.
        this.demoAutoplayTimer = setTimeout(() => {
          this.demoAutoplayActive = false
          this.demoCheckmate = true
          this.demoAutoplayTimer = null
        }, SCHOLAR_MATE_DELAY_MS)
        return
      }
      const move = SCHOLARS_MATE[idx]
      this.demoAutoplayIdx = idx
      // Flash the source square first so the eye tracks where the
      // move comes from before the piece teleports to its target.
      this.selectedSq = move.from
      this.demoAutoplayTimer = setTimeout(() => {
        if (!this.demoAutoplayActive) return
        this.applyDemoMove(move.from, move.to)
        this.demoAutoplayTimer = setTimeout(
          () => this.playScholarMove(idx + 1),
          SCHOLAR_INTERVAL_MS - SCHOLAR_FLASH_MS,
        )
      }, SCHOLAR_FLASH_MS)
    },
    stopScholarMate() {
      if (this.demoAutoplayTimer) clearTimeout(this.demoAutoplayTimer)
      this.demoAutoplayTimer = null
      this.demoAutoplayActive = false
      // Don't touch demoCheckmate here — the banner is dismissed via its
      // own controls or by reset/replay, not by side-effect.
    },
  },
}
</script>

<template>
  <div class="gameManagement chRoot">
    <!-- ───── Landing view ────────────────────────────────────────────── -->
    <template v-if="view === 'landing'">
      <div class="chHero chHero--solo">
        <div class="chHeroBrand">
          <div class="chHeroEyebrow">CHESS · H2H · WAGERED · ON-CHAIN</div>
          <div class="chHeroTitle">Standard chess. Stake set per match. House takes a small cut.</div>
          <div class="chHeroSub">
            White moves first. Pawns auto-promote to queens. Resign, claim
            checkmate, offer a draw, or claim by timeout if your opponent
            stalls. Each side locks an equal wager; on settlement the house
            keeps a small percentage of the combined pot, and the winner takes
            the rest. Drawn games refund both sides minus the cut.
          </div>
        </div>
      </div>
    </template>

    <!-- ─── SHARED: Scholar's Mate banner + animated 3D table + demo panel
         Always rendered (lives outside both view branches). The animation
         auto-starts in created() and writes to demoBoard, so landing
         visitors see the showcase before ever clicking 'Open board'.
         The 'view === landing' template above closes here; the v-else
         play branch below resumes from where this section ends. -->
      <div v-if="!inRealGame && demoAutoplayActive" class="chScholarBar">
        <span class="chScholarPlay" aria-hidden="true">▶</span>
        <span class="chScholarLabel">Scholar's Mate · 4-move checkmate</span>
        <span class="chScholarProgress">{{ Math.min(demoAutoplayIdx + 1, scholarTotalPly) }} / {{ scholarTotalPly }}</span>
        <button class="demoBtn" @click="stopScholarMate">Stop</button>
      </div>
      <div v-else-if="!inRealGame && demoCheckmate" class="chMateBanner">
        <div class="chMateIcon" aria-hidden="true">♛</div>
        <div class="chMateLines">
          <div class="chMateTop">CHECKMATE</div>
          <div class="chMateSub">Scholar's Mate · Qxf7#</div>
        </div>
        <button class="demoBtn demoBtn--primary" @click="startScholarMate">Replay</button>
        <button class="demoBtn" @click="resetDemo">Free play</button>
        <button class="chMateDismiss" @click="demoCheckmate = false" aria-label="Dismiss">×</button>
      </div>

      <div class="chScene">
        <div class="chTable">
          <div class="chTableRail" aria-hidden="true"></div>
          <div class="chCloth">
            <div class="chTableBrand">CHESS · CLUB ROOM</div>
            <div class="chBoard">
              <div class="chFileRow">
                <div class="chLabelCorner"></div>
                <div v-for="f in FILES" :key="'top-' + f" class="chFileLabel">{{ f }}</div>
                <div class="chLabelCorner"></div>
              </div>
              <div v-for="(row, r) in boardRanks" :key="r" class="chBoardRow">
                <div class="chRankLabel">{{ 8 - r }}</div>
                <div
                  v-for="cell in row"
                  :key="cell.idx"
                  :class="[
                    'chCell',
                    cell.isLight ? 'chCell--light' : 'chCell--dark',
                    selectedSq === cell.idx ? 'chCell--selected' : '',
                    lastMove && (lastMove.from === cell.idx || lastMove.to === cell.idx) ? 'chCell--lastMove' : '',
                    legalDests.has(cell.idx) && cell.piece === 0 ? 'chCell--legal' : '',
                    legalDests.has(cell.idx) && cell.piece !== 0 ? 'chCell--legalCapture' : '',
                    (myTurn && (cell.piece !== 0 || selectedSq != null)) ? 'chCell--tappable' : '',
                  ]"
                  @click="clickSq(cell)"
                >
                  <span
                    v-if="cell.piece"
                    :class="['chPiece', cell.isWhitePiece ? 'chPiece--white' : 'chPiece--black']"
                  >{{ cell.glyph }}</span>
                </div>
                <div class="chRankLabel">{{ 8 - r }}</div>
              </div>
              <div class="chFileRow">
                <div class="chLabelCorner"></div>
                <div v-for="f in FILES" :key="'bot-' + f" class="chFileLabel">{{ f }}</div>
                <div class="chLabelCorner"></div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div v-if="!inRealGame" class="chDemoPanel">
        <div class="chDemoBar">
          <div class="chDemoTurn">
            <span class="chDemoTurnDot" :class="demoTurn === 1 ? 'chDot--white' : 'chDot--black'"></span>
            <span class="chDemoTurnLabel">{{ demoTurnLabel }}</span>
          </div>
          <div class="chDemoMeta">
            <span class="chDemoMetaLabel">Moves</span>
            <span class="chDemoMetaValue">{{ demoHistory.length }}</span>
          </div>
        </div>

        <div class="chCapStrip">
          <div class="chCapSide">
            <div class="chCapLbl">White captured</div>
            <div class="chCapRow">
              <span
                v-for="(g, i) in demoCapturedWhite"
                :key="'wc' + i"
                class="chCapGlyph chCapGlyph--black"
              >{{ g }}</span>
              <span v-if="!demoCapturedWhite.length" class="chCapEmpty">—</span>
            </div>
          </div>
          <div class="chCapSide">
            <div class="chCapLbl">Black captured</div>
            <div class="chCapRow">
              <span
                v-for="(g, i) in demoCapturedBlack"
                :key="'bc' + i"
                class="chCapGlyph chCapGlyph--white"
              >{{ g }}</span>
              <span v-if="!demoCapturedBlack.length" class="chCapEmpty">—</span>
            </div>
          </div>
        </div>

        <div v-if="demoMovesPaired.length" class="chMoveList">
          <div class="chMoveListHdr">Move history</div>
          <div class="chMoveListScroll">
            <div class="chMoveListRow chMoveListRow--head">
              <span class="chMoveN">#</span>
              <span class="chMoveCol">White</span>
              <span class="chMoveCol">Black</span>
            </div>
            <div
              v-for="p in demoMovesPaired"
              :key="'mv' + p.n"
              class="chMoveListRow"
            >
              <span class="chMoveN">{{ p.n }}.</span>
              <span class="chMoveCol">{{ p.white }}</span>
              <span class="chMoveCol">{{ p.black }}</span>
            </div>
          </div>
        </div>

        <div class="chDemoHint">
          <span class="demoHintDot"></span>
          <span class="demoHintLabel">DEMO</span>
          <span class="demoHintBody">Tap your piece, then a highlighted square. Legal moves only.</span>
          <button class="demoBtn" :disabled="!demoHistory.length || demoAutoplayActive" @click="undoDemo">Undo</button>
          <button class="demoBtn" @click="resetDemo">Reset board</button>
          <button class="demoBtn" @click="startScholarMate">▶ Scholar's Mate</button>
        </div>
      </div>

    <template v-if="view === 'landing'">
      <div class="chStatusRow">
        <div :class="['chPill', phaseTone]">
          <div class="chPillLabel">Phase</div>
          <div class="chPillValue">{{ phaseLabel }}</div>
        </div>
        <div class="chPill">
          <div class="chPillLabel">Game</div>
          <div class="chPillValue">{{ activeGameId == null ? '—' : '#' + activeGameId }}</div>
        </div>
        <div class="chPill">
          <div class="chPillLabel">Wager (each)</div>
          <div class="chPillValue">{{ activeWagerTez.toFixed(3) }} ꜩ</div>
          <div class="chPillFootnote">+ {{ feeTez.toFixed(2) }} ꜩ fee</div>
        </div>
        <div class="chPill chPill--house">
          <div class="chPillLabel">House cut</div>
          <div class="chPillValue">{{ houseCutPercent }}%</div>
          <div class="chPillFootnote">{{ houseCutTez.toFixed(4) }} ꜩ on this pot</div>
        </div>
        <div class="chPill chPill--pot">
          <div class="chPillLabel">Net pot to winner</div>
          <div class="chPillValue">{{ netPotTez.toFixed(3) }} ꜩ</div>
          <div class="chPillFootnote">gross {{ grossPotTez.toFixed(3) }} ꜩ</div>
        </div>
        <div class="chPill">
          <div class="chPillLabel">Your side</div>
          <div class="chPillValue">{{ myColorLabel }}</div>
        </div>
      </div>

      <!-- ── Wager controls ──────────────────────────────────────────── -->
      <div class="chWagerCard">
        <div class="chWagerHead">
          <div class="chWagerTitle">Set your wager</div>
          <div class="chWagerHint">
            min {{ minWagerTez.toFixed(2) }} ꜩ · max {{ maxWagerTez.toFixed(2) }} ꜩ
          </div>
        </div>
        <div class="chWagerRow">
          <input
            type="range"
            class="chWagerSlider"
            :min="minWagerTez"
            :max="maxWagerTez"
            step="0.05"
            v-model.number="wagerTez"
          />
          <div class="chWagerValue">{{ wagerTez.toFixed(3) }} ꜩ</div>
        </div>
        <div class="chWagerQuick">
          <button class="chQuickBtn" @click="setWagerPercent(0)">Min</button>
          <button class="chQuickBtn" @click="setWagerPercent(25)">25%</button>
          <button class="chQuickBtn" @click="setWagerPercent(50)">50%</button>
          <button class="chQuickBtn" @click="setWagerPercent(75)">75%</button>
          <button class="chQuickBtn" @click="setWagerPercent(100)">Max</button>
        </div>
        <div class="chWagerMath">
          <div class="chMathRow">
            <span class="chMathLabel">You lock</span>
            <span class="chMathValue">{{ wagerTez.toFixed(3) }} ꜩ + {{ feeTez.toFixed(2) }} ꜩ fee</span>
          </div>
          <div class="chMathRow">
            <span class="chMathLabel">Pot if matched</span>
            <span class="chMathValue">{{ (wagerTez * 2).toFixed(3) }} ꜩ</span>
          </div>
          <div class="chMathRow">
            <span class="chMathLabel">House keeps</span>
            <span class="chMathValue chMathValue--house">
              {{ ((wagerTez * 2) * (houseCutBps / 10000)).toFixed(4) }} ꜩ
              ({{ (houseCutBps / 100).toFixed(2) }}%)
            </span>
          </div>
          <div class="chMathRow chMathRow--strong">
            <span class="chMathLabel">Winner takes</span>
            <span class="chMathValue chMathValue--win">
              {{ ((wagerTez * 2) * (1 - houseCutBps / 10000)).toFixed(3) }} ꜩ
            </span>
          </div>
        </div>
      </div>

      <div class="rowFlex chPrimaryRow">
        <div class="actionButton chPrimary" @click="setView('play')">Open board</div>
        <div class="actionButton" @click="createGame">
          New wagered game · {{ wagerTez.toFixed(2) }} ꜩ
        </div>
        <div class="actionButtonHelp" @click="toggleRules">
          {{ showRules ? 'Hide rules' : 'How it works' }}
        </div>
      </div>

      <div v-if="openGames.length" class="rowFlex">
        <div class="gameInfo chOpenLabel">Open challenges:</div>
        <div
          v-for="g in openGames"
          :key="g.id"
          class="actionButton"
          @click="joinGame(g.id)"
        >
          Join #{{ g.id }} — {{ (Number(g.wager) / 1000000).toFixed(2) }} ꜩ
        </div>
      </div>

      <div v-if="showRules" class="chRules">
        <ol>
          <li v-for="(line, i) in info" :key="i">{{ line }}</li>
        </ol>
        <ol class="chRulesGambling">
          <li>
            <strong>Stake.</strong> Both sides lock the same wager (plus a flat
            holder fee per transaction).
          </li>
          <li>
            <strong>House cut.</strong> The contract retains
            {{ houseCutPercent }}% of the combined pot at settlement; the
            remainder pays the winner. Configurable by admin (capped at 10%).
          </li>
          <li>
            <strong>Draw.</strong> Each side gets back their wager minus half
            the house cut.
          </li>
          <li>
            <strong>Cancel.</strong> The creator can cancel an un-joined game
            and reclaim the wager (the fee is non-refundable).
          </li>
          <li>
            <strong>Timeout.</strong> If your opponent stalls beyond the stale
            window, you can claim the pot directly.
          </li>
        </ol>
      </div>

      <div class="gameInfo chStatusLine">{{ blockchainStatus }}</div>
    </template>

    <!-- ───── Play view ───────────────────────────────────────────────── -->
    <template v-else>
      <div class="rowFlex chPlayHeader">
        <div class="actionButton chBackBtn" @click="setView('landing')">‹ Lobby</div>
        <div class="gameInfo">
          {{ game ? 'Game #' + activeGameId + ' · ' + phaseLabel : 'Demo board' }}
        </div>
        <div class="actionButton" @click="refresh">Refresh</div>
      </div>

      <div class="rowFlex">
        <div class="txlRank">Turn: <strong>{{ turnLabel }}</strong></div>
        <div class="txlRank">Your side: {{ myColorLabel }}</div>
        <div class="txlRank">Wager: {{ activeWagerTez.toFixed(3) }} ꜩ</div>
        <div class="txlRank">House: {{ houseCutPercent }}%</div>
        <div class="txlRank">Net pot: {{ netPotTez.toFixed(3) }} ꜩ</div>
      </div>

      <div v-if="statusBanner" class="chFinalBanner">{{ statusBanner }}</div>

      <!-- Scholar's Mate banner, 3D table, and demo panel now live in the
           shared section above this v-else block, so they render on both
           the lobby/landing AND the play views. -->

      <div v-if="inRealGame" class="chPlayActions">
        <div class="chPlayActionsRow">
          <div class="actionButton" @click="claimCheckmate">Claim checkmate</div>
          <div class="actionButtonHelp" @click="offerDraw">
            {{ drawOfferedByOpponent ? 'Accept draw' : 'Offer draw' }}
          </div>
          <div v-if="drawOfferedByOpponent" class="actionButtonHelp" @click="denyDraw">Decline draw</div>
          <div class="actionButtonHelp" @click="claimStalemate">Claim stalemate</div>
        </div>
        <div class="chPlayActionsRow">
          <div class="actionButtonHelp" @click="giveup">Give up (resign)</div>
          <div class="actionButtonHelp" @click="claimByTimeout">Claim by timeout</div>
        </div>
        <div class="chPotLine">
          Settlement → winner: <strong>{{ netPotTez.toFixed(3) }} ꜩ</strong>,
          house: <strong>{{ houseCutTez.toFixed(4) }} ꜩ</strong>
          ({{ houseCutPercent }}% of {{ grossPotTez.toFixed(3) }} ꜩ pot)
        </div>
      </div>

      <div class="rowFlex">
        <div class="actionButton" @click="setView('landing')">Back to lobby</div>
        <div v-if="game && Number(game.gameStatus) === 0 && myColor === 1"
             class="actionButtonHelp" @click="cancelGame">Cancel open game</div>
      </div>

      <div class="gameInfo chStatusLine">{{ blockchainStatus }}</div>
    </template>
  </div>
</template>

<style scoped>
.chRoot { font-family: 'EB Garamond', serif; color: #efeae2; }

/* ─── Hero ─────────────────────────────────────────────────────────── */
.chHero {
  display: flex; flex-direction: row; gap: 18px;
  padding: 16px 14px; margin: 8px 4px 14px;
  border-radius: 14px;
  background:
    radial-gradient(ellipse at 80% 20%, rgba(212, 162, 78, 0.15) 0%, transparent 60%),
    linear-gradient(135deg, #1a0e08 0%, #0a0604 100%);
  box-shadow:
    inset 0 0 0 1px rgba(255, 255, 255, 0.06),
    0 8px 22px rgba(0, 0, 0, 0.45);
}
.chHeroBrand { flex: 1.4; min-width: 0; }
.chHeroBoard { flex: 1; display: flex; align-items: center; justify-content: center; }
.chHeroSvg { width: 100%; max-width: 180px; }

/* Solo hero — used when the brand is the only thing in the hero
   (because the animated 3D board now sits below the hero, not beside
   it). Center the brand text so it doesn't look orphaned in a wide
   flex row with nothing on the right. */
.chHero--solo {
  flex-direction: column;
  align-items: center;
  text-align: center;
}
.chHero--solo .chHeroBrand {
  flex: 0 1 auto;
  max-width: 720px;
}
.chHeroEyebrow { font-size: 10px; letter-spacing: 4px; font-weight: 700; color: rgba(245,196,81,0.75); margin-bottom: 6px; }
.chHeroTitle { font-size: clamp(20px, 4.5vw, 30px); line-height: 1.1; font-weight: 700; color: #fff; margin-bottom: 8px; }
.chHeroSub { font-size: 13px; line-height: 1.4; color: rgba(255, 255, 255, 0.78); }

/* ─── Status pills ──────────────────────────────────────────────────── */
.chStatusRow { display: flex; flex-wrap: wrap; gap: 6px; margin: 0 4px 12px; }
.chPill { flex: 1 1 110px; min-width: 110px; padding: 8px 10px; border-radius: 8px;
  background: rgba(255, 255, 255, 0.04); border: 1px solid rgba(255, 255, 255, 0.08); }
.chPillLabel { font-size: 9px; letter-spacing: 2px; text-transform: uppercase; color: rgba(255,255,255,0.55); }
.chPillValue { font-size: 16px; font-weight: 700; color: #fff; margin-top: 2px; }
.chPillFootnote { font-size: 10px; color: rgba(255,255,255,0.55); margin-top: 2px; }
.chPill--house { border-color: rgba(196, 82, 79, 0.45); background: rgba(196, 82, 79, 0.08); }
.chPill--pot { border-color: rgba(118, 196, 138, 0.55); background: rgba(118, 196, 138, 0.08); }
.phaseOpen { border-color: rgba(118, 196, 138, 0.5); }
.phaseLive { border-color: rgba(245, 196, 81, 0.6); }
.phaseDone { border-color: rgba(196, 82, 79, 0.5); }
.phaseNone { border-color: rgba(255, 255, 255, 0.08); }

.chPrimaryRow { margin-top: 4px; }
.chPrimary {
  background: linear-gradient(135deg, #4a2c1a 0%, #2a1a10 100%);
  border-color: #f5c451;
  font-weight: 700; letter-spacing: 1px; text-transform: uppercase;
}
.chOpenLabel { flex: 0 0 auto; align-self: center; font-size: 12px; }

/* ─── Wager card (gambling controls) ────────────────────────────────── */
.chWagerCard {
  margin: 4px 4px 12px;
  padding: 12px 14px;
  border-radius: 12px;
  background:
    linear-gradient(135deg, rgba(245,196,81,0.08) 0%, rgba(245,196,81,0.02) 100%);
  border: 1px solid rgba(245, 196, 81, 0.30);
  box-shadow: inset 0 0 0 1px rgba(0, 0, 0, 0.18);
}
.chWagerHead { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 10px; }
.chWagerTitle { font-size: 13px; letter-spacing: 2px; text-transform: uppercase; color: #f5c451; font-weight: 700; }
.chWagerHint { font-size: 11px; color: rgba(255,255,255,0.55); }
.chWagerRow { display: flex; align-items: center; gap: 12px; }
.chWagerSlider { flex: 1; appearance: none; height: 5px; background: rgba(255,255,255,0.15); border-radius: 4px; outline: none; }
.chWagerSlider::-webkit-slider-thumb {
  appearance: none; width: 18px; height: 18px; border-radius: 50%;
  background: #f5c451; cursor: pointer;
  box-shadow: 0 0 6px rgba(245, 196, 81, 0.7);
}
.chWagerSlider::-moz-range-thumb {
  width: 18px; height: 18px; border-radius: 50%;
  background: #f5c451; cursor: pointer; border: none;
}
.chWagerValue { min-width: 80px; text-align: right; font-size: 17px; font-weight: 700; color: #fff; }
.chWagerQuick { display: flex; gap: 6px; margin-top: 8px; flex-wrap: wrap; }
.chQuickBtn {
  background: transparent; border: 1px solid rgba(245, 196, 81, 0.4);
  color: #f5c451; padding: 4px 10px; border-radius: 4px;
  font-family: 'EB Garamond', serif; font-size: 11px; letter-spacing: 1.5px;
  font-weight: 700; cursor: pointer;
}
.chQuickBtn:hover { background: rgba(245, 196, 81, 0.1); }

.chWagerMath { margin-top: 12px; padding-top: 10px; border-top: 1px dashed rgba(245, 196, 81, 0.25); }
.chMathRow { display: flex; justify-content: space-between; padding: 2px 0; font-size: 12px; color: rgba(255,255,255,0.78); }
.chMathRow--strong { font-size: 13px; padding-top: 6px; margin-top: 4px; border-top: 1px solid rgba(255,255,255,0.08); }
.chMathLabel { letter-spacing: 1px; text-transform: uppercase; font-size: 10px; color: rgba(255,255,255,0.55); }
.chMathValue { font-weight: 600; }
.chMathValue--house { color: rgba(229, 121, 121, 0.95); }
.chMathValue--win { color: #b9e6a3; font-size: 14px; }

.chRules { margin: 8px 4px 12px; padding: 12px 16px; border-radius: 8px;
  background: rgba(255, 255, 255, 0.03); border: 1px solid rgba(255, 255, 255, 0.08); }
.chRules ol { margin: 0; padding-left: 20px; font-size: 13px; line-height: 1.55; color: rgba(255,255,255,0.85); }
.chRulesGambling { margin-top: 10px !important; padding-top: 10px; border-top: 1px dashed rgba(245, 196, 81, 0.2); }
.chRulesGambling li { color: rgba(255,255,255,0.78); font-size: 12.5px; }
.chRulesGambling strong { color: #f5c451; }

.chStatusLine { font-size: 12px; color: #d4a24e; font-style: italic; }

/* ─── Play header ───────────────────────────────────────────────────── */
.chPlayHeader { margin: 4px 0 8px; }
.chBackBtn { flex: 0 0 auto; min-width: 90px; }
.chFinalBanner {
  text-align: center; margin: 6px 4px 8px;
  padding: 8px 12px; border-radius: 8px;
  background: linear-gradient(135deg, rgba(118,196,138,0.18), rgba(118,196,138,0.04));
  border: 1px solid rgba(118, 196, 138, 0.45);
  color: #d8f0ce; font-weight: 700; letter-spacing: 1px;
}

/* ─── Play actions / pot summary ────────────────────────────────────── */
.chPlayActions { margin: 8px 4px; padding: 8px; border-radius: 8px;
  background: rgba(255, 255, 255, 0.03); border: 1px solid rgba(255, 255, 255, 0.08); }
.chPlayActionsRow { display: flex; flex-wrap: wrap; gap: 6px; margin: 4px 0; }
.chPotLine { font-size: 11.5px; color: rgba(255,255,255,0.7); margin-top: 6px; padding-top: 6px; border-top: 1px dashed rgba(255,255,255,0.08); }
.chPotLine strong { color: #f5c451; }

/* ─── Tilted 3D table (mirrors AD adTableWrap pattern) ────────────────
   Three nested layers like AD:
     .chScene   → the room: ambient gradients, perspective origin, spotlight
     .chTable   → the tilted plane: rotateX so the back recedes
     .chTableRail → lacquered wood ring around the cloth
     .chCloth   → burgundy felt tablecloth the board rests on
     .chBoard   → the actual 8x8 chess board, unchanged
   We tilt the whole table (not just the board) so the rank/file labels,
   wood frame, and felt edges all share the same vanishing point. */
.chScene {
  --ch-room-bg:
    /* warm overhead spotlight */
    radial-gradient(ellipse 60% 45% at 50% -10%, rgba(255, 220, 140, 0.28) 0%, transparent 60%),
    /* floor vignette */
    radial-gradient(ellipse 80% 60% at 50% 110%, rgba(0, 0, 0, 0.55) 0%, transparent 65%),
    /* faint wood-panel verticals on the back wall */
    repeating-linear-gradient(90deg,
      rgba(0, 0, 0, 0.22) 0px, rgba(0, 0, 0, 0.22) 1px,
      transparent 1px, transparent 36px),
    /* base wall: dark walnut */
    linear-gradient(180deg, #1a100a 0%, #2a1a10 45%, #14090a 100%);
  position: relative;
  display: flex;
  justify-content: center;
  align-items: flex-start;
  margin: 8px 0 18px;
  padding: 44px 18px 56px;
  border-radius: 18px;
  background: var(--ch-room-bg);
  perspective: 1400px;
  perspective-origin: 50% -10%;
  overflow: hidden;
  box-shadow:
    inset 0 0 0 1px rgba(255, 255, 255, 0.04),
    inset 0 -40px 60px rgba(0, 0, 0, 0.55);
}
/* Overhead bulb glow — pure decoration, sells the spotlit table look. */
.chScene::before {
  content: '';
  position: absolute;
  top: -20px; left: 50%;
  width: 260px; height: 260px;
  transform: translateX(-50%);
  background: radial-gradient(circle, rgba(255, 220, 140, 0.22) 0%, transparent 60%);
  pointer-events: none;
}

.chTable {
  position: relative;
  width: clamp(320px, 92vw, 540px);
  /* Aspect a touch taller than the board itself so cloth fringe shows
     above and below the wood frame. */
  aspect-ratio: 9 / 10;
  border-radius: 22px;
  overflow: hidden;
  /* Strong forward tilt — same angle/origin as AD so the page reads
     consistently. preserve-3d lets the board's hover/selection
     transforms compose with the tilt instead of being flattened. */
  transform: rotateX(22deg);
  transform-origin: center bottom;
  transform-style: preserve-3d;
  box-shadow:
    0 26px 44px rgba(0, 0, 0, 0.65),
    0 10px 18px rgba(0, 0, 0, 0.55),
    inset 0 0 0 1px rgba(255, 255, 255, 0.06);
}

/* Lacquered wood ring around the cloth — three stacked gradients fake a
   walnut frame without a texture file. Matches AD's adRail recipe. */
.chTableRail {
  position: absolute;
  inset: 0;
  border-radius: 22px;
  background:
    radial-gradient(ellipse at 50% 0%, rgba(255, 220, 160, 0.18) 0%, transparent 38%),
    radial-gradient(ellipse at center, transparent 56%, rgba(0, 0, 0, 0.5) 100%),
    /* fine cross-grain */
    repeating-linear-gradient(90deg,
      rgba(0, 0, 0, 0.18) 0px, rgba(0, 0, 0, 0.18) 1px,
      transparent 1px, transparent 4px),
    /* main grain stripes, slight angle for life */
    repeating-linear-gradient(8deg,
      #3a2214 0px, #4a2c1a 6px, #3a2214 12px, #2a1810 18px),
    linear-gradient(135deg, #2a1810 0%, #5a3620 50%, #1f120a 100%);
  box-shadow:
    inset 0 1px 0 rgba(255, 220, 160, 0.20),
    inset 0 -2px 6px rgba(0, 0, 0, 0.55);
}

/* The tablecloth itself — burgundy felt with a hot spot under the
   overhead light, fine fabric nap from layered radial-gradients, and
   a gold piping inset to echo AD's felt without copying its green. */
.chCloth {
  position: absolute;
  inset: 18px;
  border-radius: 14px;
  background:
    radial-gradient(ellipse at 50% 30%, #6a1a25 0%, #38101a 55%, #1a0608 100%);
  background-image:
    /* fabric nap — two offset stipple layers */
    radial-gradient(rgba(255, 255, 255, 0.035) 0.6px, transparent 0.6px),
    radial-gradient(rgba(0, 0, 0, 0.10) 0.6px, transparent 0.6px),
    radial-gradient(ellipse at 50% 30%, #6a1a25 0%, #38101a 55%, #1a0608 100%);
  background-size: 3px 3px, 5px 5px, auto;
  background-position: 0 0, 1px 2px, 0 0;
  box-shadow:
    inset 0 0 0 1px rgba(0, 0, 0, 0.55),
    inset 0 0 0 3px rgba(245, 196, 81, 0.10),
    inset 0 8px 22px rgba(0, 0, 0, 0.50),
    inset 0 -4px 12px rgba(0, 0, 0, 0.35);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 18px 14px 14px;
  transform-style: preserve-3d;
}
.chTableBrand {
  letter-spacing: 5px;
  font-size: 11px;
  font-weight: 700;
  color: rgba(245, 196, 81, 0.70);
  text-shadow:
    0 1px 0 rgba(0, 0, 0, 0.6),
    0 0 12px rgba(245, 196, 81, 0.35);
  margin-bottom: 10px;
}

/* The actual 8x8 board — same wood-frame styling as before, just with a
   tighter shadow now that it sits on the felt instead of an empty page.
   translateZ lifts it a hair off the cloth so the tilt reads as "board
   sitting on cloth" rather than "board painted onto cloth". */
.chBoard {
  display: inline-block;
  padding: 8px;
  border-radius: 10px;
  background: linear-gradient(135deg, #5a3a1f 0%, #2e1d0f 100%);
  box-shadow:
    inset 0 0 0 1px rgba(0, 0, 0, 0.45),
    0 10px 22px rgba(0, 0, 0, 0.55),
    0 2px 4px rgba(0, 0, 0, 0.45);
  transform: translateZ(6px);
}
.chFileRow { display: flex; align-items: center; }
.chBoardRow { display: flex; align-items: center; }
.chFileLabel,
.chRankLabel,
.chLabelCorner {
  width: 40px; height: 16px;
  display: flex; align-items: center; justify-content: center;
  font-size: 10px; letter-spacing: 1px; color: rgba(245, 196, 81, 0.65);
}
.chRankLabel { width: 16px; height: 40px; }
.chCell {
  width: 40px; height: 40px;
  display: flex; align-items: center; justify-content: center;
  font-size: 32px; user-select: none; cursor: default;
  position: relative;
  transition: box-shadow 0.12s ease;
}
.chCell--light { background: linear-gradient(180deg, #f3dfbb 0%, #d8bf94 100%); }
.chCell--dark { background: linear-gradient(180deg, #7a5436 0%, #5a3a1f 100%); }
.chCell--tappable { cursor: pointer; }
.chCell--selected { box-shadow: inset 0 0 0 3px #f5c451; z-index: 2; }
.chCell--lastMove {
  background-image: linear-gradient(180deg, rgba(245, 196, 81, 0.35), rgba(245, 196, 81, 0.18));
}
.chCell--lastMove.chCell--dark {
  background-image: linear-gradient(180deg, rgba(245, 196, 81, 0.35), rgba(245, 196, 81, 0.12)),
    linear-gradient(180deg, #7a5436 0%, #5a3a1f 100%);
}

/* Legal-destination markers (demo only) ─────────────────────────────
   .chCell--legal         empty square — soft gold dot in the centre
   .chCell--legalCapture  enemy-occupied — red inset ring around the cell
   Both are subtle on purpose; the gold ring on the selected source
   piece is the loudest highlight on the board. */
.chCell--legal::after {
  content: '';
  position: absolute;
  width: 14px; height: 14px;
  border-radius: 50%;
  background: rgba(245, 196, 81, 0.35);
  box-shadow:
    0 0 0 1px rgba(245, 196, 81, 0.6),
    0 0 10px rgba(245, 196, 81, 0.3);
  pointer-events: none;
}
.chCell--legalCapture {
  box-shadow: inset 0 0 0 3px rgba(196, 82, 79, 0.85);
}

.chPiece {
  line-height: 1;
  filter: drop-shadow(0 2px 2px rgba(0, 0, 0, 0.55));
  position: relative; z-index: 1;
}
.chPiece--white {
  color: #fff;
  text-shadow: 0 0 1px #000, 0 1px 2px rgba(0, 0, 0, 0.55);
}
.chPiece--black {
  color: #1a1a1a;
  text-shadow: 0 0 1px #fff, 0 1px 2px rgba(0, 0, 0, 0.55);
}

/* ─── Demo panel: turn bar + captures + move history ──────────────── */
.chDemoPanel {
  margin: 0 4px 10px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.chDemoBar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 8px 14px;
  border-radius: 10px;
  background:
    linear-gradient(135deg, rgba(245, 196, 81, 0.10) 0%, rgba(245, 196, 81, 0.02) 100%);
  border: 1px solid rgba(245, 196, 81, 0.30);
}
.chDemoTurn { display: flex; align-items: center; gap: 10px; }
.chDemoTurnDot {
  width: 16px; height: 16px; border-radius: 50%;
  border: 1px solid rgba(0, 0, 0, 0.45);
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.5), inset 0 1px 0 rgba(255, 255, 255, 0.25);
}
.chDot--white { background: linear-gradient(135deg, #ffffff 0%, #d6cfbe 100%); }
.chDot--black { background: linear-gradient(135deg, #2a2a2a 0%, #050505 100%); }
.chDemoTurnLabel {
  font-size: 14px;
  letter-spacing: 2px;
  text-transform: uppercase;
  color: #fff;
  font-weight: 700;
}
.chDemoMeta {
  display: flex; align-items: baseline; gap: 6px;
  font-family: 'JetBrains Mono', ui-monospace, monospace;
}
.chDemoMetaLabel {
  font-size: 9px; letter-spacing: 2px; text-transform: uppercase;
  color: rgba(255, 255, 255, 0.55);
}
.chDemoMetaValue {
  font-size: 16px; font-weight: 700; color: #f5c451;
}

/* Captures strip — taken pieces grouped by capturer side. White
   captures black pieces (rendered dark) and vice versa. */
.chCapStrip {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.chCapSide {
  flex: 1 1 200px;
  padding: 6px 12px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.08);
}
.chCapLbl {
  font-size: 9px;
  letter-spacing: 2px;
  text-transform: uppercase;
  color: rgba(255, 255, 255, 0.55);
}
.chCapRow {
  display: flex; flex-wrap: wrap; gap: 1px;
  min-height: 26px; align-items: center; margin-top: 2px;
}
.chCapGlyph {
  font-size: 20px; line-height: 1;
  filter: drop-shadow(0 1px 1px rgba(0, 0, 0, 0.55));
}
.chCapGlyph--white {
  /* white = the colour of the piece glyph itself (taken-by-black are
     white pieces) */
  color: #fff;
  text-shadow: 0 0 1px #000;
}
.chCapGlyph--black {
  color: #1a1a1a;
  text-shadow: 0 0 1px rgba(255, 255, 255, 0.85);
}
.chCapEmpty { color: rgba(255, 255, 255, 0.3); font-size: 14px; }

/* Move history — two-column algebraic notation, scrollable. */
.chMoveList {
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.08);
  overflow: hidden;
}
.chMoveListHdr {
  padding: 6px 12px;
  font-size: 10px; letter-spacing: 2px; text-transform: uppercase;
  color: #f5c451;
  background: rgba(0, 0, 0, 0.25);
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
}
.chMoveListScroll {
  max-height: 180px;
  overflow-y: auto;
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 12px;
}
.chMoveListRow {
  display: grid;
  grid-template-columns: 40px 1fr 1fr;
  padding: 3px 12px;
  color: rgba(255, 255, 255, 0.85);
}
.chMoveListRow:nth-child(odd) { background: rgba(255, 255, 255, 0.02); }
.chMoveListRow--head {
  font-size: 9px; letter-spacing: 1.5px; text-transform: uppercase;
  color: rgba(255, 255, 255, 0.5);
  background: rgba(0, 0, 0, 0.18);
}
.chMoveN { color: rgba(255, 255, 255, 0.45); }
.chMoveCol { word-break: break-all; }

/* Demo hint row — narrower margin so it sits flush with the panel. */
.chDemoHint {
  display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
  padding: 6px 10px; border-radius: 8px;
  background: rgba(245, 196, 81, 0.08);
  border: 1px dashed rgba(245, 196, 81, 0.45);
  color: rgba(255, 255, 255, 0.85);
  font-size: 12px;
}
.chDemoHint .demoBtn[disabled] {
  opacity: 0.4; cursor: not-allowed;
}
.demoBtn--primary {
  background: linear-gradient(135deg, rgba(245, 196, 81, 0.25), rgba(245, 196, 81, 0.10));
  color: #fff;
}

/* ─── Scholar's Mate showcase: progress bar + mate banner ─────────── */
.chScholarBar {
  display: flex; align-items: center; gap: 10px;
  margin: 0 4px 8px;
  padding: 8px 14px;
  border-radius: 10px;
  background:
    linear-gradient(135deg, rgba(167, 139, 250, 0.18) 0%, rgba(167, 139, 250, 0.04) 100%);
  border: 1px solid rgba(167, 139, 250, 0.45);
  color: #fff;
  font-size: 13px;
}
.chScholarPlay {
  color: #a78bfa;
  font-size: 14px;
  animation: chScholarPulse 1.0s ease-in-out infinite;
}
@keyframes chScholarPulse {
  0%, 100% { opacity: 0.55; }
  50%      { opacity: 1; }
}
.chScholarLabel {
  flex: 1;
  letter-spacing: 1.5px;
  text-transform: uppercase;
  font-weight: 700;
}
.chScholarProgress {
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  color: rgba(245, 196, 81, 0.9);
  font-size: 12px;
}

/* Checkmate banner — gold/red trim, big serif word, pulses in. */
.chMateBanner {
  position: relative;
  display: flex; align-items: center; gap: 14px;
  margin: 0 4px 10px;
  padding: 12px 18px;
  border-radius: 12px;
  background:
    radial-gradient(ellipse at 30% 40%, rgba(245, 196, 81, 0.22) 0%, transparent 60%),
    linear-gradient(135deg, rgba(196, 82, 79, 0.18) 0%, rgba(74, 26, 28, 0.85) 100%);
  border: 1px solid rgba(245, 196, 81, 0.55);
  box-shadow:
    0 8px 22px rgba(0, 0, 0, 0.55),
    inset 0 0 0 1px rgba(255, 255, 255, 0.04);
  animation: chMateIn 0.5s ease-out;
}
@keyframes chMateIn {
  0%   { opacity: 0; transform: translateY(-6px) scale(0.98); }
  100% { opacity: 1; transform: translateY(0) scale(1); }
}
.chMateIcon {
  font-size: 36px; line-height: 1;
  color: #ffe089;
  text-shadow: 0 0 12px rgba(245, 196, 81, 0.7), 0 2px 4px rgba(0, 0, 0, 0.6);
}
.chMateLines { flex: 1; min-width: 0; }
.chMateTop {
  font-family: 'EB Garamond', serif;
  font-size: clamp(20px, 4vw, 26px);
  font-weight: 700;
  letter-spacing: 3px;
  color: #ffe089;
  text-shadow: 0 2px 4px rgba(0, 0, 0, 0.6);
}
.chMateSub {
  font-size: 11.5px;
  letter-spacing: 2px;
  text-transform: uppercase;
  color: rgba(255, 255, 255, 0.75);
  margin-top: 2px;
}
.chMateDismiss {
  position: absolute;
  top: 6px; right: 8px;
  width: 22px; height: 22px;
  background: transparent;
  border: 1px solid rgba(255, 255, 255, 0.2);
  border-radius: 50%;
  color: rgba(255, 255, 255, 0.7);
  font-size: 14px; line-height: 1;
  cursor: pointer;
  padding: 0;
}
.chMateDismiss:hover { color: #fff; border-color: rgba(255, 255, 255, 0.45); }

@media (max-width: 480px) {
  .chCell { width: 34px; height: 34px; font-size: 26px; }
  .chFileLabel, .chLabelCorner { width: 34px; }
  .chRankLabel { height: 34px; }
  .chHero { flex-direction: column; gap: 12px; }
  .chWagerHead { flex-direction: column; align-items: flex-start; gap: 4px; }
  /* Soften the tilt on small screens — at narrow widths the strong
     perspective makes the back rank crowd into the rail. */
  .chTable { transform: rotateX(16deg); }
  .chScene { padding: 32px 8px 40px; }
  .chCloth { padding: 14px 8px 10px; }
  .chTableBrand { letter-spacing: 3px; font-size: 10px; }
}

/* ─── Demo hint ─────────────────────────────────────────────────────── */
.demoHint {
  display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
  padding: 6px 10px; margin: 8px auto;
  max-width: 520px; border-radius: 8px;
  background: rgba(245, 196, 81, 0.08);
  border: 1px dashed rgba(245, 196, 81, 0.45);
  color: rgba(255, 255, 255, 0.85);
  font-size: 12px;
}
.demoHintDot { width: 8px; height: 8px; border-radius: 50%; background: #f5c451;
  box-shadow: 0 0 6px rgba(245, 196, 81, 0.8); animation: demoPulse 1.6s ease-in-out infinite; }
@keyframes demoPulse { 0%, 100% { opacity: 0.5; } 50% { opacity: 1; } }
.demoHintLabel { font-size: 10px; letter-spacing: 3px; font-weight: 700; color: #f5c451; }
.demoBtn {
  background: transparent; border: 1px solid rgba(245, 196, 81, 0.55);
  border-radius: 4px; color: #f5c451;
  font-family: 'EB Garamond', serif; font-size: 11px; letter-spacing: 1.5px;
  font-weight: 700; padding: 4px 10px; cursor: pointer;
}
.demoBtn:hover { background: rgba(245, 196, 81, 0.12); }
</style>
