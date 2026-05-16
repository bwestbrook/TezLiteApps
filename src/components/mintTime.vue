<template>
  <div class="centerBody">
    <h2 class="gameInfo">Mint Time</h2>
    <p class="gameInfo">
      Claim a minute (or up to 15 consecutive minutes) on planet Earth. Pick a frame,
      drop in a short note and an image, and mint a one-of-a-kind time capsule NFT.
      Every UTC minute is globally unique — once it's claimed, it's gone.
    </p>

    <!-- ── Time picker ─────────────────────────────────────────────── -->
    <div class="mintTimeSection">
      <label class="mintTimeLabel">Capsule start (UTC)</label>
      <div class="rowFlex">
        <input
          type="datetime-local"
          v-model="startInput"
          class="mintTimeInput"
          step="60"
        />
        <button class="actionButtonHelp" @click="setStartToNow">now</button>
      </div>
      <div class="mintTimeMinute">
        UTC minute #{{ startMinute.toLocaleString() }}
      </div>

      <label class="mintTimeLabel">Duration: {{ duration }} minute{{ duration === 1 ? '' : 's' }}</label>
      <input
        type="range"
        min="1"
        max="15"
        v-model.number="duration"
        class="mintTimeSlider"
      />
    </div>

    <!-- ── Frame picker ────────────────────────────────────────────── -->
    <div class="mintTimeSection">
      <label class="mintTimeLabel">Frame</label>
      <div class="frameSwatchRow">
        <button
          v-for="f in frames"
          :key="f.id"
          class="frameSwatch"
          :class="{ frameSwatchSelected: f.id === frameId }"
          @click="frameId = f.id"
        >
          <span class="frameSwatchInner" v-html="f.svg"></span>
          <span class="frameSwatchName">{{ f.name }}</span>
        </button>
      </div>
    </div>

    <!-- ── Capsule contents ────────────────────────────────────────── -->
    <div class="mintTimeSection">
      <label class="mintTimeLabel">
        Note ({{ text.length }} / 280)
      </label>
      <textarea
        v-model="text"
        maxlength="280"
        rows="3"
        class="mintTimeText"
        placeholder="A message for the future…"
      ></textarea>

      <label class="mintTimeLabel">Image (optional)</label>
      <input
        type="file"
        accept="image/*"
        @change="onImageChange"
        class="mintTimeFile"
      />
      <div v-if="imageWarning" class="mintTimeWarn">{{ imageWarning }}</div>
    </div>

    <!-- ── Live preview ────────────────────────────────────────────── -->
    <div class="mintTimePreview">
      <div class="previewFrame" v-html="selectedFrame.svg"></div>
      <div class="previewContent" :style="{ color: selectedFrame.textOn }">
        <div class="previewTimestamp">{{ humanTimestamp }}</div>
        <div class="previewRange" v-if="duration > 1">
          → {{ humanEndTimestamp }} ({{ duration }} min)
        </div>
        <div v-if="imagePreviewUrl" class="previewImageWrap">
          <img :src="imagePreviewUrl" class="previewImage" alt="capsule"/>
        </div>
        <div class="previewText">{{ text || '(your note here)' }}</div>
      </div>
    </div>

    <!-- ── Mint controls ───────────────────────────────────────────── -->
    <div class="rowFlex mintTimeMintRow">
      <div class="mintTimePrice">
        Total: {{ totalPriceTez.toFixed(2) }} ꜩ
        <span class="mintTimePriceSub">({{ pricePerMinuteTez.toFixed(2) }} × {{ duration }})</span>
      </div>
      <button
        class="actionButton"
        :disabled="minting || !canMint"
        @click="mintCapsule"
      >
        {{ minting ? 'Minting…' : 'Mint capsule' }}
      </button>
    </div>

    <div class="gameInfo mintTimeStatus">{{ blockChainStatus }}</div>
  </div>
</template>

<script>
import { MINT_TIME_CONTRACT_ADDRESS } from '../constants'
import { FRAMES, FRAME_BY_ID } from '../assets/mintTimeFrames'
import { pinImage, ipfsConfigured } from '../services/ipfs'
import { getContractStorage } from '../services/tzkt'

const MS_PER_MIN = 60_000

// Default fallback price if contract storage isn't reachable yet
// (placeholder address, RPC down, etc.). Mirrors the SmartPy default
// in smart_contract_mint_time.py: 500000 mutez = 0.5 ꜩ.
const FALLBACK_PRICE_MUTEZ = 500_000

function currentUtcMinute() {
  return Math.floor(Date.now() / MS_PER_MIN)
}

// Convert an HTML <input type="datetime-local"> value (no timezone info,
// always read as local time) into a UTC epoch minute. The user is picking
// a "wall clock UTC moment", so we re-interpret the picker's components as
// UTC rather than letting the browser apply its local offset.
function inputToUtcMinute(value) {
  if (!value) return currentUtcMinute()
  const [datePart, timePart] = value.split('T')
  const [y, m, d] = datePart.split('-').map(Number)
  const [hh, mm] = (timePart || '00:00').split(':').map(Number)
  const ms = Date.UTC(y, m - 1, d, hh, mm, 0)
  return Math.floor(ms / MS_PER_MIN)
}

function utcMinuteToInput(minute) {
  const d = new Date(minute * MS_PER_MIN)
  const pad = (n) => String(n).padStart(2, '0')
  return (
    `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}` +
    `T${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}`
  )
}

function formatMinute(minute) {
  const d = new Date(minute * MS_PER_MIN)
  return d.toISOString().slice(0, 16).replace('T', ' ') + ' UTC'
}

export default {
  name: 'MintTime',
  props: ['socket', 'wallet', 'tezos'],
  data() {
    const startMin = currentUtcMinute()
    return {
      frames: FRAMES,
      startInput: utcMinuteToInput(startMin),
      duration: 1,
      frameId: 0,
      text: '',
      imageFile: null,
      imagePreviewUrl: '',
      imageWarning: '',
      minting: false,
      blockChainStatus: ipfsConfigured()
        ? 'Pick a minute, a frame, and your capsule contents — then mint.'
        : 'Dev mode: VUE_APP_PINATA_JWT is not set, so images are NOT being pinned to IPFS. Mint will still complete on-chain with a placeholder ref.',
      pricePerMinuteMutez: FALLBACK_PRICE_MUTEZ,
    }
  },
  computed: {
    startMinute() {
      return inputToUtcMinute(this.startInput)
    },
    endMinute() {
      return this.startMinute + this.duration - 1
    },
    humanTimestamp() {
      return formatMinute(this.startMinute)
    },
    humanEndTimestamp() {
      return formatMinute(this.endMinute)
    },
    selectedFrame() {
      return FRAME_BY_ID[this.frameId] || FRAMES[0]
    },
    pricePerMinuteTez() {
      return this.pricePerMinuteMutez / 1_000_000
    },
    totalPriceMutez() {
      return this.pricePerMinuteMutez * this.duration
    },
    totalPriceTez() {
      return this.totalPriceMutez / 1_000_000
    },
    canMint() {
      return this.duration >= 1 && this.duration <= 15 && this.startMinute > 0
    },
  },
  async mounted() {
    await this.refreshPrice()
  },
  methods: {
    setStartToNow() {
      this.startInput = utcMinuteToInput(currentUtcMinute())
    },

    onImageChange(e) {
      const file = e.target.files && e.target.files[0]
      this.imageWarning = ''
      if (!file) {
        this.imageFile = null
        this.imagePreviewUrl = ''
        return
      }
      // 5 MB ceiling — beyond that, Pinata starts charging serious bandwidth
      // and the preview <img> chokes. Loud rejection is friendlier than a
      // silent half-broken mint.
      if (file.size > 5 * 1024 * 1024) {
        this.imageWarning = 'Image too large (max 5 MB).'
        this.imageFile = null
        this.imagePreviewUrl = ''
        return
      }
      this.imageFile = file
      this.imagePreviewUrl = URL.createObjectURL(file)
    },

    async refreshPrice() {
      try {
        const storage = await getContractStorage(MINT_TIME_CONTRACT_ADDRESS)
        if (storage && storage.price_per_minute_mutez !== undefined) {
          // TzKT returns mutez as either a number or a string depending on
          // size; coerce defensively.
          const p = Number(storage.price_per_minute_mutez)
          if (Number.isFinite(p) && p > 0) this.pricePerMinuteMutez = p
        }
      } catch (e) {
        // Contract not deployed yet on this network, or RPC hiccup. Fall
        // back to the bundled default — UI still works.
        console.warn('[MintTime] refreshPrice failed:', e?.message || e)
      }
    },

    useWalletProvider() {
      if (this.tezos && this.wallet) {
        this.tezos.setWalletProvider(this.wallet)
      }
    },

    async mintCapsule() {
      if (this.minting) return
      this.minting = true
      try {
        if (!this.wallet) {
          this.blockChainStatus = 'Wallet not initialised — refresh the page.'
          return
        }
        let activeAccount
        try {
          activeAccount = await this.wallet.client.getActiveAccount()
        } catch (e) {
          this.blockChainStatus = 'Could not read wallet — Reset wallet at top.'
          console.error('mintCapsule: getActiveAccount failed:', e)
          return
        }
        if (!activeAccount) {
          this.blockChainStatus = 'Connect your wallet first (top of page).'
          return
        }

        // 1. Pin the image (or get a local-* placeholder in dev mode).
        let imageRef = ''
        if (this.imageFile) {
          this.blockChainStatus = 'Pinning image to IPFS…'
          try {
            imageRef = await pinImage(this.imageFile)
          } catch (e) {
            this.blockChainStatus = `IPFS pin failed: ${(e?.message || String(e)).slice(0, 140)}`
            console.error('mintCapsule: pin failed', e)
            return
          }
        }

        // 2. Build mint params + price.
        const params = {
          start_minute: this.startMinute,
          duration: this.duration,
          frame_id: this.frameId,
          text: this.text,
          image_ipfs: imageRef,
        }
        const amountTezStr = this.totalPriceTez.toFixed(6)
        console.log('[MintTime] mint with', params, 'amount', amountTezStr)

        this.blockChainStatus = `Submitting mint (${amountTezStr} ꜩ)…`
        this.useWalletProvider()

        const contract = await this.tezos.wallet.at(MINT_TIME_CONTRACT_ADDRESS)
        const op = await contract.methodsObject
          .mint(params)
          .send({ amount: amountTezStr })
        this.blockChainStatus =
          `Mint broadcast — waiting for confirmation (${op.opHash.slice(0, 12)}…)`
        console.log('[MintTime] op injected', op.opHash)
        await op.confirmation()
        this.blockChainStatus =
          `Minted! Capsule for ${this.humanTimestamp} is yours. Op ${op.opHash.slice(0, 12)}…`
      } catch (err) {
        const msg = err?.message || String(err)
        console.error('mintCapsule: failed', err)
        if (/aborted|cancel|rejected/i.test(msg)) {
          this.blockChainStatus = 'Mint cancelled in wallet.'
        } else if (/insufficient|balance/i.test(msg)) {
          this.blockChainStatus =
            'Insufficient balance — fund the wallet at the shadownet faucet.'
        } else if (/MinuteTaken/i.test(msg)) {
          this.blockChainStatus =
            'One of those minutes is already claimed — try a different start time.'
        } else if (/WrongPayment/i.test(msg)) {
          this.blockChainStatus =
            'Price changed on-chain — reload and try again.'
        } else {
          this.blockChainStatus = `Mint failed: ${msg.slice(0, 160)}`
        }
      } finally {
        this.minting = false
      }
    },
  },
  beforeUnmount() {
    if (this.imagePreviewUrl) URL.revokeObjectURL(this.imagePreviewUrl)
  },
}
</script>

<style scoped>
.mintTimeSection {
  width: 100%;
  max-width: 480px;
  margin: 12px auto;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.mintTimeLabel {
  font-size: 13px;
  color: var(--ad-text-2, #c2c2cc);
  letter-spacing: 0.04em;
  text-transform: uppercase;
}
.mintTimeInput,
.mintTimeText,
.mintTimeFile {
  background: var(--ad-bg-elev-1, #1a1a22);
  border: 1px solid var(--ad-border-faint, #2c2c3a);
  border-radius: var(--ad-r-md, 8px);
  color: var(--ad-text-1, #f0f0f5);
  padding: 8px 10px;
  font-size: 14px;
  font-family: inherit;
}
.mintTimeText {
  resize: vertical;
  min-height: 64px;
}
.mintTimeSlider {
  width: 100%;
  accent-color: var(--ad-accent, #d4a73a);
}
.mintTimeMinute {
  font-size: 12px;
  color: var(--ad-text-3, #8a8a96);
  font-variant-numeric: tabular-nums;
}
.mintTimeWarn {
  color: #ff7a7a;
  font-size: 12px;
}

.frameSwatchRow {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 10px;
}
.frameSwatch {
  background: transparent;
  border: 2px solid var(--ad-border-faint, #2c2c3a);
  border-radius: var(--ad-r-md, 8px);
  padding: 6px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  cursor: pointer;
  transition: border-color 0.15s ease, transform 0.15s ease;
}
.frameSwatch:hover { transform: translateY(-2px); }
.frameSwatchSelected {
  border-color: var(--ad-accent, #d4a73a);
  box-shadow: 0 0 0 2px rgba(212, 167, 58, 0.25);
}
.frameSwatchInner {
  display: block;
  width: 100%;
  aspect-ratio: 1 / 1;
}
.frameSwatchInner :deep(svg) {
  width: 100%;
  height: 100%;
  display: block;
}
.frameSwatchName {
  font-size: 11px;
  color: var(--ad-text-2, #c2c2cc);
}

.mintTimePreview {
  position: relative;
  width: 100%;
  max-width: 400px;
  aspect-ratio: 1 / 1;
  margin: 20px auto;
}
.previewFrame {
  position: absolute;
  inset: 0;
}
.previewFrame :deep(svg) {
  width: 100%;
  height: 100%;
  display: block;
}
.previewContent {
  position: absolute;
  /* Inner safe area on 400x400 viewBox is roughly 60-340 in both axes,
     i.e. 15% inset. Polaroid is closer to the top but the bottom caption
     band still leaves enough room — accept a small layout compromise to
     keep one inner box across all six frames. */
  inset: 15%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: flex-start;
  text-align: center;
  gap: 6px;
  padding: 8px;
  overflow: hidden;
}
.previewTimestamp {
  font-size: 15px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}
.previewRange {
  font-size: 11px;
  opacity: 0.8;
  font-variant-numeric: tabular-nums;
}
.previewImageWrap {
  width: 70%;
  flex: 0 0 auto;
}
.previewImage {
  width: 100%;
  max-height: 140px;
  object-fit: cover;
  display: block;
  border-radius: 4px;
}
.previewText {
  font-size: 12px;
  line-height: 1.3;
  word-break: break-word;
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 4;
  -webkit-box-orient: vertical;
}

.mintTimeMintRow {
  margin: 12px auto;
  max-width: 480px;
  width: 100%;
  justify-content: space-between;
  align-items: center;
}
.mintTimePrice {
  font-size: 16px;
  font-weight: 600;
  color: var(--ad-text-1, #f0f0f5);
  font-variant-numeric: tabular-nums;
}
.mintTimePriceSub {
  font-size: 12px;
  font-weight: 400;
  color: var(--ad-text-3, #8a8a96);
  margin-left: 4px;
}
.mintTimeStatus {
  margin-top: 10px;
  font-size: 13px;
}
</style>
