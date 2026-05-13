<script>
// War — 5-card head-to-head showdown.
//
// Repackaging of the classic card game "War" as a fast, on-chain settled bet:
//
//   1. Player A creates a game with a stake.
//   2. Player B matches it. The oracle shuffles a deck.
//   3. Five cards dealt to each player, face up.
//   4. Hand value = sum of ranks (A=14, K=13, Q=12, J=11, 2-10 face value).
//   5. Higher total takes the pot minus a 10% holder fee.
//   6. Exact tie → one more card each (sudden death). Tie again → push.
//
// This is *strictly* 50/50 by construction — same deck, identical priors, zero
// decisions on either side. The only "house edge" is the holder fee.
//
// Demo mode runs entirely client-side: redeal random shuffles to preview the
// visuals before any contract is deployed or any wallet is connected.

import { getContractStorage } from '../services/tzkt'
import {
  BLOCKCHAIN_ENABLED,
  WAR_CONTRACT_ADDRESS,
  WAR_GAME_INFO,
} from '../constants'

const SUIT_GLYPHS = ['♣', '♦', '♥', '♠']
const RANK_LABELS = { 11: 'J', 12: 'Q', 13: 'K', 14: 'A' }

function rankOf(deckIndex) {
  return Math.floor(deckIndex / 4) + 2
}
function suitOf(deckIndex) {
  return deckIndex % 4
}
function shortLabel(deckIndex) {
  if (deckIndex == null || deckIndex < 0) return ''
  const r = rankOf(deckIndex)
  const s = suitOf(deckIndex)
  return `${RANK_LABELS[r] || r}${SUIT_GLYPHS[s]}`
}
function suitColor(deckIndex) {
  const s = suitOf(deckIndex)
  return s === 1 || s === 2 ? 'red' : 'black'
}

// Fisher-Yates shuffle for demo mode. Returns array of unique deck indices.
function shuffleDeck() {
  const d = []
  for (let i = 0; i < 52; i++) d.push(i)
  for (let i = d.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1))
    ;[d[i], d[j]] = [d[j], d[i]]
  }
  return d
}

const PHASE_LABELS = {
  0: 'Open — waiting for opponent',
  1: 'Dealing',
  2: 'You win',
  3: 'You lose',
  4: 'Push (tie)',
}

export default {
  name: 'warGame',
  props: ['socket', 'wallet', 'tezos'],
  data() {
    return {
      info: WAR_GAME_INFO,
      walletAddress: '',
      currentGameId: 0,
      activeGameId: null,
      games: {},
      stakeMutez: 1_000_000,
      pollInterval: null,
      blockchainStatus: 'idle',
      view: 'landing',
      showRules: false,
      // ─── Demo mode state ─────────────────────────────────────────────
      // Pre-deal a hand so the board has something to show on first load.
      demoYou: [],
      demoOpp: [],
      // 0=face-down, 1=revealed
      youRevealed: [false, false, false, false, false],
      oppRevealed: [false, false, false, false, false],
      demoVerdict: null, // 'win' | 'lose' | 'push'
      // Path the load deck — built lazily because we need require() resolved.
      deck: [],
    }
  },
  computed: {
    game() {
      return this.activeGameId == null ? null : this.games[this.activeGameId]
    },
    inRealGame() {
      return !!this.game
    },
    openGames() {
      return Object.entries(this.games)
        .filter(([, g]) => Number(g.phase) === 0)
        .map(([id, g]) => ({ id: Number(id), ...g }))
    },
    phaseLabel() {
      if (!this.game) return 'Demo deal'
      return PHASE_LABELS[Number(this.game.phase)] || `phase ${this.game.phase}`
    },
    stakeTez() {
      if (!this.game) return (this.stakeMutez / 1_000_000).toFixed(3)
      return (Number(this.game.stake) / 1_000_000).toFixed(3)
    },
    potTez() {
      if (!this.game) return '—'
      return ((Number(this.game.stake) * 2) / 1_000_000).toFixed(3)
    },
    yourTotal() {
      return this.demoYou.reduce((sum, idx, i) => sum + (this.youRevealed[i] ? rankOf(idx) : 0), 0)
    },
    oppTotal() {
      return this.demoOpp.reduce((sum, idx, i) => sum + (this.oppRevealed[i] ? rankOf(idx) : 0), 0)
    },
    allRevealed() {
      return this.youRevealed.every((r) => r) && this.oppRevealed.every((r) => r)
    },
  },
  created() {
    this.socket.on('newWallet', (w) => {
      this.walletAddress = w
    })
    // Webpack picks these up at build time via require().
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
    this.dealDemo()
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
    cardFace(idx) {
      if (idx == null || idx < 0) return null
      return this.deck[idx] || null
    },
    cardLabel(idx) {
      return shortLabel(idx)
    },
    suitColor(idx) {
      return suitColor(idx)
    },
    // ─── Demo: deal & reveal ────────────────────────────────────────
    dealDemo() {
      const shuffled = shuffleDeck()
      this.demoYou = shuffled.slice(0, 5)
      this.demoOpp = shuffled.slice(5, 10)
      this.youRevealed = [false, false, false, false, false]
      this.oppRevealed = [false, false, false, false, false]
      this.demoVerdict = null
      // Stagger the reveal so it reads as a deal.
      const reveal = (which, i, delay) => {
        setTimeout(() => {
          if (which === 'you') {
            this.youRevealed = this.youRevealed.map((r, idx) => (idx === i ? true : r))
          } else {
            this.oppRevealed = this.oppRevealed.map((r, idx) => (idx === i ? true : r))
          }
        }, delay)
      }
      for (let i = 0; i < 5; i++) {
        reveal('you', i, 220 + i * 180)
        reveal('opp', i, 320 + i * 180)
      }
      setTimeout(() => this.computeVerdict(), 220 + 5 * 180 + 200)
    },
    computeVerdict() {
      const y = this.demoYou.reduce((s, idx) => s + rankOf(idx), 0)
      const o = this.demoOpp.reduce((s, idx) => s + rankOf(idx), 0)
      if (y > o) this.demoVerdict = 'win'
      else if (y < o) this.demoVerdict = 'lose'
      else this.demoVerdict = 'push'
    },
    // ─── Contract calls ────────────────────────────────────────────
    async refresh() {
      try {
        const storage = await getContractStorage(WAR_CONTRACT_ADDRESS)
        if (!storage) return
        this.currentGameId = Number(storage.currentGameId || 0)
        this.games = storage.games || {}
        if (this.activeGameId == null && this.currentGameId > 0) {
          this.activeGameId = this.currentGameId - 1
        }
      } catch (e) {
        console.warn('war refresh failed:', e?.message)
      }
    },
    async createGame() {
      try {
        this.tezos.setWalletProvider(this.wallet)
        this.blockchainStatus = 'creating war game...'
        const total = this.stakeMutez + 50000
        const contract = await this.tezos.wallet.at(WAR_CONTRACT_ADDRESS)
        const op = await contract.methodsObject
          .createGame({ stake: this.stakeMutez })
          .send({ amount: total / 1_000_000 })
        await op.confirmation()
        this.blockchainStatus = 'created.'
        await this.refresh()
      } catch (err) {
        console.error('war create failed:', err)
        this.blockchainStatus = 'create failed'
      }
    },
    async joinGame(gameId) {
      try {
        this.tezos.setWalletProvider(this.wallet)
        const g = this.games[gameId]
        const total = Number(g.stake) + 50000
        const contract = await this.tezos.wallet.at(WAR_CONTRACT_ADDRESS)
        const op = await contract.methodsObject
          .joinGame({ gameId })
          .send({ amount: total / 1_000_000 })
        await op.confirmation()
        this.activeGameId = gameId
        await this.refresh()
      } catch (err) {
        console.error('war join failed:', err)
      }
    },
    async claim() {
      try {
        this.tezos.setWalletProvider(this.wallet)
        const contract = await this.tezos.wallet.at(WAR_CONTRACT_ADDRESS)
        const op = await contract.methodsObject.claim().send()
        await op.confirmation()
        this.blockchainStatus = 'claimed.'
      } catch (err) {
        console.error('war claim failed:', err)
      }
    },
  },
}
</script>

<template>
  <div class="gameManagement warRoot">
    <!-- ───── Landing view ────────────────────────────────────────────── -->
    <template v-if="view === 'landing'">
      <div class="warHero">
        <div class="warHeroBrand">
          <div class="warHeroEyebrow">WAR · 5-CARD SHOWDOWN</div>
          <div class="warHeroTitle">Pure-luck H2H. 50/50.</div>
          <div class="warHeroSub">
            Both players ante up. Oracle shuffles a deck. Five cards each, face
            up. Higher rank-sum wins the pot. Exact tie → sudden death. No skill
            required, no edge for either side — only the holder fee.
          </div>
        </div>
        <div class="warHeroBoard" aria-hidden="true">
          <svg viewBox="0 0 120 80" class="warHeroSvg">
            <defs>
              <linearGradient id="wBack" x1="0" y1="0" x2="1" y2="1">
                <stop offset="0%" stop-color="#190857"/>
                <stop offset="100%" stop-color="#2a1577"/>
              </linearGradient>
            </defs>
            <!-- Two facing piles -->
            <rect x="10" y="20" width="38" height="50" rx="3" fill="url(#wBack)" stroke="#f5c451" stroke-width="1" transform="rotate(-8, 29, 45)"/>
            <rect x="72" y="20" width="38" height="50" rx="3" fill="url(#wBack)" stroke="#f5c451" stroke-width="1" transform="rotate(8, 91, 45)"/>
            <text x="29" y="50" text-anchor="middle" font-size="14" font-weight="700" fill="#f5c451" transform="rotate(-8, 29, 45)">A♠</text>
            <text x="91" y="50" text-anchor="middle" font-size="14" font-weight="700" fill="#f5c451" transform="rotate(8, 91, 45)">K♥</text>
          </svg>
        </div>
      </div>

      <div class="warStatusRow">
        <div class="warPill">
          <div class="warPillLabel">Phase</div>
          <div class="warPillValue">{{ phaseLabel }}</div>
        </div>
        <div class="warPill">
          <div class="warPillLabel">Game</div>
          <div class="warPillValue">{{ activeGameId == null ? '—' : '#' + activeGameId }}</div>
        </div>
        <div class="warPill">
          <div class="warPillLabel">Stake</div>
          <div class="warPillValue">{{ stakeTez }} ꜩ</div>
          <div class="warPillFootnote">+ 0.05 ꜩ fee</div>
        </div>
        <div class="warPill">
          <div class="warPillLabel">Pot</div>
          <div class="warPillValue">{{ potTez }} ꜩ</div>
        </div>
        <div class="warPill">
          <div class="warPillLabel">House edge</div>
          <div class="warPillValue">10%</div>
          <div class="warPillFootnote">holder fee on pot</div>
        </div>
      </div>

      <div class="rowFlex warPrimaryRow">
        <div class="actionButton warPrimary" @click="setView('play')">Open table</div>
        <div class="actionButton" @click="createGame">New game ({{ (stakeMutez / 1000000).toFixed(2) }} ꜩ)</div>
        <div class="actionButton" @click="claim">Claim winnings</div>
        <div class="actionButtonHelp" @click="toggleRules">{{ showRules ? 'Hide rules' : 'How it works' }}</div>
      </div>

      <div v-if="openGames.length" class="rowFlex">
        <div class="gameInfo warOpenLabel">Open challenges:</div>
        <div
          v-for="g in openGames"
          :key="g.id"
          class="actionButton"
          @click="joinGame(g.id)"
        >Join #{{ g.id }} — {{ (Number(g.stake) / 1000000).toFixed(2) }} ꜩ</div>
      </div>

      <div v-if="showRules" class="warRules">
        <ol>
          <li v-for="(line, i) in info" :key="i">{{ line }}</li>
        </ol>
      </div>

      <div class="gameInfo warStatusLine">{{ blockchainStatus }}</div>
    </template>

    <!-- ───── Play view ───────────────────────────────────────────────── -->
    <template v-else>
      <div class="rowFlex warPlayHeader">
        <div class="actionButton warBackBtn" @click="setView('landing')">‹ Lobby</div>
        <div class="gameInfo">
          {{ game ? 'Game #' + activeGameId + ' · ' + phaseLabel : 'Demo deal' }}
        </div>
        <div class="actionButton" @click="refresh">Refresh</div>
      </div>

      <div class="warTableWrap">
        <div :class="['warTable', demoVerdict ? `warTable--${demoVerdict}` : '']">
          <div class="warRail" aria-hidden="true"></div>
          <div class="warFelt">
            <div class="warBrand">5-CARD WAR</div>

            <!-- Opponent's hand (top, face up after reveal) -->
            <div class="warSide warSide--opp">
              <div class="warSideLabel">
                Opponent
                <span class="warTotal">{{ oppTotal || 0 }}</span>
              </div>
              <div class="warHand">
                <div
                  v-for="(idx, i) in demoOpp"
                  :key="'opp-' + i"
                  class="warCardSlot"
                >
                  <div :class="['warCard', { 'warCard--flipped': oppRevealed[i] }]">
                    <div class="warCardFace warCardFace--back">
                      <div class="warBack"><div class="warBackInner"><div class="warBackMark">W</div></div></div>
                    </div>
                    <div class="warCardFace warCardFace--front">
                      <img
                        v-if="cardFace(idx)"
                        :src="cardFace(idx)"
                        :alt="cardLabel(idx)"
                        class="warCardImg"
                        draggable="false"
                      />
                      <div :class="['warCardCorner', `warCardCorner--${suitColor(idx)}`]">
                        {{ cardLabel(idx) }}
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <div class="warVs">vs</div>

            <!-- Your hand (bottom) -->
            <div class="warSide warSide--you">
              <div class="warSideLabel">
                You
                <span class="warTotal">{{ yourTotal || 0 }}</span>
              </div>
              <div class="warHand">
                <div
                  v-for="(idx, i) in demoYou"
                  :key="'you-' + i"
                  class="warCardSlot"
                >
                  <div :class="['warCard', { 'warCard--flipped': youRevealed[i] }]">
                    <div class="warCardFace warCardFace--back">
                      <div class="warBack"><div class="warBackInner"><div class="warBackMark">W</div></div></div>
                    </div>
                    <div class="warCardFace warCardFace--front">
                      <img
                        v-if="cardFace(idx)"
                        :src="cardFace(idx)"
                        :alt="cardLabel(idx)"
                        class="warCardImg"
                        draggable="false"
                      />
                      <div :class="['warCardCorner', `warCardCorner--${suitColor(idx)}`]">
                        {{ cardLabel(idx) }}
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <div v-if="demoVerdict === 'win'" class="warVerdict warVerdict--win">YOU WIN</div>
            <div v-else-if="demoVerdict === 'lose'" class="warVerdict warVerdict--loss">YOU LOSE</div>
            <div v-else-if="demoVerdict === 'push'" class="warVerdict warVerdict--push">PUSH</div>
          </div>
        </div>
      </div>

      <div v-if="!inRealGame" class="demoHint">
        <span class="demoHintDot"></span>
        <span class="demoHintLabel">DEMO</span>
        <span class="demoHintBody">Random demo deal. The on-chain version uses the oracle's verifiable RNG.</span>
        <button class="demoBtn" @click="dealDemo">Deal again</button>
      </div>

      <div class="rowFlex">
        <div class="actionButton" @click="createGame">New game</div>
        <div class="actionButton" @click="claim">Claim</div>
        <div class="actionButton" @click="setView('landing')">Back to lobby</div>
      </div>

      <div class="gameInfo warStatusLine">{{ blockchainStatus }}</div>
    </template>
  </div>
</template>

<style scoped>
.warRoot { font-family: 'EB Garamond', serif; color: #efeae2; }

/* ─── Hero ─────────────────────────────────────────────────────────── */
.warHero {
  display: flex; flex-direction: row; gap: 18px;
  padding: 16px 14px; margin: 8px 4px 14px;
  border-radius: 14px;
  background:
    radial-gradient(ellipse at 80% 20%, rgba(212, 162, 78, 0.15) 0%, transparent 60%),
    linear-gradient(135deg, #190857 0%, #07041e 100%);
  box-shadow:
    inset 0 0 0 1px rgba(255, 255, 255, 0.06),
    0 8px 22px rgba(0, 0, 0, 0.45);
}
.warHeroBrand { flex: 1.4; min-width: 0; }
.warHeroBoard { flex: 1; display: flex; align-items: center; justify-content: center; }
.warHeroSvg { width: 100%; max-width: 220px; }
.warHeroEyebrow { font-size: 10px; letter-spacing: 4px; font-weight: 700; color: rgba(245,196,81,0.75); margin-bottom: 6px; }
.warHeroTitle { font-size: clamp(20px, 4.5vw, 30px); line-height: 1.1; font-weight: 700; color: #fff; margin-bottom: 8px; }
.warHeroSub { font-size: 13px; line-height: 1.4; color: rgba(255, 255, 255, 0.78); }

/* ─── Status pills ──────────────────────────────────────────────────── */
.warStatusRow { display: flex; flex-wrap: wrap; gap: 6px; margin: 0 4px 12px; }
.warPill { flex: 1 1 110px; min-width: 110px; padding: 8px 10px; border-radius: 8px;
  background: rgba(255, 255, 255, 0.04); border: 1px solid rgba(255, 255, 255, 0.08); }
.warPillLabel { font-size: 9px; letter-spacing: 2px; text-transform: uppercase; color: rgba(255,255,255,0.55); }
.warPillValue { font-size: 16px; font-weight: 700; color: #fff; margin-top: 2px; }
.warPillFootnote { font-size: 10px; color: rgba(255,255,255,0.55); margin-top: 2px; }

.warPrimaryRow { margin-top: 4px; }
.warPrimary {
  background: linear-gradient(135deg, #2a1577 0%, #190857 100%);
  border-color: #f5c451;
  font-weight: 700; letter-spacing: 1px; text-transform: uppercase;
}
.warOpenLabel { flex: 0 0 auto; align-self: center; font-size: 12px; }

.warRules { margin: 8px 4px 12px; padding: 12px 16px; border-radius: 8px;
  background: rgba(255, 255, 255, 0.03); border: 1px solid rgba(255, 255, 255, 0.08); }
.warRules ol { margin: 0; padding-left: 20px; font-size: 13px; line-height: 1.55; color: rgba(255,255,255,0.85); }

.warStatusLine { font-size: 12px; color: #d4a24e; font-style: italic; }

/* ─── Play table ────────────────────────────────────────────────────── */
.warPlayHeader { margin: 4px 0 8px; }
.warBackBtn { flex: 0 0 auto; min-width: 90px; }

.warTableWrap { display: flex; justify-content: center; margin: 8px 0 12px; }
.warTable {
  position: relative;
  width: clamp(280px, 92vw, 620px);
  aspect-ratio: 4 / 3;
  border-radius: 18px;
  overflow: hidden;
  box-shadow:
    0 12px 30px rgba(0, 0, 0, 0.55),
    inset 0 0 0 1px rgba(255, 255, 255, 0.06);
  transition: box-shadow 0.4s ease;
}
.warTable--win { box-shadow: 0 0 0 2px #f5c451, 0 0 28px 6px rgba(245, 196, 81, 0.45), 0 12px 30px rgba(0, 0, 0, 0.55); }
.warTable--lose { box-shadow: 0 0 0 2px #c4524f, 0 0 22px 4px rgba(196, 82, 79, 0.35), 0 12px 30px rgba(0, 0, 0, 0.55); }
.warTable--push { box-shadow: 0 0 0 2px #d4a24e, 0 0 22px 4px rgba(212, 162, 78, 0.35), 0 12px 30px rgba(0, 0, 0, 0.55); }

.warRail {
  position: absolute; inset: 0;
  background:
    radial-gradient(ellipse at center, transparent 55%, rgba(0, 0, 0, 0.35) 100%),
    linear-gradient(135deg, #2a1a10 0%, #4a2c1a 40%, #2a1a10 100%);
  border-radius: 18px;
}
.warFelt {
  position: absolute; inset: 14px;
  border-radius: 12px;
  background: radial-gradient(ellipse at 50% 50%, #1f5c3a 0%, #0e3b22 65%, #07291a 100%);
  display: flex; flex-direction: column; justify-content: space-between;
  padding: 14px 12px 14px;
}
.warBrand {
  position: absolute; top: 8px; left: 50%; transform: translateX(-50%);
  letter-spacing: 4px; font-size: 10px; color: rgba(245, 196, 81, 0.55); font-weight: 600;
}

.warSide { display: flex; flex-direction: column; align-items: center; gap: 4px; }
.warSide--opp { transform: rotate(180deg); }
.warSide--opp .warSideLabel,
.warSide--opp .warCardCorner,
.warSide--opp .warCardImg { transform: rotate(180deg); }
/* The img and corner get the rotate back so they read upright after the side flip. */
.warSideLabel {
  font-size: 11px; letter-spacing: 2px; text-transform: uppercase;
  color: rgba(255, 255, 255, 0.85);
  display: flex; align-items: center; gap: 8px;
}
.warTotal {
  font-size: 14px; color: #f5c451; font-weight: 700;
  padding: 1px 8px; border-radius: 4px;
  background: rgba(0, 0, 0, 0.35);
}
.warHand { display: flex; flex-direction: row; gap: clamp(4px, 1.5vw, 10px); }
.warCardSlot {
  width: clamp(46px, 11vw, 82px);
  aspect-ratio: 2.5 / 3.5;
  perspective: 900px;
}
.warVs {
  text-align: center;
  font-size: 11px; letter-spacing: 4px; font-weight: 700;
  color: rgba(245, 196, 81, 0.6);
  margin: 4px 0;
}

/* ─── Card flip ─────────────────────────────────────────────────────── */
.warCard {
  position: relative; width: 100%; height: 100%;
  transform-style: preserve-3d;
  transition: transform 0.7s cubic-bezier(0.65, 0, 0.35, 1);
}
.warCard--flipped { transform: rotateY(180deg); }
.warCardFace {
  position: absolute; inset: 0;
  border-radius: 6px;
  backface-visibility: hidden;
  -webkit-backface-visibility: hidden;
  overflow: hidden;
  box-shadow: 0 4px 10px rgba(0, 0, 0, 0.45), inset 0 0 0 1px rgba(255, 255, 255, 0.08);
}
.warCardFace--back { background: #fff; }
.warCardFace--front { transform: rotateY(180deg); background: #fff; display: flex; align-items: center; justify-content: center; position: relative; }
.warCardImg { width: 100%; height: 100%; object-fit: cover; user-select: none; -webkit-user-drag: none; }
.warCardCorner {
  position: absolute; top: 3px; left: 5px;
  font-size: 10px; font-weight: 700;
  background: rgba(255, 255, 255, 0.85);
  border-radius: 3px; padding: 1px 3px; line-height: 1;
}
.warCardCorner--red { color: #c4524f; }
.warCardCorner--black { color: #1a1a1a; }

/* ─── Custom CSS card back ──────────────────────────────────────────── */
.warBack {
  width: 100%; height: 100%;
  background: repeating-linear-gradient(45deg, #190857 0 6px, #2a1577 6px 12px);
  display: flex; align-items: center; justify-content: center;
  padding: 4px;
}
.warBackInner {
  width: 100%; height: 100%;
  border: 2px solid rgba(245, 196, 81, 0.85);
  border-radius: 4px;
  display: flex; align-items: center; justify-content: center;
  background: radial-gradient(ellipse at center, rgba(25, 8, 87, 0.6) 0%, rgba(0, 0, 0, 0.5) 100%);
}
.warBackMark { font-family: 'EB Garamond', serif; font-weight: 700; font-size: clamp(18px, 4vw, 28px); color: #f5c451; text-shadow: 0 1px 2px rgba(0, 0, 0, 0.55); }

/* ─── Verdict ribbon ────────────────────────────────────────────────── */
.warVerdict {
  position: absolute; bottom: 10px; left: 50%; transform: translateX(-50%);
  font-size: 13px; letter-spacing: 4px; font-weight: 700;
  padding: 4px 14px; border-radius: 4px;
  border: 1px solid currentColor;
  animation: warVerdictIn 0.5s ease-out both;
}
.warVerdict--win { color: #f5c451; background: rgba(245, 196, 81, 0.12); }
.warVerdict--loss { color: #c4524f; background: rgba(196, 82, 79, 0.12); }
.warVerdict--push { color: #d4a24e; background: rgba(212, 162, 78, 0.12); }
@keyframes warVerdictIn { from { opacity: 0; transform: translate(-50%, 8px); } to { opacity: 1; transform: translate(-50%, 0); } }

/* ─── Demo hint ─────────────────────────────────────────────────────── */
.demoHint {
  display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
  padding: 6px 10px; margin: 8px auto;
  max-width: 620px; border-radius: 8px;
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

@media (max-width: 480px) {
  .warHero { flex-direction: column; gap: 12px; }
}
</style>
