<script>
// Chess H2H — UI mirrors the contract. Pure skill, on-chain validation.
//
// Two-mode component (lobby/landing + play view). Board ALWAYS renders, with
// the standard opening position when no contract game is active so users can
// browse, learn, and try moves in demo mode before staking.

import { getContractStorage } from '../services/tzkt'
import {
  BLOCKCHAIN_ENABLED,
  CHESS_CONTRACT_ADDRESS,
  CHESS_GAME_INFO,
} from '../constants'

// Piece codes (must match contract): 0 empty, 1-6 white P/N/B/R/Q/K, 7-12 black p/n/b/r/q/k.
const GLYPH = {
  0: '',
  1: '♙', 2: '♘', 3: '♗', 4: '♖', 5: '♕', 6: '♔', // ♙♘♗♖♕♔ white
  7: '♟', 8: '♞', 9: '♝', 10: '♜', 11: '♛', 12: '♚', // ♟♞♝♜♛♚ black
}
const FILES = ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h']

// Standard chess starting position, ranks 0..7 with white at rank 0.
function openingBoard() {
  const b = new Array(64).fill(0)
  // Rank 0: white back row
  b[0] = 4; b[1] = 2; b[2] = 3; b[3] = 5; b[4] = 6; b[5] = 3; b[6] = 2; b[7] = 4
  // Rank 1: white pawns
  for (let c = 0; c < 8; c++) b[8 + c] = 1
  // Rank 6: black pawns
  for (let c = 0; c < 8; c++) b[48 + c] = 7
  // Rank 7: black back row
  b[56] = 10; b[57] = 8; b[58] = 9; b[59] = 11; b[60] = 12; b[61] = 9; b[62] = 8; b[63] = 10
  return b
}

const PHASE_LABELS = {
  0: 'Open — waiting for opponent',
  1: 'In play',
  2: 'White wins',
  3: 'Black wins',
  4: 'Draw',
}
const PHASE_TONES = {
  0: 'phaseOpen',
  1: 'phaseLive',
  2: 'phaseDone',
  3: 'phaseDone',
  4: 'phaseDone',
}

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
      stakeMutez: 1_000_000,
      selectedSq: null,
      pollInterval: null,
      blockchainStatus: 'idle',
      view: 'landing',
      showRules: false,
      demoBoard: openingBoard(),
      demoTurn: 1, // 1=white, 2=black
      lastMove: null, // { from, to }
    }
  },
  computed: {
    game() {
      return this.activeGameId == null ? null : this.games[this.activeGameId]
    },
    inRealGame() {
      return !!this.game && Number(this.game.phase) === 1
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
          const code = Number(this.displayBoard?.[idx] ?? 0)
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
        .filter(([, g]) => Number(g.phase) === 0)
        .map(([id, g]) => ({ id: Number(id), ...g }))
    },
    myColor() {
      if (!this.game || !this.walletAddress) return 0
      const me = this.walletAddress.slice(-4)
      if (this.game.white?.endsWith(me)) return 1
      if (this.game.black?.endsWith(me)) return 2
      return 0
    },
    myTurn() {
      if (!this.inRealGame) return true // demo mode: always your turn
      return Number(this.game.turn) === this.myColor
    },
    phaseLabel() {
      if (!this.game) return 'Demo board'
      const phase = Number(this.game.phase)
      if (phase === 1) {
        return `In play · ${Number(this.game.turn) === 1 ? 'White' : 'Black'} to move`
      }
      return PHASE_LABELS[phase] || `phase ${phase}`
    },
    phaseTone() {
      if (!this.game) return 'phaseNone'
      return PHASE_TONES[Number(this.game.phase)] || 'phaseNone'
    },
    turnLabel() {
      if (!this.game) return this.demoTurn === 1 ? 'White' : 'Black'
      if (Number(this.game.phase) !== 1) return '—'
      return Number(this.game.turn) === 1 ? 'White' : 'Black'
    },
    myColorLabel() {
      if (!this.inRealGame) return '—'
      if (this.myColor === 1) return 'White'
      if (this.myColor === 2) return 'Black'
      return 'Spectating'
    },
    stakeTez() {
      if (!this.game) return (this.stakeMutez / 1_000_000).toFixed(3)
      return (Number(this.game.stake) / 1_000_000).toFixed(3)
    },
    potTez() {
      if (!this.game) return '—'
      return ((Number(this.game.stake) * 2) / 1_000_000).toFixed(3)
    },
    drawOfferedByOpponent() {
      if (!this.game) return false
      const offered = Number(this.game.drawOfferedBy)
      return offered !== 0 && offered !== this.myColor
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
    async refresh() {
      try {
        const storage = await getContractStorage(CHESS_CONTRACT_ADDRESS)
        if (!storage) return
        this.currentGameId = Number(storage.currentGameId || 0)
        this.games = storage.games || {}
        if (this.activeGameId == null && this.currentGameId > 0) {
          this.activeGameId = this.currentGameId - 1
        }
      } catch (e) {
        console.warn('chess refresh failed:', e?.message)
      }
    },
    async createGame() {
      try {
        this.tezos.setWalletProvider(this.wallet)
        this.blockchainStatus = 'creating chess game...'
        const total = this.stakeMutez + 50000
        const contract = await this.tezos.wallet.at(CHESS_CONTRACT_ADDRESS)
        const op = await contract.methodsObject
          .createGame({ stake: this.stakeMutez })
          .send({ amount: total / 1_000_000 })
        await op.confirmation()
        this.blockchainStatus = 'created.'
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
        const total = Number(g.stake) + 50000
        const contract = await this.tezos.wallet.at(CHESS_CONTRACT_ADDRESS)
        const op = await contract.methodsObject.joinGame({ gameId }).send({ amount: total / 1_000_000 })
        await op.confirmation()
        this.activeGameId = gameId
        this.view = 'play'
        await this.refresh()
      } catch (err) {
        console.error('chess join failed:', err)
      }
    },
    clickSq(cell) {
      // ── DEMO MODE: relaxed piece movement, no rule checks ───────────
      if (!this.inRealGame) {
        if (this.selectedSq == null) {
          // Must click a piece (not an empty square) to begin a move.
          if (cell.piece === 0) return
          this.selectedSq = cell.idx
          return
        }
        if (cell.idx === this.selectedSq) {
          this.selectedSq = null
          return
        }
        // Move the piece. No legality checks in demo mode.
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
        const contract = await this.tezos.wallet.at(CHESS_CONTRACT_ADDRESS)
        const op = await contract.methodsObject.makeMove({ gameId: this.activeGameId, fromSq, toSq }).send()
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
    async resign() {
      try {
        this.tezos.setWalletProvider(this.wallet)
        const contract = await this.tezos.wallet.at(CHESS_CONTRACT_ADDRESS)
        const op = await contract.methodsObject.resign({ gameId: this.activeGameId }).send()
        await op.confirmation()
        await this.refresh()
      } catch (err) { console.error('resign failed:', err) }
    },
    async offerDraw() {
      try {
        this.tezos.setWalletProvider(this.wallet)
        const contract = await this.tezos.wallet.at(CHESS_CONTRACT_ADDRESS)
        const op = await contract.methodsObject.offerDraw({ gameId: this.activeGameId }).send()
        await op.confirmation()
        await this.refresh()
      } catch (err) { console.error('offerDraw failed:', err) }
    },
    async acceptDraw() {
      try {
        this.tezos.setWalletProvider(this.wallet)
        const contract = await this.tezos.wallet.at(CHESS_CONTRACT_ADDRESS)
        const op = await contract.methodsObject.acceptDraw({ gameId: this.activeGameId }).send()
        await op.confirmation()
        await this.refresh()
      } catch (err) { console.error('acceptDraw failed:', err) }
    },
    async claimByTimeout() {
      try {
        this.tezos.setWalletProvider(this.wallet)
        const contract = await this.tezos.wallet.at(CHESS_CONTRACT_ADDRESS)
        const op = await contract.methodsObject.claimByTimeout({ gameId: this.activeGameId }).send()
        await op.confirmation()
        await this.refresh()
      } catch (err) { console.error('claimByTimeout failed:', err) }
    },
    async claim() {
      try {
        this.tezos.setWalletProvider(this.wallet)
        const contract = await this.tezos.wallet.at(CHESS_CONTRACT_ADDRESS)
        const op = await contract.methodsObject.claim().send()
        await op.confirmation()
        this.blockchainStatus = 'claimed.'
      } catch (err) { console.error('chess claim failed:', err) }
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
          <div class="chHeroEyebrow">CHESS · H2H · ON-CHAIN</div>
          <div class="chHeroTitle">Standard chess. Every move validated.</div>
          <div class="chHeroSub">
            White moves first. Pawns auto-promote to queens. Castling, en passant,
            and path-clear rules are enforced by the contract. Resign, offer a
            draw, or claim by timeout if your opponent stalls. Winner takes the
            pot minus the holder fee.
          </div>
        </div>
        <div class="chHeroBoard" aria-hidden="true">
          <svg viewBox="0 0 120 120" class="chHeroSvg">
            <rect x="2" y="2" width="116" height="116" rx="6" fill="#3e2914"/>
            <g>
              <!-- 8x8 mini board -->
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
            <!-- A couple of pieces for character -->
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
          <div class="chPillLabel">Stake</div>
          <div class="chPillValue">{{ stakeTez }} ꜩ</div>
          <div class="chPillFootnote">+ 0.05 ꜩ fee</div>
        </div>
        <div class="chPill">
          <div class="chPillLabel">Pot</div>
          <div class="chPillValue">{{ potTez }} ꜩ</div>
        </div>
        <div class="chPill">
          <div class="chPillLabel">Your side</div>
          <div class="chPillValue">{{ myColorLabel }}</div>
        </div>
      </div>

      <div class="rowFlex chPrimaryRow">
        <div class="actionButton chPrimary" @click="setView('play')">Open board</div>
        <div class="actionButton" @click="createGame">New game ({{ (stakeMutez / 1000000).toFixed(2) }} ꜩ)</div>
        <div class="actionButton" @click="claim">Claim winnings</div>
        <div class="actionButtonHelp" @click="toggleRules">{{ showRules ? 'Hide rules' : 'How it works' }}</div>
      </div>

      <div v-if="openGames.length" class="rowFlex">
        <div class="gameInfo chOpenLabel">Open challenges:</div>
        <div
          v-for="g in openGames"
          :key="g.id"
          class="actionButton"
          @click="joinGame(g.id)"
        >Join #{{ g.id }} — {{ (Number(g.stake) / 1000000).toFixed(2) }} ꜩ</div>
      </div>

      <div v-if="showRules" class="chRules">
        <ol>
          <li v-for="(line, i) in info" :key="i">{{ line }}</li>
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
        <div class="txlRank">Pot: {{ potTez }} ꜩ</div>
      </div>

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

      <div v-if="inRealGame" class="rowFlex">
        <div class="actionButtonHelp" @click="offerDraw">Offer draw</div>
        <div v-if="drawOfferedByOpponent" class="actionButton" @click="acceptDraw">Accept draw</div>
        <div class="actionButtonHelp" @click="resign">Resign</div>
        <div class="actionButtonHelp" @click="claimByTimeout">Claim timeout</div>
      </div>

      <div class="rowFlex">
        <div class="actionButton" @click="createGame">New game</div>
        <div class="actionButton" @click="claim">Claim</div>
        <div class="actionButton" @click="setView('landing')">Back to lobby</div>
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

.chRules { margin: 8px 4px 12px; padding: 12px 16px; border-radius: 8px;
  background: rgba(255, 255, 255, 0.03); border: 1px solid rgba(255, 255, 255, 0.08); }
.chRules ol { margin: 0; padding-left: 20px; font-size: 13px; line-height: 1.55; color: rgba(255,255,255,0.85); }

.chStatusLine { font-size: 12px; color: #d4a24e; font-style: italic; }

/* ─── Play header ───────────────────────────────────────────────────── */
.chPlayHeader { margin: 4px 0 8px; }
.chBackBtn { flex: 0 0 auto; min-width: 90px; }

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
