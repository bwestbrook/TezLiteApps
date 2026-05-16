<script>
// Fortune Cookie — tap, crack, read a Claude-generated mediocre fortune,
// optionally mint it as a keepsake NFT.
//
// Flow:
//   idle      → user clicks. Sign cheap `record_fortune` op (skipped while
//                the contract is a KT1XXX placeholder).
//   cracking  → the two halves swing apart, shadow widens. In parallel we
//                hit FORTUNE_API_URL (or the local stub) for the text.
//   revealing → slip slides out, text types in 1 char at a time.
//   revealed  → CRACK ANOTHER (resets) and KEEP THIS ONE (FA2 mint) appear.
//
// Visual model is SVG with a single static viewBox. Plinko comments document
// why we don't use Three.js in this app — same constraint here.

import {
  FORTUNE_CONTRACT_ADDRESS,
  FORTUNE_API_URL,
  FORTUNE_GAME_INFO,
  BLOCKCHAIN_ENABLED,
} from '../constants'

const STAGES = {
  IDLE: 'idle',
  CRACKING: 'cracking',
  REVEALING: 'revealing',
  REVEALED: 'revealed',
}

// Local fallback for when FORTUNE_API_URL is empty (no backend yet) or the
// request fails. Deliberately mediocre — the cookie is the point.
const STUB_FORTUNES = [
  { text: 'You will find a sock you forgot you owned.', category: 'prediction' },
  { text: 'Your courage is in your other pants.', category: 'wisdom' },
  { text: 'A pessimist is just a realist with good Wi-Fi.', category: 'joke' },
  { text: 'Tuesday will be longer than it has any right to be.', category: 'curse' },
  { text: 'The early bird gets the worm. The late bird gets brunch.', category: 'joke' },
  { text: 'Speak softly and forget the second half of this sentence.', category: 'wisdom' },
  { text: 'Your future is bright. Wear sunglasses indoors.', category: 'prediction' },
  { text: 'Someone is thinking about you. They want their charger back.', category: 'prediction' },
  { text: 'You will reheat the same coffee three times this week.', category: 'curse' },
  { text: 'Today is a great day to remember a password from 2014.', category: 'wisdom' },
  { text: 'Trust the process. The process is just guessing.', category: 'joke' },
  { text: 'A cat thinks you are doing fine, mostly.', category: 'wisdom' },
]

function isPlaceholder(addr) {
  return !addr || /^KT1X{10,}/.test(addr)
}

function wrapText(text, maxChars) {
  const words = text.split(/\s+/)
  const lines = []
  let line = ''
  for (const w of words) {
    if ((line + ' ' + w).trim().length > maxChars && line) {
      lines.push(line.trim())
      line = w
    } else {
      line = (line + ' ' + w).trim()
    }
  }
  if (line) lines.push(line)
  return lines
}

export default {
  name: 'fortuneCookie',
  props: ['socket', 'wallet', 'tezos'],
  data() {
    return {
      stage: STAGES.IDLE,
      fortune: null,
      typedText: '',
      typingTimer: null,
      bobFrame: 0,
      bobT: 0,
      cracking: false,
      keeping: false,
      keptThis: false,
      blockchainStatus: 'Tap the cookie.',
      info: FORTUNE_GAME_INFO,
      showInfo: false,
      // Estimated fees — match the contract's eventual config. Display only.
      logFee: 0.05,
      mintFee: 0.50,
    }
  },
  computed: {
    stageHint() {
      if (this.stage === STAGES.IDLE) return 'fortune awaits'
      if (this.stage === STAGES.CRACKING) return 'cracking…'
      if (this.stage === STAGES.REVEALING) return 'reading…'
      return this.keptThis ? 'minted ✓' : 'keep or crack again'
    },
    isPlaceholderContract() { return isPlaceholder(FORTUNE_CONTRACT_ADDRESS) },
    // Idle: gentle bob + slight roll. Frozen the moment we start cracking
    // so the crack animation reads clean.
    cookieWrapStyle() {
      const idle = this.stage === STAGES.IDLE
      const y = idle ? Math.sin(this.bobT * 1.8) * 3 : 0
      const r = idle ? Math.sin(this.bobT * 1.3) * 1.6 : 0
      return { transform: `translate(0px, ${(-8 + y).toFixed(2)}px) rotate(${r.toFixed(2)}deg)` }
    },
    leftHalfStyle() {
      const open = this.stage !== STAGES.IDLE
      const x = open ? -52 : 0
      const y = open ? 6 : 0
      const r = open ? -22 : 0
      return { transform: `translate(${x}px, ${y}px) rotate(${r}deg)` }
    },
    rightHalfStyle() {
      const open = this.stage !== STAGES.IDLE
      const x = open ? 52 : 0
      const y = open ? 6 : 0
      const r = open ? 22 : 0
      return { transform: `translate(${x}px, ${y}px) rotate(${r}deg)` }
    },
    slipStyle() {
      if (this.stage === STAGES.IDLE) return { opacity: 0, transform: 'translate(0px, 6px) scale(0.4)' }
      if (this.stage === STAGES.CRACKING) return { opacity: 0.2, transform: 'translate(0px, 0px) scale(0.55)' }
      return { opacity: 1, transform: 'translate(0px, -38px) scale(1)' }
    },
    shadowStyle() {
      const open = this.stage !== STAGES.IDLE
      return { transform: `scaleX(${open ? 1.55 : 1})` }
    },
    slipLines() {
      const t = this.typedText || ''
      return wrapText(t, 26)
    },
    // Mirror of the left path along the y-axis.
    leftHalfPath() {
      // (-3,-55) top pinch → bulge left out to (-78,0) → (-3,55) bottom
      // pinch → close back up the seam.
      return 'M -3,-55 C -18,-52 -68,-46 -78,-6 C -78,28 -42,52 -3,55 L -3,-55 Z'
    },
    rightHalfPath() {
      return 'M 3,-55 C 18,-52 68,-46 78,-6 C 78,28 42,52 3,55 L 3,-55 Z'
    },
    canCrack() {
      return this.stage === STAGES.IDLE && !this.cracking
    },
  },
  created() {
    this.startBob()
  },
  beforeUnmount() {
    if (this.bobFrame) cancelAnimationFrame(this.bobFrame)
    if (this.typingTimer) clearTimeout(this.typingTimer)
  },
  methods: {
    startBob() {
      const t0 = performance.now()
      let lastWrite = 0
      const tick = (now) => {
        if (now - lastWrite >= 60) {
          this.bobT = (now - t0) / 1000
          lastWrite = now
        }
        this.bobFrame = requestAnimationFrame(tick)
      }
      this.bobFrame = requestAnimationFrame(tick)
    },
    onSceneClick() {
      if (this.canCrack) this.crack()
    },
    async crack() {
      if (!this.canCrack) return
      this.cracking = true
      this.keptThis = false
      this.fortune = null
      this.typedText = ''
      this.blockchainStatus = this.isPlaceholderContract
        ? 'Cracking… (contract not deployed yet — log skipped)'
        : 'Signing crack op…'

      // Optional: sign the cheap log op first (skipped on placeholder).
      if (!this.isPlaceholderContract && BLOCKCHAIN_ENABLED && this.wallet) {
        try {
          await this.recordOnChain('pending…')
        } catch (e) {
          this.blockchainStatus = `Crack cancelled: ${(e?.message || '').slice(0, 80)}`
          this.cracking = false
          return
        }
      }

      this.stage = STAGES.CRACKING
      // Kick off LLM fetch in parallel with the crack animation.
      const fortunePromise = this.fetchFortune()
      // Crack animation runs ~700ms; wait both before revealing.
      await new Promise((r) => setTimeout(r, 700))
      const fortune = await fortunePromise
      this.fortune = fortune
      this.stage = STAGES.REVEALING
      this.blockchainStatus = this.isPlaceholderContract
        ? 'Reading the slip…'
        : `Crack logged. Reading the slip…`
      this.startTypewriter(fortune.text)
    },
    async fetchFortune() {
      if (FORTUNE_API_URL) {
        try {
          const res = await fetch(FORTUNE_API_URL, { method: 'POST' })
          if (res.ok) {
            const body = await res.json()
            if (body && typeof body.text === 'string') return body
          }
        } catch (e) {
          console.warn('[fortune] api failed, using stub:', e?.message)
        }
      }
      return STUB_FORTUNES[Math.floor(Math.random() * STUB_FORTUNES.length)]
    },
    startTypewriter(text) {
      this.typedText = ''
      let i = 0
      const step = () => {
        if (i >= text.length) {
          this.stage = STAGES.REVEALED
          this.cracking = false
          this.blockchainStatus = this.isPlaceholderContract
            ? 'Mint disabled until contract is deployed. Crack another any time.'
            : 'Keep this one as an NFT, or crack another.'
          return
        }
        this.typedText += text[i++]
        this.typingTimer = setTimeout(step, 32)
      }
      step()
    },
    // Cheap log op — `record_fortune(text)`. Placeholder body until the
    // contract ships. We call it BEFORE the LLM resolves so the on-chain
    // record is "I paid to crack", not "I paid for this specific text" —
    // the text gets attached on the keep_fortune mint.
    async recordOnChain(_placeholderText) {
      // Real implementation, once deployed:
      //
      //   this.tezos.setWalletProvider(this.wallet)
      //   const c = await this.tezos.wallet.at(FORTUNE_CONTRACT_ADDRESS)
      //   const op = await c.methodsObject.record_fortune(
      //     _placeholderText,
      //   ).send({ amount: this.logFee.toFixed(6) })
      //   await op.confirmation()
      //
      // For now: no-op so the UI flow runs end-to-end pre-contract.
      return
    },
    async keepFortune() {
      if (!this.fortune || this.keeping || this.keptThis) return
      this.keeping = true
      this.blockchainStatus = 'Minting keepsake…'
      try {
        if (this.isPlaceholderContract || !this.wallet) {
          // Simulated path while the contract isn't deployed.
          await new Promise((r) => setTimeout(r, 600))
        } else {
          this.tezos.setWalletProvider(this.wallet)
          const c = await this.tezos.wallet.at(FORTUNE_CONTRACT_ADDRESS)
          const op = await c.methodsObject.keep_fortune(this.fortune.text).send({
            amount: this.mintFee.toFixed(6),
          })
          await op.confirmation()
        }
        this.keptThis = true
        this.blockchainStatus = 'Kept. Find it in Browse 2.725K.'
      } catch (e) {
        const msg = (e?.message || String(e)).slice(0, 140)
        if (/aborted|cancel|denied/i.test(msg)) {
          this.blockchainStatus = 'Mint cancelled in wallet.'
        } else {
          this.blockchainStatus = `Mint failed: ${msg}`
        }
      } finally {
        this.keeping = false
      }
    },
    reset() {
      if (this.typingTimer) clearTimeout(this.typingTimer)
      this.typingTimer = null
      this.typedText = ''
      this.fortune = null
      this.keptThis = false
      this.stage = STAGES.IDLE
      this.blockchainStatus = 'Tap the cookie.'
    },
  },
}
</script>

<template>
  <div class="fortuneRoot">
    <div class="fortuneHeader">
      <div class="fortuneTitle">FORTUNE COOKIE</div>
      <div class="fortuneSub">{{ stageHint }}</div>
    </div>

    <div class="sceneFrame">
      <svg
        viewBox="-200 -160 400 320"
        :class="['scene', canCrack ? 'scene--clickable' : '']"
        @click="onSceneClick"
      >
        <defs>
          <radialGradient id="cookieGrad" cx="42%" cy="34%" r="68%">
            <stop offset="0%" stop-color="#f6dba8" />
            <stop offset="55%" stop-color="#c89a4e" />
            <stop offset="100%" stop-color="#5a3812" />
          </radialGradient>
          <radialGradient id="cookieInner" cx="50%" cy="40%" r="55%">
            <stop offset="0%" stop-color="#8a6326" />
            <stop offset="100%" stop-color="#3a2210" />
          </radialGradient>
          <linearGradient id="tableGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stop-color="#3a1d1a" />
            <stop offset="100%" stop-color="#0d0408" />
          </linearGradient>
          <radialGradient id="slipGrad" cx="50%" cy="30%" r="70%">
            <stop offset="0%" stop-color="#fdf7e7" />
            <stop offset="100%" stop-color="#e6dabc" />
          </radialGradient>
        </defs>

        <!-- Table -->
        <ellipse cx="0" cy="62" rx="170" ry="26" fill="url(#tableGrad)" stroke="rgba(245,236,225,0.07)" />

        <!-- Cookie shadow — widens when the cookie opens. -->
        <ellipse
          cx="0" cy="52" rx="58" ry="8"
          fill="rgba(0,0,0,0.55)"
          class="cookieShadow"
          :style="shadowStyle"
        />

        <!-- Slip of paper — under cookie until reveal. -->
        <g :style="slipStyle" class="slip">
          <rect x="-92" y="-26" width="184" height="52" rx="3" fill="url(#slipGrad)" stroke="rgba(0,0,0,0.22)" />
          <!-- Decorative top-left mark -->
          <text x="-84" y="-13" font-size="6" fill="#8a6326" font-family="var(--ad-font-mono)" opacity="0.7">·your fortune·</text>
          <!-- Body — typed in one char at a time -->
          <text x="0" y="0" text-anchor="middle" class="slipBody" font-family="var(--ad-font-mono)" font-size="11" fill="#3a2210">
            <tspan v-for="(line, i) in slipLines" :key="i" x="0" :dy="i === 0 ? 0 : 13">{{ line }}</tspan>
          </text>
          <!-- Lucky numbers — pure decor. -->
          <text x="84" y="20" text-anchor="end" font-size="6" fill="#8a6326" font-family="var(--ad-font-mono)" opacity="0.7">
            lucky 7 · 14 · 22 · 33
          </text>
        </g>

        <!-- Cookie wrapper — bobs gently when idle. -->
        <g :style="cookieWrapStyle" class="cookieWrap">

          <!-- Inner shading visible once halves split. -->
          <ellipse
            v-if="stage !== 'idle'"
            cx="0" cy="0" rx="46" ry="36"
            fill="url(#cookieInner)" opacity="0.85"
          />

          <g :style="leftHalfStyle" class="cookieHalf cookieHalf--left">
            <path :d="leftHalfPath" fill="url(#cookieGrad)" stroke="#3a2210" stroke-width="1.2" />
            <!-- Toasted speckles for texture -->
            <circle cx="-30" cy="-20" r="1.6" fill="#5a3812" opacity="0.55" />
            <circle cx="-50" cy="10"  r="1.2" fill="#5a3812" opacity="0.45" />
            <circle cx="-22" cy="28"  r="1.1" fill="#5a3812" opacity="0.5" />
            <!-- Fold ridge along the seam — only visible when closed. -->
            <line v-if="stage === 'idle'" x1="-3" y1="-50" x2="-3" y2="50" stroke="rgba(0,0,0,0.30)" stroke-width="1.5" />
          </g>

          <g :style="rightHalfStyle" class="cookieHalf cookieHalf--right">
            <path :d="rightHalfPath" fill="url(#cookieGrad)" stroke="#3a2210" stroke-width="1.2" />
            <circle cx="28"  cy="-12" r="1.4" fill="#5a3812" opacity="0.55" />
            <circle cx="48"  cy="16"  r="1.2" fill="#5a3812" opacity="0.45" />
            <circle cx="22"  cy="32"  r="1.0" fill="#5a3812" opacity="0.5" />
          </g>
        </g>
      </svg>
    </div>

    <div class="statusPanel">
      <div class="statusLine">{{ blockchainStatus }}</div>
    </div>

    <div class="actionsRow" v-if="stage === 'revealed'">
      <button
        type="button"
        class="actBtn actBtn--again"
        :disabled="cracking"
        @click="reset"
      >CRACK ANOTHER · {{ logFee.toFixed(2) }} ꜩ</button>
      <button
        type="button"
        :class="['actBtn', 'actBtn--keep', keptThis ? 'actBtn--kept' : '']"
        :disabled="keeping || keptThis"
        @click="keepFortune"
      >
        <span v-if="keeping">MINTING…</span>
        <span v-else-if="keptThis">KEPT ✓</span>
        <span v-else>KEEP THIS ONE · {{ mintFee.toFixed(2) }} ꜩ</span>
      </button>
    </div>

    <button
      v-if="stage === 'idle'"
      type="button"
      class="crackBtn"
      :disabled="!canCrack"
      @click="crack"
    >TAP TO CRACK · {{ logFee.toFixed(2) }} ꜩ</button>

    <button
      type="button"
      class="howToBtn"
      :aria-expanded="showInfo"
      @click="showInfo = !showInfo"
    >How it works <span aria-hidden="true">{{ showInfo ? '▲' : '▼' }}</span></button>
    <div v-if="showInfo" class="infoBlock">
      <div v-for="(line, i) in info" :key="i" class="infoLine">· {{ line }}</div>
    </div>
  </div>
</template>

<style scoped>
.fortuneRoot {
  display: flex; flex-direction: column; gap: 14px;
  padding: 16px;
  max-width: 680px; width: 100%; margin: 0 auto;
  color: var(--ad-text-1);
}

.fortuneHeader { text-align: center; }
.fortuneTitle {
  font-family: var(--ad-font-display);
  font-size: 28px;
  letter-spacing: 0.12em;
  background: var(--ad-grad-fire);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}
.fortuneSub {
  font-family: var(--ad-font-mono);
  font-size: 11px;
  color: var(--ad-text-3);
  letter-spacing: 0.08em;
  text-transform: uppercase;
  margin-top: 2px;
}

.sceneFrame {
  background:
    radial-gradient(ellipse at 50% 0%, rgba(125, 211, 200, 0.14) 0%, transparent 62%),
    var(--ad-bg-elev-1);
  border: 1px solid var(--ad-border-soft);
  border-radius: var(--ad-r-lg);
  padding: 10px;
}
.scene {
  width: 100%; display: block;
  cursor: default;
  user-select: none;
  -webkit-tap-highlight-color: transparent;
}
.scene--clickable { cursor: pointer; }

/* Every transformable group transitions smoothly between stages. The bob
   tick updates ~17×/s — well below the 350ms transition, so the spring
   never thrashes — but we cut the bob duration short so it still reads
   as live. */
.cookieWrap {
  transition: transform 0.18s linear;
  transform-origin: 0 0;
  transform-box: fill-box;
}
.cookieHalf {
  transition: transform 0.7s cubic-bezier(0.22, 0.61, 0.36, 1);
  transform-origin: 0 0;
  transform-box: fill-box;
  filter: drop-shadow(0 1px 1px rgba(0,0,0,0.45));
}
.cookieShadow {
  transition: transform 0.7s cubic-bezier(0.22, 0.61, 0.36, 1);
  transform-origin: center;
  transform-box: fill-box;
}
.slip {
  transition: transform 0.6s cubic-bezier(0.22, 0.61, 0.36, 1), opacity 0.6s ease;
  transform-origin: 0 0;
  transform-box: fill-box;
  filter: drop-shadow(0 2px 4px rgba(0,0,0,0.5));
}
.slipBody { letter-spacing: 0.02em; }

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

.crackBtn {
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
  transition: transform 0.12s ease, box-shadow 0.2s ease, filter 0.15s ease;
}
.crackBtn:hover:not(:disabled) { transform: translateY(-1px); filter: brightness(1.05); }
.crackBtn:active:not(:disabled) { transform: translateY(0); }
.crackBtn:disabled { opacity: 0.55; cursor: not-allowed; }

.actionsRow {
  display: flex; gap: 8px;
}
.actBtn {
  flex: 1;
  border-radius: var(--ad-r-md);
  border: 0;
  padding: 12px 14px;
  font-family: var(--ad-font-display);
  font-size: 14px;
  letter-spacing: 0.06em;
  cursor: pointer;
  transition: transform 0.12s ease, filter 0.15s ease, box-shadow 0.2s ease;
}
.actBtn:hover:not(:disabled) { transform: translateY(-1px); filter: brightness(1.05); }
.actBtn:active:not(:disabled) { transform: translateY(0); }
.actBtn:disabled { opacity: 0.55; cursor: not-allowed; }
.actBtn--again {
  background: var(--ad-bg-elev-2);
  color: var(--ad-text-1);
  border: 1px solid var(--ad-border-mid);
}
.actBtn--keep {
  background: var(--ad-grad-violet);
  color: #04201d;
  box-shadow: var(--ad-glow-violet);
}
.actBtn--kept {
  background: var(--ad-bg-elev-2);
  color: var(--ad-violet-1);
  border: 1px solid rgba(125, 211, 200, 0.45);
  box-shadow: none;
}

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

@media (max-width: 480px) {
  .infoBlock { font-size: 10px; }
  .crackBtn { font-size: 16px; padding: 12px 14px; }
  .actBtn { font-size: 12.5px; padding: 12px 10px; }
}
</style>
