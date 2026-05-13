<script>
// Reversi (Othello) — H2H wagered.
//
// Two-mode component:
//   • view = 'landing' — hero + status pills + rules (default when first opened)
//   • view = 'play'    — the felt board + open games list + actions
//
// The board ALWAYS renders, even before a contract game has loaded — when no
// game is in progress we run a local "demo board" with the standard 4-stone
// opening so the player can see how the visuals look and place stones freely.
// When `gamePlayable` becomes true (joined contract game), the contract state
// takes over and the demo board is hidden.

import { getContractStorage } from '../services/tzkt'
import {
  BLOCKCHAIN_ENABLED,
  REVERSI_CONTRACT_ADDRESS,
  REVERSI_GAME_INFO,
} from '../constants'

const PHASE_LABELS = {
  0: 'Open — waiting for opponent',
  1: 'In play',
  2: 'Game complete',
}
const PHASE_TONES = {
  0: 'phaseOpen',
  1: 'phaseLive',
  2: 'phaseDone',
}
const FILES = ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h']

// Standard Othello opening: white at (3,3) & (4,4), black at (3,4) & (4,3).
// We encode stones as 1 = black, 2 = white, 0 = empty.
function openingBoard() {
  const b = new Array(64).fill(0)
  b[3 * 8 + 3] = 2
  b[4 * 8 + 4] = 2
  b[3 * 8 + 4] = 1
  b[4 * 8 + 3] = 1
  return b
}

export default {
  name: 'reversiGame',
  props: ['socket', 'wallet', 'tezos'],
  data() {
    return {
      info: REVERSI_GAME_INFO,
      walletAddress: '',
      currentGameId: 0,
      activeGameId: null,
      games: {},
      stakeMutez: 1_000_000, // 1 ꜩ default new-game stake
      pollInterval: null,
      blockchainStatus: 'idle',
      view: 'landing',
      showRules: false,
      // Demo state — used when no contract game is loaded.
      demoBoard: openingBoard(),
      demoTurn: 1, // 1=black, 2=white (Othello convention)
      lastMoveIdx: null,
    }
  },
  computed: {
    game() {
      return this.activeGameId == null ? null : this.games[this.activeGameId]
    },
    // True when we're playing a real contract game (board comes from chain).
    inRealGame() {
      return !!this.game && Number(this.game.phase) === 1
    },
    // What we actually render on the board — contract state if a real game is
    // active, otherwise the local demo board.
    displayBoard() {
      if (this.game?.board) return this.game.board
      return this.demoBoard
    },
    boardCells() {
      const out = []
      for (let r = 0; r < 8; r++) {
        const row = []
        for (let c = 0; c < 8; c++) {
          const idx = r * 8 + c
          const stone = Number(this.displayBoard?.[idx] ?? 0)
          row.push({ r, c, idx, stone })
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
    myTurn() {
      if (!this.inRealGame) return false
      const turn = Number(this.game.turn)
      const me = (turn === 1 ? this.game.player1 : this.game.player2) || ''
      return this.walletAddress.endsWith(me.slice(-4))
    },
    phaseLabel() {
      if (!this.game) return 'Demo board'
      return PHASE_LABELS[Number(this.game.phase)] || `phase ${this.game.phase}`
    },
    phaseTone() {
      if (!this.game) return 'phaseNone'
      return PHASE_TONES[Number(this.game.phase)] || 'phaseNone'
    },
    score() {
      // Count stones on the current board for either source.
      let black = 0
      let white = 0
      for (let i = 0; i < 64; i++) {
        const v = Number(this.displayBoard?.[i] ?? 0)
        if (v === 1) black++
        else if (v === 2) white++
      }
      return { black, white }
    },
    potTez() {
      if (!this.game) return '—'
      // Both players paid stake; pot = 2 × stake.
      const lamports = Number(this.game.stake) * 2
      return (lamports / 1_000_000).toFixed(3)
    },
    stakeTez() {
      if (!this.game) return (this.stakeMutez / 1_000_000).toFixed(3)
      return (Number(this.game.stake) / 1_000_000).toFixed(3)
    },
    turnLabel() {
      if (!this.game) return this.demoTurn === 1 ? 'Black' : 'White'
      if (Number(this.game.phase) !== 1) return '—'
      return Number(this.game.turn) === 1 ? 'Black' : 'White'
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
    },
    toggleRules() {
      this.showRules = !this.showRules
    },
    async refresh() {
      try {
        const storage = await getContractStorage(REVERSI_CONTRACT_ADDRESS)
        if (!storage) return
        this.currentGameId = Number(storage.currentGameId || 0)
        this.games = storage.games || {}
        if (this.activeGameId == null && this.currentGameId > 0) {
          this.activeGameId = this.currentGameId - 1
        }
      } catch (e) {
        console.warn('reversi storage refresh failed:', e?.message)
      }
    },
    async createGame() {
      const total = this.stakeMutez + 50000
      try {
        this.tezos.setWalletProvider(this.wallet)
        this.blockchainStatus = 'creating game...'
        const contract = await this.tezos.wallet.at(REVERSI_CONTRACT_ADDRESS)
        const op = await contract.methodsObject
          .createGame({ stake: this.stakeMutez })
          .send({ amount: total / 1_000_000 })
        await op.confirmation()
        this.blockchainStatus = 'game created.'
        await this.refresh()
      } catch (err) {
        console.error('createGame failed:', err)
        this.blockchainStatus = 'create failed'
      }
    },
    async joinGame(gameId) {
      try {
        this.tezos.setWalletProvider(this.wallet)
        this.blockchainStatus = `joining game ${gameId}...`
        const g = this.games[gameId]
        const total = Number(g.stake) + 50000
        const contract = await this.tezos.wallet.at(REVERSI_CONTRACT_ADDRESS)
        const op = await contract.methodsObject.joinGame({ gameId }).send({ amount: total / 1_000_000 })
        await op.confirmation()
        this.activeGameId = gameId
        this.blockchainStatus = 'joined.'
        this.view = 'play'
        await this.refresh()
      } catch (err) {
        console.error('joinGame failed:', err)
        this.blockchainStatus = 'join failed'
      }
    },
    async clickCell(cell) {
      // Demo mode (no real game): cycle stone empty → black → white → empty.
      if (!this.inRealGame) {
        const cur = this.demoBoard[cell.idx]
        let next
        if (cur === 0) next = this.demoTurn
        else if (cur === 1) next = 2
        else next = 0
        this.demoBoard = this.demoBoard.map((v, i) => (i === cell.idx ? next : v))
        if (next !== 0) this.demoTurn = next === 1 ? 2 : 1
        this.lastMoveIdx = next !== 0 ? cell.idx : null
        return
      }
      // Real game: only your turn, empty cells.
      if (!this.myTurn) return
      if (cell.stone !== 0) return
      try {
        this.tezos.setWalletProvider(this.wallet)
        this.blockchainStatus = `moving (${cell.r},${cell.c})...`
        const contract = await this.tezos.wallet.at(REVERSI_CONTRACT_ADDRESS)
        const op = await contract.methodsObject
          .makeMove({ gameId: this.activeGameId, row: cell.r, col: cell.c })
          .send()
        await op.confirmation()
        this.lastMoveIdx = cell.idx
        this.blockchainStatus = `placed at (${cell.r},${cell.c}).`
        await this.refresh()
      } catch (err) {
        console.error('makeMove failed:', err)
        this.blockchainStatus = 'illegal or failed'
      }
    },
    async passTurn() {
      try {
        this.tezos.setWalletProvider(this.wallet)
        this.blockchainStatus = 'passing turn...'
        const contract = await this.tezos.wallet.at(REVERSI_CONTRACT_ADDRESS)
        const op = await contract.methodsObject.passTurn({ gameId: this.activeGameId }).send()
        await op.confirmation()
        this.blockchainStatus = 'passed.'
        await this.refresh()
      } catch (err) {
        console.error('passTurn failed:', err)
        this.blockchainStatus = 'pass failed'
      }
    },
    async claim() {
      try {
        this.tezos.setWalletProvider(this.wallet)
        this.blockchainStatus = 'claiming...'
        const contract = await this.tezos.wallet.at(REVERSI_CONTRACT_ADDRESS)
        const op = await contract.methodsObject.claim().send()
        await op.confirmation()
        this.blockchainStatus = 'claimed.'
      } catch (err) {
        console.error('claim failed:', err)
        this.blockchainStatus = 'no winnings'
      }
    },
    resetDemo() {
      this.demoBoard = openingBoard()
      this.demoTurn = 1
      this.lastMoveIdx = null
    },
  },
}
</script>

<template>
  <div class="gameManagement rvRoot">
    <!-- ───── Landing view ────────────────────────────────────────────── -->
    <template v-if="view === 'landing'">
      <div class="rvHero">
        <div class="rvHeroBrand">
          <div class="rvHeroEyebrow">REVERSI · 8 × 8</div>
          <div class="rvHeroTitle">Outflank. Flip. Win.</div>
          <div class="rvHeroSub">
            Place a stone so that one or more of your opponent's stones lies
            between yours in any direction. Every flanked stone flips. Most
            stones when the board fills (or both pass) takes the pot.
          </div>
        </div>
        <div class="rvHeroBoard" aria-hidden="true">
          <svg viewBox="0 0 120 120" class="rvHeroSvg">
            <rect x="2" y="2" width="116" height="116" rx="6" fill="#2a1a10"/>
            <rect x="8" y="8" width="104" height="104" rx="3" fill="#0e3b22"/>
            <g stroke="rgba(0,0,0,0.35)" stroke-width="0.5">
              <line x1="21" y1="8" x2="21" y2="112"/>
              <line x1="34" y1="8" x2="34" y2="112"/>
              <line x1="47" y1="8" x2="47" y2="112"/>
              <line x1="60" y1="8" x2="60" y2="112"/>
              <line x1="73" y1="8" x2="73" y2="112"/>
              <line x1="86" y1="8" x2="86" y2="112"/>
              <line x1="99" y1="8" x2="99" y2="112"/>
              <line x1="8" y1="21" x2="112" y2="21"/>
              <line x1="8" y1="34" x2="112" y2="34"/>
              <line x1="8" y1="47" x2="112" y2="47"/>
              <line x1="8" y1="60" x2="112" y2="60"/>
              <line x1="8" y1="73" x2="112" y2="73"/>
              <line x1="8" y1="86" x2="112" y2="86"/>
              <line x1="8" y1="99" x2="112" y2="99"/>
            </g>
            <defs>
              <radialGradient id="hWhite" cx="35%" cy="30%" r="70%">
                <stop offset="0%" stop-color="#fff"/>
                <stop offset="100%" stop-color="#c9c5be"/>
              </radialGradient>
              <radialGradient id="hBlack" cx="35%" cy="30%" r="70%">
                <stop offset="0%" stop-color="#3a3a3a"/>
                <stop offset="100%" stop-color="#0a0a0a"/>
              </radialGradient>
            </defs>
            <circle cx="53" cy="53" r="5" fill="url(#hWhite)"/>
            <circle cx="66" cy="66" r="5" fill="url(#hWhite)"/>
            <circle cx="53" cy="66" r="5" fill="url(#hBlack)"/>
            <circle cx="66" cy="53" r="5" fill="url(#hBlack)"/>
          </svg>
        </div>
      </div>

      <div class="rvStatusRow">
        <div :class="['rvPill', phaseTone]">
          <div class="rvPillLabel">Phase</div>
          <div class="rvPillValue">{{ phaseLabel }}</div>
        </div>
        <div class="rvPill">
          <div class="rvPillLabel">Game</div>
          <div class="rvPillValue">{{ activeGameId == null ? '—' : '#' + activeGameId }}</div>
        </div>
        <div class="rvPill">
          <div class="rvPillLabel">Stake</div>
          <div class="rvPillValue">{{ stakeTez }} ꜩ</div>
          <div class="rvPillFootnote">+ 0.05 ꜩ fee</div>
        </div>
        <div class="rvPill">
          <div class="rvPillLabel">Pot</div>
          <div class="rvPillValue">{{ potTez }} ꜩ</div>
        </div>
        <div class="rvPill">
          <div class="rvPillLabel">Turn</div>
          <div class="rvPillValue">{{ turnLabel }}</div>
        </div>
      </div>

      <div class="rowFlex rvPrimaryRow">
        <div class="actionButton rvPrimary" @click="setView('play')">Open board</div>
        <div class="actionButton" @click="createGame">New game ({{ (stakeMutez / 1000000).toFixed(2) }} ꜩ)</div>
        <div class="actionButton" @click="claim">Claim winnings</div>
        <div class="actionButtonHelp" @click="toggleRules">{{ showRules ? 'Hide rules' : 'How it works' }}</div>
      </div>

      <div v-if="openGames.length" class="rowFlex">
        <div class="gameInfo rvOpenLabel">Open challenges:</div>
        <div
          v-for="g in openGames"
          :key="g.id"
          class="actionButton"
          @click="joinGame(g.id)"
        >Join #{{ g.id }} — {{ (Number(g.stake) / 1000000).toFixed(2) }} ꜩ</div>
      </div>

      <div v-if="showRules" class="rvRules">
        <ol>
          <li v-for="(line, i) in info" :key="i">{{ line }}</li>
        </ol>
      </div>

      <div class="gameInfo rvStatusLine">{{ blockchainStatus }}</div>
    </template>

    <!-- ───── Play view ───────────────────────────────────────────────── -->
    <template v-else>
      <div class="rowFlex rvPlayHeader">
        <div class="actionButton rvBackBtn" @click="setView('landing')">‹ Lobby</div>
        <div class="gameInfo">
          {{ game ? 'Game #' + activeGameId + ' · ' + phaseLabel : 'Demo board' }}
        </div>
        <div class="actionButton" @click="refresh">Refresh</div>
      </div>

      <div class="rowFlex">
        <div class="txlRank">
          <span class="rvScoreSwatch rvScoreSwatch--black"></span>
          {{ score.black }}
        </div>
        <div class="txlRank">
          <span class="rvScoreSwatch rvScoreSwatch--white"></span>
          {{ score.white }}
        </div>
        <div class="txlRank">Turn: <strong>{{ turnLabel }}</strong></div>
        <div class="txlRank">Pot: {{ potTez }} ꜩ</div>
      </div>

      <div class="rvBoardWrap">
        <div class="rvBoard">
          <!-- Top file labels -->
          <div class="rvFileRow">
            <div class="rvLabelCorner"></div>
            <div v-for="f in FILES" :key="'top-' + f" class="rvFileLabel">{{ f }}</div>
            <div class="rvLabelCorner"></div>
          </div>
          <div
            v-for="(row, r) in boardCells"
            :key="r"
            class="rvBoardRow"
          >
            <div class="rvRankLabel">{{ 8 - r }}</div>
            <div
              v-for="cell in row"
              :key="cell.idx"
              :class="[
                'rvCell',
                (inRealGame && myTurn && cell.stone === 0) || !inRealGame ? 'rvCell--playable' : '',
                lastMoveIdx === cell.idx ? 'rvCell--last' : '',
              ]"
              @click="clickCell(cell)"
            >
              <div
                v-if="cell.stone === 1"
                class="rvStone rvStone--black"
                :class="lastMoveIdx === cell.idx ? 'rvStone--justPlayed' : ''"
              ></div>
              <div
                v-else-if="cell.stone === 2"
                class="rvStone rvStone--white"
                :class="lastMoveIdx === cell.idx ? 'rvStone--justPlayed' : ''"
              ></div>
            </div>
            <div class="rvRankLabel">{{ 8 - r }}</div>
          </div>
          <div class="rvFileRow">
            <div class="rvLabelCorner"></div>
            <div v-for="f in FILES" :key="'bot-' + f" class="rvFileLabel">{{ f }}</div>
            <div class="rvLabelCorner"></div>
          </div>
        </div>
      </div>

      <!-- Demo hint when not in a real game -->
      <div v-if="!inRealGame" class="demoHint">
        <span class="demoHintDot"></span>
        <span class="demoHintLabel">DEMO</span>
        <span class="demoHintBody">Click any cell to cycle empty / black / white. Try out positions before staking.</span>
        <button class="demoBtn" @click="resetDemo">Reset board</button>
      </div>

      <div v-if="myTurn" class="rowFlex">
        <div class="actionButtonHelp" @click="passTurn">Pass turn (no legal moves)</div>
      </div>

      <div class="rowFlex">
        <div class="actionButton" @click="createGame">New game</div>
        <div class="actionButton" @click="claim">Claim</div>
        <div class="actionButton" @click="setView('landing')">Back to lobby</div>
      </div>

      <div class="gameInfo rvStatusLine">{{ blockchainStatus }}</div>
    </template>
  </div>
</template>

<style scoped>
.rvRoot { font-family: 'EB Garamond', serif; color: #efeae2; }

/* ─── Hero ─────────────────────────────────────────────────────────── */
.rvHero {
  display: flex;
  flex-direction: row;
  gap: 18px;
  padding: 16px 14px;
  margin: 8px 4px 14px;
  border-radius: 14px;
  background:
    radial-gradient(ellipse at 80% 20%, rgba(212, 162, 78, 0.15) 0%, transparent 60%),
    linear-gradient(135deg, #1a1410 0%, #07050a 100%);
  box-shadow:
    inset 0 0 0 1px rgba(255, 255, 255, 0.06),
    0 8px 22px rgba(0, 0, 0, 0.45);
}
.rvHeroBrand { flex: 1.4; min-width: 0; }
.rvHeroBoard { flex: 1; display: flex; align-items: center; justify-content: center; }
.rvHeroSvg { width: 100%; max-width: 180px; }
.rvHeroEyebrow {
  font-size: 10px; letter-spacing: 4px; font-weight: 700;
  color: rgba(245, 196, 81, 0.75); margin-bottom: 6px;
}
.rvHeroTitle {
  font-size: clamp(20px, 4.5vw, 30px); line-height: 1.1;
  font-weight: 700; color: #fff; margin-bottom: 8px;
}
.rvHeroSub { font-size: 13px; line-height: 1.4; color: rgba(255, 255, 255, 0.78); }

/* ─── Status pills (shared style with squaresGame) ──────────────────── */
.rvStatusRow { display: flex; flex-wrap: wrap; gap: 6px; margin: 0 4px 12px; }
.rvPill {
  flex: 1 1 110px; min-width: 110px; padding: 8px 10px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.08);
}
.rvPillLabel {
  font-size: 9px; letter-spacing: 2px; text-transform: uppercase;
  color: rgba(255, 255, 255, 0.55);
}
.rvPillValue { font-size: 16px; font-weight: 700; color: #fff; margin-top: 2px; }
.rvPillFootnote { font-size: 10px; color: rgba(255, 255, 255, 0.55); margin-top: 2px; }
.phaseOpen { border-color: rgba(118, 196, 138, 0.5); }
.phaseLive { border-color: rgba(245, 196, 81, 0.6); }
.phaseDone { border-color: rgba(196, 82, 79, 0.5); }
.phaseNone { border-color: rgba(255, 255, 255, 0.08); }

.rvPrimaryRow { margin-top: 4px; }
.rvPrimary {
  background: linear-gradient(135deg, #1f5c3a 0%, #0e3b22 100%);
  border-color: #f5c451;
  font-weight: 700;
  letter-spacing: 1px;
  text-transform: uppercase;
}
.rvOpenLabel { flex: 0 0 auto; align-self: center; font-size: 12px; }

.rvRules {
  margin: 8px 4px 12px; padding: 12px 16px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.08);
}
.rvRules ol { margin: 0; padding-left: 20px; font-size: 13px; line-height: 1.55; color: rgba(255, 255, 255, 0.85); }

.rvStatusLine { font-size: 12px; color: #d4a24e; font-style: italic; }

/* ─── Play view ─────────────────────────────────────────────────────── */
.rvPlayHeader { margin: 4px 0 8px; }
.rvBackBtn { flex: 0 0 auto; min-width: 90px; }

.rvScoreSwatch {
  display: inline-block; width: 12px; height: 12px; border-radius: 50%;
  vertical-align: middle; margin-right: 6px;
}
.rvScoreSwatch--black {
  background: radial-gradient(circle at 35% 30%, #3a3a3a 0%, #0a0a0a 100%);
  border: 1px solid #000;
}
.rvScoreSwatch--white {
  background: radial-gradient(circle at 35% 30%, #fff 0%, #c9c5be 100%);
  border: 1px solid #888;
}

/* ─── Board ─────────────────────────────────────────────────────────── */
.rvBoardWrap { display: flex; justify-content: center; margin: 8px 0 12px; }
.rvBoard {
  display: inline-block;
  padding: 8px;
  border-radius: 10px;
  background: linear-gradient(135deg, #4a2c1a 0%, #2a1a10 100%);
  box-shadow:
    inset 0 0 0 1px rgba(0, 0, 0, 0.45),
    0 8px 22px rgba(0, 0, 0, 0.45);
}
.rvFileRow { display: flex; align-items: center; }
.rvBoardRow { display: flex; align-items: center; }
.rvFileLabel,
.rvRankLabel,
.rvLabelCorner {
  width: 38px; height: 16px;
  display: flex; align-items: center; justify-content: center;
  font-size: 10px; letter-spacing: 1px;
  color: rgba(245, 196, 81, 0.65);
}
.rvRankLabel { width: 16px; height: 38px; }
.rvCell {
  width: 38px; height: 38px;
  border: 1px solid rgba(0, 0, 0, 0.45);
  background: #1f5c3a;
  cursor: default;
  display: flex; align-items: center; justify-content: center;
  position: relative;
  transition: background 0.15s ease;
}
.rvCell--playable { cursor: pointer; }
.rvCell--playable:hover { background: #29754a; }
.rvCell--last::after {
  content: '';
  position: absolute;
  bottom: 3px; right: 3px;
  width: 5px; height: 5px;
  border-radius: 50%;
  background: #f5c451;
  box-shadow: 0 0 4px rgba(245, 196, 81, 0.8);
}
.rvStone {
  width: 30px; height: 30px; border-radius: 50%;
  box-shadow:
    inset -2px -3px 6px rgba(0, 0, 0, 0.5),
    0 2px 3px rgba(0, 0, 0, 0.45);
}
.rvStone--black {
  background: radial-gradient(circle at 35% 30%, #4a4a4a 0%, #1a1a1a 60%, #050505 100%);
}
.rvStone--white {
  background: radial-gradient(circle at 35% 30%, #ffffff 0%, #d9d4c8 60%, #a8a39a 100%);
}
.rvStone--justPlayed {
  animation: rvDrop 0.35s ease-out;
}
@keyframes rvDrop {
  0% { transform: scale(0); opacity: 0; }
  60% { transform: scale(1.15); opacity: 1; }
  100% { transform: scale(1); opacity: 1; }
}

@media (max-width: 480px) {
  .rvCell, .rvFileLabel, .rvLabelCorner { width: 32px; height: 32px; }
  .rvRankLabel { width: 14px; height: 32px; }
  .rvStone { width: 26px; height: 26px; }
  .rvHero { flex-direction: column; gap: 12px; }
}

/* ─── Demo hint (shared aesthetic with TTT) ─────────────────────────── */
.demoHint {
  display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
  padding: 6px 10px; margin: 8px auto;
  max-width: 520px; border-radius: 8px;
  background: rgba(245, 196, 81, 0.08);
  border: 1px dashed rgba(245, 196, 81, 0.45);
  color: rgba(255, 255, 255, 0.85);
  font-size: 12px;
}
.demoHintDot {
  width: 8px; height: 8px; border-radius: 50%; background: #f5c451;
  box-shadow: 0 0 6px rgba(245, 196, 81, 0.8);
  animation: demoPulse 1.6s ease-in-out infinite;
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
</style>
