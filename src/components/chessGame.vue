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

import { getContractStorage } from '../services/tzkt'
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
  },
  created() {
    this.socket.on('newWallet', (w) => {
      this.walletAddress = w
    })
    this.refresh()
    if (BLOCKCHAIN_ENABLED) {
      this.pollInterval = setInterval(() => this.refresh(), 8000)
    }
  },
  beforeUnmount() {
    if (this.pollInterval) clearInterval(this.pollInterval)
  },
  methods: {
    setView(v) {
      this.view = v
      this.selectedSq = null
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
    async createGame() {
      try {
        this.tezos.setWalletProvider(this.wallet)
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
        this.tezos.setWalletProvider(this.wallet)
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
      // ── DEMO MODE: relaxed piece movement, no rule checks ───────────
      if (!this.inRealGame) {
        if (this.selectedSq == null) {
          if (cell.piece === 0) return
          this.selectedSq = cell.idx
          return
        }
        if (cell.idx === this.selectedSq) {
          this.selectedSq = null
          return
        }
        const fromPiece = this.demoBoard[this.selectedSq]
        const next = [...this.demoBoard]
        next[this.selectedSq] = 0
        next[cell.idx] = fromPiece
        this.demoBoard = next
        this.lastMove = { from: this.selectedSq, to: cell.idx }
        this.selectedSq = null
        this.demoTurn = this.demoTurn === 1 ? 2 : 1
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
        this.tezos.setWalletProvider(this.wallet)
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
        this.tezos.setWalletProvider(this.wallet)
        const contract = await this.tezos.wallet.at(CHESS_CONTRACT_ADDRESS)
        const op = await contract.methodsObject
          .giveup({ gameId: this.activeGameId }).send()
        await op.confirmation()
        await this.refresh()
      } catch (err) { console.error('giveup failed:', err) }
    },
    async claimCheckmate() {
      try {
        this.tezos.setWalletProvider(this.wallet)
        const contract = await this.tezos.wallet.at(CHESS_CONTRACT_ADDRESS)
        const op = await contract.methodsObject
          .claim_checkmate({ gameId: this.activeGameId }).send()
        await op.confirmation()
        await this.refresh()
      } catch (err) { console.error('claim checkmate failed:', err) }
    },
    async offerDraw() {
      try {
        this.tezos.setWalletProvider(this.wallet)
        const contract = await this.tezos.wallet.at(CHESS_CONTRACT_ADDRESS)
        const op = await contract.methodsObject
          .offer_draw({ gameId: this.activeGameId }).send()
        await op.confirmation()
        await this.refresh()
      } catch (err) { console.error('offerDraw failed:', err) }
    },
    async denyDraw() {
      try {
        this.tezos.setWalletProvider(this.wallet)
        const contract = await this.tezos.wallet.at(CHESS_CONTRACT_ADDRESS)
        const op = await contract.methodsObject
          .deny_draw({ gameId: this.activeGameId }).send()
        await op.confirmation()
        await this.refresh()
      } catch (err) { console.error('denyDraw failed:', err) }
    },
    async claimStalemate() {
      try {
        this.tezos.setWalletProvider(this.wallet)
        const contract = await this.tezos.wallet.at(CHESS_CONTRACT_ADDRESS)
        const op = await contract.methodsObject
          .claim_stalemate({ gameId: this.activeGameId }).send()
        await op.confirmation()
        await this.refresh()
      } catch (err) { console.error('claim stalemate failed:', err) }
    },
    async claimByTimeout() {
      try {
        this.tezos.setWalletProvider(this.wallet)
        const contract = await this.tezos.wallet.at(CHESS_CONTRACT_ADDRESS)
        const op = await contract.methodsObject
          .claimByTimeout({ gameId: this.activeGameId }).send()
        await op.confirmation()
        await this.refresh()
      } catch (err) { console.error('claimByTimeout failed:', err) }
    },
    async cancelGame() {
      try {
        this.tezos.setWalletProvider(this.wallet)
        const contract = await this.tezos.wallet.at(CHESS_CONTRACT_ADDRESS)
        const op = await contract.methodsObject
          .cancelGame({ gameId: this.activeGameId }).send()
        await op.confirmation()
        await this.refresh()
      } catch (err) { console.error('cancelGame failed:', err) }
    },
    resetDemo() {
      this.demoBoard = openingBoard()
      this.demoTurn = 1
      this.lastMove = null
      this.selectedSq = null
    },
  },
}
</script>

<template>
  <div class="gameManagement chRoot">
    <!-- ───── Landing view ────────────────────────────────────────────── -->
    <template v-if="view === 'landing'">
      <div class="chHero">
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
        <div class="chHeroBoard" aria-hidden="true">
          <svg viewBox="0 0 120 120" class="chHeroSvg">
            <rect x="2" y="2" width="116" height="116" rx="6" fill="#3e2914"/>
            <g>
              <g v-for="(_, r) in 8" :key="'rr-' + r">
                <rect
                  v-for="(__, c) in 8"
                  :key="'rc-' + r + '-' + c"
                  :x="10 + c * 12.5"
                  :y="10 + r * 12.5"
                  width="12.5" height="12.5"
                  :fill="(r + c) % 2 === 0 ? '#d8bf94' : '#7a5436'"
                />
              </g>
            </g>
            <text x="22" y="105" font-family="serif" font-size="12" fill="#fff" text-anchor="middle">♙</text>
            <text x="97" y="22" font-family="serif" font-size="12" fill="#1a1a1a" text-anchor="middle">♛</text>
          </svg>
        </div>
      </div>

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

      <div class="chBoardWrap">
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

      <div v-if="!inRealGame" class="demoHint">
        <span class="demoHintDot"></span>
        <span class="demoHintLabel">DEMO</span>
        <span class="demoHintBody">Click a piece then a destination. No legality checks — try anything.</span>
        <button class="demoBtn" @click="resetDemo">Reset board</button>
      </div>

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

/* ─── Board ─────────────────────────────────────────────────────────── */
.chBoardWrap { display: flex; justify-content: center; margin: 8px 0 12px; }
.chBoard {
  display: inline-block;
  padding: 8px;
  border-radius: 10px;
  background: linear-gradient(135deg, #5a3a1f 0%, #2e1d0f 100%);
  box-shadow:
    inset 0 0 0 1px rgba(0, 0, 0, 0.45),
    0 8px 22px rgba(0, 0, 0, 0.45);
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
  font-size: 28px; user-select: none; cursor: default;
  position: relative;
}
.chCell--light { background: linear-gradient(180deg, #f3dfbb 0%, #d8bf94 100%); }
.chCell--dark { background: linear-gradient(180deg, #7a5436 0%, #5a3a1f 100%); }
.chCell--tappable { cursor: pointer; }
.chCell--selected { box-shadow: inset 0 0 0 3px #f5c451; }
.chCell--lastMove {
  background-image: linear-gradient(180deg, rgba(245, 196, 81, 0.35), rgba(245, 196, 81, 0.18));
}
.chCell--lastMove.chCell--dark {
  background-image: linear-gradient(180deg, rgba(245, 196, 81, 0.35), rgba(245, 196, 81, 0.12)),
    linear-gradient(180deg, #7a5436 0%, #5a3a1f 100%);
}
.chPiece {
  line-height: 1;
  text-shadow: 0 1px 1px rgba(0, 0, 0, 0.55);
}
.chPiece--white {
  color: #fff;
  text-shadow: 0 0 1px #000, 0 1px 2px rgba(0, 0, 0, 0.55);
}
.chPiece--black {
  color: #1a1a1a;
  text-shadow: 0 0 1px #fff, 0 1px 2px rgba(0, 0, 0, 0.55);
}

@media (max-width: 480px) {
  .chCell { width: 34px; height: 34px; font-size: 24px; }
  .chFileLabel, .chLabelCorner { width: 34px; }
  .chRankLabel { height: 34px; }
  .chHero { flex-direction: column; gap: 12px; }
  .chWagerHead { flex-direction: column; align-items: flex-start; gap: 4px; }
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
