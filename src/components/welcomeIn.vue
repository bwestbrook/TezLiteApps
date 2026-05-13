<script>
import { TILE_APPS } from '../apps/registry'

// Tabs are derived from app `tag` values. The order here is the order they
// render in. "all" is a synthetic tab that doesn't filter.
const TABS = [
  { id: 'all',        label: 'All' },
  { id: 'game',       label: 'Games' },
  { id: 'collection', label: 'Collection' },
  { id: 'tools',      label: 'Tools' },
]

export default {
  name: 'welcomeIn',
  props: ['wallet', 'socket', 'tezos'],
  data() {
    return {
      tiles: TILE_APPS,
      walletAddress: '',
      tabs: TABS,
      activeTab: 'game', // open on Games — that's where most users are headed
    }
  },
  computed: {
    visibleTiles() {
      if (this.activeTab === 'all') return this.tiles
      return this.tiles.filter((t) => t.tag === this.activeTab)
    },
    tabCounts() {
      // Pre-compute counts per tab for the badge UI.
      const out = { all: this.tiles.length }
      for (const t of this.tiles) out[t.tag] = (out[t.tag] || 0) + 1
      return out
    },
  },
  created() {
    this.socket.on('newWallet', (newWallet) => {
      this.walletAddress = newWallet
    })
  },
  methods: {
    selectGame(id) {
      this.socket.emit('selectGame', id)
    },
    setTab(id) {
      this.activeTab = id
    },
  },
}
</script>

<template>
  <div class="welcomeRoot">
    <!-- Hero header: one liner so the rest of the screen is the lobby itself -->
    <div class="welcomeHero">
      <div class="welcomeEyebrow">TXL · LOBBY</div>
      <div class="welcomeTitle">Welcome.</div>
      <div class="welcomeSub">Pick a game, browse the collection, or check the tools.</div>
    </div>

    <!-- Tabs row -->
    <div class="welcomeTabs" role="tablist">
      <button
        v-for="tab in tabs"
        :key="tab.id"
        :class="['welcomeTab', activeTab === tab.id ? 'welcomeTab--active' : '']"
        role="tab"
        :aria-selected="activeTab === tab.id"
        @click="setTab(tab.id)"
      >
        <span class="welcomeTabLabel">{{ tab.label }}</span>
        <span class="welcomeTabCount">{{ tabCounts[tab.id] || 0 }}</span>
      </button>
    </div>

    <!-- Single-column tile list -->
    <div class="welcomeList">
      <div
        v-for="tile in visibleTiles"
        :key="tile.id"
        class="welcomeCard"
        @click="selectGame(tile.id)"
        role="button"
        tabindex="0"
        @keydown.enter="selectGame(tile.id)"
      >
        <div class="welcomeCardImg">
          <img :src="tile.image" :alt="tile.name" draggable="false"/>
        </div>
        <div class="welcomeCardBody">
          <div class="welcomeCardTagRow">
            <span :class="['welcomeCardTag', `welcomeCardTag--${tile.tag}`]">
              {{ tile.tag }}
            </span>
          </div>
          <div class="welcomeCardName">{{ tile.name }}</div>
          <div class="welcomeCardBlurb">{{ tile.blurb }}</div>
          <div class="welcomeCardCta">Open <span aria-hidden="true">›</span></div>
        </div>
      </div>

      <div v-if="visibleTiles.length === 0" class="welcomeEmpty">
        Nothing in this section yet.
      </div>
    </div>
  </div>
</template>

<style scoped>
.welcomeRoot {
  font-family: 'EB Garamond';
  color: #efeae2;
  padding: 8px 4px 12px;
}

/* ─── Hero ───────────────────────────────────────────────────────────── */
.welcomeHero {
  padding: 14px 14px 12px;
  margin-bottom: 12px;
  border-radius: 12px;
  background:
    radial-gradient(ellipse at 80% 20%, rgba(212, 162, 78, 0.15) 0%, transparent 60%),
    linear-gradient(135deg, #190857 0%, #07041e 100%);
  box-shadow:
    inset 0 0 0 1px rgba(255, 255, 255, 0.06),
    0 6px 16px rgba(0, 0, 0, 0.4);
}
.welcomeEyebrow {
  font-size: 10px;
  letter-spacing: 5px;
  font-weight: 700;
  color: rgba(245, 196, 81, 0.75);
  margin-bottom: 4px;
}
.welcomeTitle {
  font-size: clamp(22px, 5vw, 32px);
  font-weight: 700;
  color: #fff;
  line-height: 1;
  margin-bottom: 6px;
}
.welcomeSub {
  font-size: 13px;
  color: rgba(255, 255, 255, 0.78);
  line-height: 1.4;
}

/* ─── Tabs ───────────────────────────────────────────────────────────── */
.welcomeTabs {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  padding: 4px;
  margin-bottom: 12px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.06);
}
.welcomeTab {
  flex: 1 1 auto;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 8px 12px;
  border: 1px solid transparent;
  border-radius: 7px;
  background: transparent;
  color: rgba(255, 255, 255, 0.65);
  font-family: 'EB Garamond';
  font-size: 13px;
  letter-spacing: 1px;
  cursor: pointer;
  transition: background 0.18s ease, color 0.18s ease, border-color 0.18s ease;
}
.welcomeTab:hover {
  color: #fff;
  background: rgba(255, 255, 255, 0.04);
}
.welcomeTab--active {
  background: linear-gradient(135deg, rgba(245, 196, 81, 0.18), rgba(212, 162, 78, 0.08));
  border-color: rgba(245, 196, 81, 0.5);
  color: #f5c451;
  font-weight: 700;
}
.welcomeTabCount {
  font-size: 10px;
  font-weight: 700;
  padding: 1px 6px;
  border-radius: 8px;
  background: rgba(0, 0, 0, 0.35);
  color: inherit;
  letter-spacing: 0;
}

/* ─── Tile list (single column) ──────────────────────────────────────── */
.welcomeList {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.welcomeCard {
  display: flex;
  flex-direction: row;
  align-items: stretch;
  gap: 12px;
  padding: 10px;
  border-radius: 10px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  background: rgba(255, 255, 255, 0.03);
  cursor: pointer;
  transition: transform 0.15s ease, border-color 0.15s ease, background 0.15s ease,
              box-shadow 0.2s ease;
  /* Stagger-fade as the list re-renders. JS-free, purely CSS. */
  animation: adFadeUp 0.35s ease-out backwards;
}
.welcomeCard:nth-child(1) { animation-delay: 0.00s; }
.welcomeCard:nth-child(2) { animation-delay: 0.04s; }
.welcomeCard:nth-child(3) { animation-delay: 0.08s; }
.welcomeCard:nth-child(4) { animation-delay: 0.12s; }
.welcomeCard:nth-child(5) { animation-delay: 0.16s; }
.welcomeCard:nth-child(6) { animation-delay: 0.20s; }
.welcomeCard:nth-child(7) { animation-delay: 0.24s; }
.welcomeCard:nth-child(8) { animation-delay: 0.28s; }
.welcomeCard:nth-child(9) { animation-delay: 0.32s; }
.welcomeCard:nth-child(10) { animation-delay: 0.36s; }
.welcomeCard:hover,
.welcomeCard:focus-visible {
  transform: translateY(-2px);
  border-color: rgba(245, 196, 81, 0.55);
  background: rgba(255, 255, 255, 0.05);
  box-shadow: 0 6px 22px rgba(0, 0, 0, 0.4), 0 0 0 1px rgba(245, 196, 81, 0.25);
  outline: none;
}
.welcomeCardImg {
  flex: 0 0 38%;
  max-width: 200px;
  aspect-ratio: 5 / 3;
  border-radius: 6px;
  overflow: hidden;
  background: #0a0a0a;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.06);
}
.welcomeCardImg img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
  user-select: none;
  -webkit-user-drag: none;
}
.welcomeCardBody {
  flex: 1;
  display: flex;
  flex-direction: column;
  justify-content: center;
  min-width: 0;
}
.welcomeCardTagRow { margin-bottom: 4px; }
.welcomeCardTag {
  display: inline-block;
  font-size: 9px;
  letter-spacing: 2px;
  padding: 1px 7px;
  border-radius: 8px;
  text-transform: uppercase;
  font-weight: 700;
  background: rgba(255, 255, 255, 0.08);
  color: rgba(255, 255, 255, 0.7);
}
.welcomeCardTag--game       { background: rgba(245, 196, 81, 0.18); color: #f5c451; }
.welcomeCardTag--collection { background: rgba(196, 82, 79, 0.18);  color: #ff908d; }
.welcomeCardTag--tools      { background: rgba(75, 130, 240, 0.18); color: #9ec0ff; }
.welcomeCardName {
  font-size: 16px;
  font-weight: 700;
  color: #fff;
  margin-bottom: 2px;
}
.welcomeCardBlurb {
  font-size: 12.5px;
  line-height: 1.4;
  color: rgba(255, 255, 255, 0.72);
  margin-bottom: 6px;
}
.welcomeCardCta {
  font-size: 11px;
  letter-spacing: 2px;
  font-weight: 700;
  color: #f5c451;
  text-transform: uppercase;
}
.welcomeCardCta span {
  display: inline-block;
  margin-left: 4px;
  transition: transform 0.2s ease;
}
.welcomeCard:hover .welcomeCardCta span {
  transform: translateX(3px);
}

.welcomeEmpty {
  padding: 20px;
  text-align: center;
  color: rgba(255, 255, 255, 0.55);
  font-size: 13px;
  border: 1px dashed rgba(255, 255, 255, 0.12);
  border-radius: 8px;
}

/* ─── Mobile: stack the card vertically so the image is hero-sized ─── */
@media (max-width: 480px) {
  .welcomeCard { flex-direction: column; }
  .welcomeCardImg {
    flex: 0 0 auto;
    max-width: 100%;
    width: 100%;
  }
}
</style>
