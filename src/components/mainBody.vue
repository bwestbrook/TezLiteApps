<script>
// Registry-driven nav. Adding a new app = one entry in src/apps/registry.js.
import { APPS, HOME_APP, NAV_APPS, APP_BY_ID } from '../apps/registry'
import {
  NETWORK,
  setNetwork,
  getBeaconNetwork,
  TXL_CONTRACT_ADDRESS,
  BLOCKCHAIN_ENABLED,
} from '../constants'
import { getContractStorage } from '../services/tzkt'

export default {
  name: 'mainBody',
  // We register every app's component up-front so <component :is> can resolve.
  components: Object.fromEntries(APPS.map((a) => [a.id, a.component])),
  props: ['wallet', 'socket', 'tezos'],
  data() {
    return {
      APPS,
      NAV_APPS,
      HOME_APP,
      NETWORK,
      activeView: HOME_APP.id,
      walletAddress: 'SYNC WALLET',
      // TXL manager contract state, polled from storage so the holder pool
      // total + the connected wallet's claimable share show on every page.
      txlPoolValue: 0,
      txlShare: 0,
      txlOwnsNft: false,
      txlCashStatus: '',
      // Flashes the "Unclaimed" chip green for ~1s when the pool grows (a bet
      // somewhere sent its holder fee in). txlPoolSeeded guards the first poll
      // so the initial 0 → real-value jump doesn't trigger a flash.
      txlPoolFlash: false,
      txlPoolSeeded: false,
    }
  },
  computed: {
    activeComponent() {
      return APP_BY_ID[this.activeView]?.component || HOME_APP.component
    },
    // The carousel order: TXL Manager (home) first, then every nav app.
    // Single source of truth so the template loop and scroll-into-view
    // logic stay in sync.
    navTiles() {
      return [this.HOME_APP, ...this.NAV_APPS]
    },
  },
  created() {
    this.socket.on('newWallet', (newWallet) => {
      this.walletAddress = newWallet
    })
    this.socket.on('selectGame', (game) => {
      this.selectGame(game)
    })
  },
  mounted() {
    // Poll the TXL manager contract for the holder pool total and — when a
    // wallet is connected — that wallet's claimable share. Lives here (not in
    // browseNFTs) so the Cash Out button + stats appear on every page.
    this.refreshTxlContract()
    if (BLOCKCHAIN_ENABLED) {
      this.txlPollInterval = setInterval(() => this.refreshTxlContract(), 30000)
    }
  },
  beforeUnmount() {
    if (this.txlPollInterval) clearInterval(this.txlPollInterval)
    if (this.txlFlashTimeout) clearTimeout(this.txlFlashTimeout)
  },
  methods: {
    selectGame(id) {
      // Accept legacy 'welcome' alias.
      const target = id === 'welcome' ? HOME_APP.id : id
      if (!APP_BY_ID[target]) return
      this.activeView = target
      // Special hook: TezTacToe wants this every time it becomes active.
      if (target === 'tezTacToe') {
        this.socket.emit('updatePlayerControl')
      }
      this.$nextTick(() => this.scrollActiveIntoView())
    },
    // Scroll the carousel strip by ±~70% of its visible width per click.
    // Smooth-scroll is browser-native; no JS easing needed.
    scrollNav(dir) {
      const strip = this.$refs.navStrip
      if (!strip) return
      const delta = Math.max(120, Math.round(strip.clientWidth * 0.7))
      strip.scrollBy({ left: dir * delta, behavior: 'smooth' })
    },
    // Keep the selected pill in view when nav changes via socket / keyboard.
    scrollActiveIntoView() {
      const strip = this.$refs.navStrip
      if (!strip) return
      const active = strip.querySelector('.navPill--active')
      if (!active) return
      const stripRect = strip.getBoundingClientRect()
      const pillRect = active.getBoundingClientRect()
      if (pillRect.left < stripRect.left || pillRect.right > stripRect.right) {
        active.scrollIntoView({ behavior: 'smooth', inline: 'center', block: 'nearest' })
      }
    },
    async toggleWallet() {
      // Currently connected? Disconnect.
      try {
        const activeAccount = await this.wallet.client.getActiveAccount()
        if (activeAccount) {
          await this.wallet.clearActiveAccount()
          this.walletAddress = 'SYNC WALLET'
          return
        }
      } catch (err) {
        console.warn('getActiveAccount failed (continuing to connect):', err?.message)
      }

      // Not connected — request permissions on the *current* network.
      // Passing `network` explicitly matters: without it Beacon falls back
      // to its built-in default (mainnet) which mismatches our CUSTOM
      // shadownet config and causes a slow re-handshake.
      const network = getBeaconNetwork()
      this.walletAddress = 'CONNECTING…'
      try {
        await this.wallet.client.requestPermissions({ network })
        this.tezos.setWalletProvider(this.wallet)
        // ACTIVE_ACCOUNT_SET event handler in App.vue will update the badge
      } catch (err) {
        // User-visible message. Most common failure modes: relay DNS issue
        // (we now mitigate via custom matrixNodes), user closed the popup,
        // wallet extension locked, or the wallet not supporting shadownet.
        const msg = err?.message || String(err)
        const name = err?.name || ''
        const isAborted = /aborted|cancel|denied/i.test(msg)
        const isNetworkUnsupported =
          name === 'NetworkNotSupportedBeaconError' ||
          /network.*not.*support|not.*support.*network|network_not_supported/i.test(msg)
        const isNetwork = /timeout|network|relay|resolve|ENOTFOUND|ERR_NAME/i.test(msg)
        if (isAborted) {
          this.walletAddress = 'SYNC WALLET (cancelled)'
        } else if (isNetworkUnsupported) {
          // Kukai's hosted web wallet doesn't implement shadownet. Temple
          // (extension) does — steer the user there.
          this.walletAddress = 'SYNC WALLET (use Temple for shadownet)'
          console.warn(
            'Wallet rejected shadownet. Kukai\'s web wallet does not support ' +
            'it — use Temple (browser extension), which connects to custom / ' +
            'test networks.',
            err,
          )
        } else if (isNetwork) {
          this.walletAddress = 'SYNC WALLET (relay error)'
          console.warn(
            'Beacon relay failed. If this persists, the Matrix relay list in ' +
            'constants.js may need refresh. See https://docs.walletbeacon.io',
            err,
          )
        } else {
          this.walletAddress = 'SYNC WALLET (failed)'
          console.warn('Wallet connect failed:', err)
        }
      }
    },
    /**
     * Nuke ALL Beacon storage and reload. Use this when Beacon's relay
     * connection is wedged — it forces a completely fresh handshake.
     * More aggressive than clearStaleBeaconStorage() (which only removes
     * known-bad-host entries).
     */
    resetWallet() {
      try {
        const ls = window.localStorage
        const toRemove = []
        for (let i = 0; i < ls.length; i++) {
          const k = ls.key(i)
          if (k && k.startsWith('beacon')) toRemove.push(k)
        }
        for (const k of toRemove) ls.removeItem(k)
        // Also clear the beacon IndexedDB if present
        if (window.indexedDB && window.indexedDB.deleteDatabase) {
          try { window.indexedDB.deleteDatabase('beacon') } catch (_e) { /* noop */ }
          try { window.indexedDB.deleteDatabase('beacon-sdk') } catch (_e) { /* noop */ }
        }
      } catch (e) {
        console.warn('resetWallet cleanup failed:', e)
      }
      window.location.reload()
    },
    toggleNetwork() {
      const next = this.NETWORK === 'mainnet' ? 'shadownet' : 'mainnet'
      // Confirm because reload will drop any in-flight wallet permissions.
      const ok = typeof window !== 'undefined'
        ? window.confirm(
            `Switch to ${next}?\n\n` +
            `The page will reload and your wallet will need to be reconnected. ` +
            `Contract addresses and RPC endpoints will swap to ${next}'s.`
          )
        : true
      if (ok) setNetwork(next)
    },
    // Poll the TXL manager contract: the holder pool total (storage
    // totalRewards), and — if a wallet is connected — that wallet's claimable
    // share, summed from the contract's own idLookUp owner records (exactly
    // what payTxlHolder pays out, so it matches the Cash Out button).
    async refreshTxlContract() {
      const storage = await getContractStorage(TXL_CONTRACT_ADDRESS)
      if (!storage) return
      const nextPool = Number(storage.totalRewards || 0) / 1e6
      // A bet landed its holder fee — flash the chip green. Skip the very
      // first poll (0 → real value isn't a "bet was placed").
      if (this.txlPoolSeeded && nextPool > this.txlPoolValue) this.flashTxlPool()
      this.txlPoolValue = nextPool
      this.txlPoolSeeded = true

      const activeAccount = await this.wallet?.client?.getActiveAccount?.()
      const address = activeAccount?.address
      if (!address) {
        this.txlOwnsNft = false
        this.txlShare = 0
        return
      }
      let shareMutez = 0
      let owns = false
      for (const entry of Object.values(storage.idLookUp || {})) {
        if (entry?.owner === address) {
          owns = true
          shareMutez += Number(entry.balance || 0)
        }
      }
      this.txlOwnsNft = owns
      this.txlShare = shareMutez / 1e6
    },
    // Claim this wallet's accrued TXL holder earnings. payTxlHolder zeroes the
    // per-NFT balances the contract attributes to the sender and sends the sum.
    async payNftHolderBC() {
      const activeAccount = await this.wallet.client.getActiveAccount()
      if (!activeAccount) {
        this.txlCashStatus = 'Sync a wallet first'
        return
      }
      this.txlCashStatus = 'Cashing out…'
      this.tezos.setWalletProvider(this.wallet)
      await this.tezos.wallet
        .at(TXL_CONTRACT_ADDRESS)
        .then((contract) => contract.methodsObject.payTxlHolder().send())
        .then((op) => op.confirmation().then(() => op.opHash))
        .then(() => {
          this.txlCashStatus = 'Cashed out!'
          // Balances were just zeroed on-chain — repoll so the pool total
          // and "Your Share" reflect the payout.
          this.refreshTxlContract()
        })
        .catch((error) => {
          console.error('payNftHolderBC failed:', error)
          this.txlCashStatus = 'Cash out failed'
        })
    },
    // Pulse the "Unclaimed" chip green for ~1s. Re-arm the timer each call so
    // back-to-back increases don't leave it stuck on.
    flashTxlPool() {
      this.txlPoolFlash = true
      if (this.txlFlashTimeout) clearTimeout(this.txlFlashTimeout)
      this.txlFlashTimeout = setTimeout(() => { this.txlPoolFlash = false }, 1000)
    },
  },
}
</script>

<template>
  <div class="mainBody">
    <div class="centerBody">
      <div class="gameManagement">
        <div class="rowFlex">
          <div class="actionButton" @click="toggleWallet">{{ walletAddress }}</div>
          <div class="actionButton" @click="payNftHolderBC"> Cash Out TXL Earnings </div>
          <div :class="['txlRank', txlPoolFlash ? 'txlRank--flash' : '']"> Unclaimed: {{ txlPoolValue.toFixed(3) }} ꜩ </div>
          <div
            v-if="walletAddress.includes('error') || walletAddress.includes('failed')"
            class="actionButtonHelp walletReset"
            @click="resetWallet"
            title="Wipe Beacon's cached state and start fresh — fixes stuck connect handshakes"
          >Reset wallet</div>
          <div
            :class="[
              'networkBadge',
              'networkBadge--toggle',
              NETWORK === 'mainnet' ? 'badgeProd' : 'badgeTest',
            ]"
            @click="toggleNetwork"
            :title="'Click to switch to ' + (NETWORK === 'mainnet' ? 'shadownet' : 'mainnet')"
            role="button"
            tabindex="0"
            @keydown.enter="toggleNetwork"
          >
            <span class="networkBadge__dot" aria-hidden="true"></span>
            {{ NETWORK }}
            <span class="networkBadge__arrow" aria-hidden="true">⇄</span>
          </div>
        </div>

        <div class="rowFlex" v-if="txlOwnsNft || txlCashStatus">
          <div class="txlRank" v-if="txlOwnsNft"> Your Claimable Share: {{ txlShare.toFixed(6) }} ꜩ </div>
          <div class="txlRank" v-if="txlCashStatus"> {{ txlCashStatus }} </div>
        </div>

        <div class="navCarousel" role="tablist" aria-label="Apps">
          <button
            type="button"
            class="navArrow navArrow--left"
            aria-label="Scroll apps left"
            @click="scrollNav(-1)"
          >‹</button>
          <div class="navStrip" ref="navStrip">
            <button
              v-for="app in navTiles"
              :key="app.id"
              type="button"
              role="tab"
              :aria-selected="activeView === app.id"
              :class="['navPill', activeView === app.id ? 'navPill--active' : '']"
              @click="selectGame(app.id)"
            >
              {{ app.name }}
            </button>
          </div>
          <button
            type="button"
            class="navArrow navArrow--right"
            aria-label="Scroll apps right"
            @click="scrollNav(1)"
          >›</button>
        </div>

        <!-- The wrapper div is load-bearing: <Transition mode="out-in">
             needs a single element root to track enter/leave. Some app
             components (e.g. tezTacToe) have multi-root templates, which
             leaves the transition unable to fire afterLeave — the next
             view never mounts and the pane goes blank. Wrapping the
             dynamic component guarantees one element root regardless. -->
        <transition name="view" mode="out-in">
          <div :key="activeView" class="viewSlot">
            <component
              :is="activeComponent"
              :socket="socket"
              :wallet="wallet"
              :tezos="tezos"
            />
          </div>
        </transition>
      </div>
    </div>
    <div class="label">
      Made with love by @jamin_b on telegram/discord and @jaminb12 on X... shhh all games on
      shadownet
    </div>
  </div>
</template>

<style>
/* ─── Global shared classes ──────────────────────────────────────────
   Crypto/web3 dark aesthetic. Tokens live in App.vue's :root. Every
   game component inherits these classes via mainBody — keep the names
   stable so we don't have to touch the children. */

.mainBody {
  margin: auto;
  padding: 14px 14px 20px;
  max-width: 720px;
  display: flex;
  flex-direction: column;
  border-radius: var(--ad-r-lg);
  background:
    radial-gradient(ellipse at 50% 0%, rgba(124, 58, 237, 0.10) 0%, transparent 60%),
    var(--ad-bg-base);
  border: 1px solid var(--ad-border-faint);
  box-shadow: var(--ad-shadow-card);
  color: var(--ad-text-1);
  font-family: var(--ad-font-body);
}
.centerBody {
  margin: auto;
  padding: 4px;
  max-width: 700px;
  display: flex;
  flex-direction: column;
  color: var(--ad-text-1);
  font-family: var(--ad-font-body);
}
.gameManagement {
  justify-content: center;
  width: 100%;
  flex: 1;
  cursor: default;
}
/* Single-element root for <Transition mode="out-in"> — see template. */
.viewSlot {
  width: 100%;
}

.rowFlex {
  display: flex;
  flex-wrap: wrap;
  width: 100%;
  gap: 6px;
}
.gameCenter {
  align-content: center;
  margin: auto;
  flex: 1;
}

/* ─── Surface chips (info / status / score) ──────────────────────── */
.gameInfo {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 8px 12px;
  margin: 2px 0;
  border-radius: var(--ad-r-md);
  background: var(--ad-bg-elev-1);
  border: 1px solid var(--ad-border-soft);
  cursor: default;
  font-family: var(--ad-font-body);
  font-size: 13px;
  color: var(--ad-text-1);
  flex: 1;
  letter-spacing: 0.01em;
}
.gameSelect {
  margin: 2px 0;
  padding: 8px 12px;
  border-radius: var(--ad-r-md);
  background: var(--ad-bg-elev-1);
  border: 1px solid var(--ad-border-soft);
  color: var(--ad-text-1);
  font-family: var(--ad-font-body);
  font-size: 13px;
  flex: 1;
  cursor: pointer;
  transition: background 0.15s ease, border-color 0.15s ease;
}
.gameSelect:hover {
  background: var(--ad-bg-elev-2);
  border-color: var(--ad-border-mid);
}
.txlRank {
  align-content: center;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 10px 12px;
  margin: 2px 0;
  border-radius: var(--ad-r-md);
  background: var(--ad-bg-elev-1);
  border: 1px solid var(--ad-border-faint);
  color: var(--ad-text-1);
  font-size: 12.5px;
  flex: 1;
  cursor: default;
  min-height: 38px;
}
/* Flash a chip green for ~1s when the value it shows grows. */
.txlRank--flash {
  animation: txlRankFlash 1s ease-out;
}
@keyframes txlRankFlash {
  0%, 15% {
    background: rgba(74, 222, 128, 0.30);
    border-color: rgba(74, 222, 128, 0.75);
    color: #4ade80;
  }
  100% {
    background: var(--ad-bg-elev-1);
    border-color: var(--ad-border-faint);
    color: var(--ad-text-1);
  }
}
.infoBox {
  justify-content: center;
  text-align: center;
  width: 95%;
  flex: 1;
  cursor: default;
  border-radius: var(--ad-r-md);
  border: 1px solid var(--ad-border-soft);
  background: var(--ad-bg-elev-1);
}

/* ─── Network badge (mainnet / testnet pill) ─────────────────────── */
.networkBadge {
  align-self: center;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin: 3px;
  padding: 4px 10px 4px 8px;
  border-radius: var(--ad-r-pill);
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 2px;
  text-transform: uppercase;
  font-family: var(--ad-font-mono);
  user-select: none;
}
.networkBadge--toggle {
  cursor: pointer;
  transition: filter 0.15s ease, transform 0.12s ease;
}
.networkBadge--toggle:hover {
  filter: brightness(1.1);
}
.networkBadge--toggle:active {
  transform: scale(0.97);
}
.networkBadge__dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
  box-shadow: 0 0 6px currentColor;
}
.networkBadge__arrow {
  opacity: 0.6;
  font-size: 9px;
  letter-spacing: 0;
}
.badgeProd {
  background: rgba(196, 82, 79, 0.18);
  color: var(--ad-red-1);
  border: 1px solid rgba(196, 82, 79, 0.45);
}
.badgeTest {
  background: rgba(245, 196, 81, 0.16);
  color: var(--ad-gold-2);
  border: 1px solid rgba(245, 196, 81, 0.45);
}

/* ─── Game canvas container ─────────────────────────────────────── */
.canvasContainer {
  border-radius: var(--ad-r-md);
  touch-action: manipulation;
  -webkit-user-select: none;
  user-select: none;
}
.canvasContainer canvas {
  display: block;
  max-width: 100%;
  height: auto;
}

/* ─── Tile/imageviewer used on welcome page (legacy fallback) ───── */
.imageViewer {
  flex: 1 1 200px;
  border: 1px solid var(--ad-border-soft);
  background: var(--ad-bg-elev-1);
  border-radius: var(--ad-r-md);
  padding: 8px;
  margin: 4px;
  cursor: pointer;
  transition: background 0.15s ease, border-color 0.15s ease, transform 0.15s ease;
}
.imageViewer:hover {
  background: var(--ad-bg-elev-2);
  border-color: rgba(167, 139, 250, 0.45);
  transform: translateY(-1px);
}
.imageViewerBox {
  width: 100%;
  border-radius: var(--ad-r-sm);
  cursor: pointer;
}

/* ─── Info popup (rules drawer) ─────────────────────────────────── */
.infoPopup {
  position: relative;
  width: 100%;
  margin: 8px 0;
  padding: 14px 18px;
  background: linear-gradient(180deg, rgba(124, 58, 237, 0.10), rgba(124, 58, 237, 0.02));
  border: 1px solid var(--ad-border-soft);
  border-radius: var(--ad-r-md);
  text-align: left;
  cursor: not-allowed;
  color: var(--ad-text-2);
  font-size: 13px;
  line-height: 1.55;
}
.listItem {
  list-style-type: none;
  margin: 4px 0;
}

/* ─── Buttons: the workhorse ─────────────────────────────────────
   .actionButton           — default secondary button
   .actionButtonSelected   — currently-active state in nav
   .actionButtonHelp       — tertiary / muted help button
   All three share the same shape; the variants differ only in fill. */
.actionButton,
.actionButtonSelected,
.actionButtonHelp {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 10px 16px;
  margin: 3px 0;
  min-height: 40px;
  border-radius: var(--ad-r-pill);
  border: 1px solid var(--ad-border-soft);
  background: var(--ad-bg-elev-1);
  color: var(--ad-text-1);
  flex: 1;
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 0.02em;
  font-family: var(--ad-font-body);
  cursor: pointer;
  text-align: center;
  transition: background 0.18s ease, border-color 0.18s ease,
              transform 0.12s ease, box-shadow 0.2s ease;
  /* Subtle inner highlight so the button feels lit from above. */
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.04);
}
.actionButton:hover,
.actionButtonHelp:hover {
  background: var(--ad-bg-elev-2);
  border-color: rgba(167, 139, 250, 0.55);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.06),
    var(--ad-glow-violet);
}
.actionButton:active,
.actionButtonHelp:active,
.actionButtonSelected:active {
  transform: translateY(1px) scale(0.99);
}
.actionButtonHelp {
  color: var(--ad-text-2);
  cursor: help;
}

/* The "selected" state in the top nav — gold gradient + glow. */
.actionButtonSelected {
  background: var(--ad-grad-gold);
  color: #1a1004;
  border-color: rgba(245, 196, 81, 0.7);
  font-weight: 700;
  text-shadow: 0 1px 0 rgba(255, 255, 255, 0.25);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.3),
    var(--ad-glow-gold);
}
.actionButtonSelected:hover {
  filter: brightness(1.05);
}

/* ─── App-nav carousel (TXL Manager first, then games) ─────────
   A horizontally-scrolling pill row flanked by arrow buttons. The
   strip itself is a CSS scroll-snap container so the active pill
   keeps near a snap-point as the user clicks the arrows. The pills
   carry their own active/inactive styling so we don't need the
   .actionButton family rules to apply (they would force flex:1 and
   wrap-stretch the pills full width). */
.navCarousel {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: 6px 0 8px;
  width: 100%;
}
.navStrip {
  flex: 1;
  display: flex;
  gap: 6px;
  overflow-x: auto;
  scroll-snap-type: x proximity;
  scroll-behavior: smooth;
  /* Hide scrollbar without removing the wheel/swipe behavior. */
  scrollbar-width: none;
  -ms-overflow-style: none;
  padding: 2px 4px;
}
.navStrip::-webkit-scrollbar { display: none; }
.navPill {
  flex: 0 0 auto;
  scroll-snap-align: center;
  padding: 8px 14px;
  min-height: 36px;
  border-radius: var(--ad-r-pill);
  border: 1px solid var(--ad-border-soft);
  background: var(--ad-bg-elev-1);
  color: var(--ad-text-1);
  font-family: var(--ad-font-body);
  font-size: 12.5px;
  font-weight: 600;
  letter-spacing: 0.02em;
  white-space: nowrap;
  cursor: pointer;
  transition: background 0.15s ease, border-color 0.15s ease,
              transform 0.1s ease;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.04);
}
.navPill:hover {
  background: var(--ad-bg-elev-2);
  border-color: rgba(167, 139, 250, 0.55);
}
.navPill:active { transform: scale(0.97); }
.navPill--active {
  background: var(--ad-grad-gold);
  color: #1a1004;
  border-color: rgba(245, 196, 81, 0.7);
  font-weight: 700;
  text-shadow: 0 1px 0 rgba(255, 255, 255, 0.25);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.3),
    var(--ad-glow-gold);
}
.navArrow {
  flex: 0 0 auto;
  width: 32px;
  height: 32px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  border: 1px solid var(--ad-border-soft);
  background: var(--ad-bg-elev-1);
  color: var(--ad-text-1);
  font-size: 18px;
  line-height: 1;
  cursor: pointer;
  user-select: none;
  transition: background 0.15s ease, border-color 0.15s ease,
              transform 0.1s ease;
}
.navArrow:hover {
  background: var(--ad-bg-elev-2);
  border-color: rgba(167, 139, 250, 0.55);
}
.navArrow:active { transform: scale(0.92); }

/* ─── Native select — styled to match the buttons ─────────────── */
.selectBox {
  padding: 8px 32px 8px 12px;
  margin: 2px 0;
  border-radius: var(--ad-r-md);
  border: 1px solid var(--ad-border-soft);
  background-color: var(--ad-bg-elev-1);
  background-image:
    linear-gradient(45deg, transparent 50%, var(--ad-text-2) 50%),
    linear-gradient(135deg, var(--ad-text-2) 50%, transparent 50%);
  background-position:
    calc(100% - 16px) 50%,
    calc(100% - 10px) 50%;
  background-size: 6px 6px, 6px 6px;
  background-repeat: no-repeat;
  color: var(--ad-text-1);
  font-family: var(--ad-font-body);
  font-size: 13px;
  flex: 1;
  cursor: pointer;
  appearance: none;
  -webkit-appearance: none;
  -moz-appearance: none;
  transition: background-color 0.15s ease, border-color 0.15s ease;
  min-height: 38px;
}
.selectBox:hover {
  background-color: var(--ad-bg-elev-2);
  border-color: var(--ad-border-mid);
}
.selectBox:focus {
  outline: none;
  border-color: rgba(167, 139, 250, 0.65);
  box-shadow: 0 0 0 3px rgba(124, 58, 237, 0.18);
}
.selectBox option {
  background-color: var(--ad-bg-base);
  color: var(--ad-text-1);
}

/* The "Made with love" footer-style label scattered in components. */
.label {
  text-align: center;
  color: var(--ad-text-3);
  font-size: 11px;
  letter-spacing: 0.04em;
  margin: 12px auto 0;
  font-family: var(--ad-font-body);
}
</style>
