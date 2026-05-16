<script>
import { BeaconEvent } from '@airgap/beacon-sdk'
import { BeaconWallet } from '@taquito/beacon-wallet'
import { TezosToolkit } from '@taquito/taquito'
import io from 'socket.io-client'

import mainBody from './components/mainBody.vue'
import { reduceAddress } from './utilities'
import {
  APP_NAME,
  ADMIN_ADDRESS,
  DEFAULT_GAME_SIZE,
  NODE_URL,
  SOCKET_URL,
  clearStaleBeaconStorage,
  getBeaconNetwork,
} from './constants'

// Wipe any cached Beacon relay entries that point at known-dead hosts
// BEFORE the SDK initialises. Must happen at module-load time so it runs
// before any DAppClient instance reads from localStorage.
clearStaleBeaconStorage()

// Beacon throws/rejects non-Error objects when the user dismisses a
// wallet popup (e.g. `{title: 'Aborted', description: '…'}`). Those
// rejections don't always reach the awaiting promise's catch (Beacon
// fires several internal subscribers as well), so webpack-dev-server's
// overlay shows them as `ERROR [object Object]`. We swallow the known
// abort variants and let real errors continue to surface.
if (typeof window !== 'undefined') {
  const isBeaconAbort = (r) => {
    if (!r) return false
    if (r.name === 'AbortedBeaconError') return true
    const probe = `${r.title || ''} ${r.description || ''} ${r.message || ''}`.toLowerCase()
    return /aborted|cancel|denied|user closed|user rejected/.test(probe)
  }
  // Some wallets (notably Kukai's hosted web wallet) don't implement the
  // `shadownet` network type even though beacon-sdk's enum declares it.
  // They reject the permission request with NetworkNotSupportedBeaconError.
  // That rejection escapes Beacon's internal subscribers as an uncaught
  // promise — swallow it and point the user at a wallet that works.
  const isBeaconNetworkUnsupported = (r) => {
    if (!r) return false
    if (r.name === 'NetworkNotSupportedBeaconError') return true
    const probe = `${r.title || ''} ${r.description || ''} ${r.message || ''}`.toLowerCase()
    return /network.*not.*support|not.*support.*network|network_not_supported/.test(probe)
  }
  window.addEventListener('unhandledrejection', (event) => {
    if (isBeaconAbort(event.reason)) {
      event.preventDefault()
      // Surface a quiet console note so devs can still see it happened.
      // eslint-disable-next-line no-console
      console.info('[beacon] user dismissed wallet popup — suppressing overlay')
    } else if (isBeaconNetworkUnsupported(event.reason)) {
      event.preventDefault()
      // eslint-disable-next-line no-console
      console.warn(
        '[beacon] wallet rejected the shadownet network. Kukai\'s web wallet ' +
        'does not support shadownet — use Temple (browser extension), which ' +
        'connects to custom/test networks.',
      )
    }
  })
  window.addEventListener('error', (event) => {
    if (
      isBeaconAbort(event.error) || isBeaconAbort(event) ||
      isBeaconNetworkUnsupported(event.error) || isBeaconNetworkUnsupported(event)
    ) {
      event.preventDefault()
    }
  })
}

const Tezos = new TezosToolkit(NODE_URL)

export default {
  name: 'TezosXTZLounge',
  components: { mainBody },
  data() {
    return {
      wallet: undefined,
      tezos: undefined,
      socket: undefined,
      walletAddress: undefined,
      user: '',
      gameSize: DEFAULT_GAME_SIZE,
      windowWidth: typeof window !== 'undefined' ? window.innerWidth : 0,
    }
  },
  created() {
    this.socket = io(SOCKET_URL)
    this.tezos = Tezos
    this.getWallet()
    this.socket.on('socketId', (socketId) => {
      this.user = socketId
    })
  },
  mounted() {
    window.addEventListener('resize', this.onResize)
  },
  beforeUnmount() {
    window.removeEventListener('resize', this.onResize)
  },
  methods: {
    async getWallet() {
      // Reuse an existing wallet if one was already created on this page.
      if (this.wallet) return this.wallet

      // Build the Beacon network config from constants. For mainnet the
      // SDK already knows the RPC, but we pass it explicitly anyway so
      // the dApp and the wallet are always agreeing on the same chain.
      const network = getBeaconNetwork()
      // No matrixNodes override. Beacon-sdk 4.8.x ships a current
      // regional list (papers.tech + octez.io hosts). A previous
      // override pinned EUROPE to a hand-picked 4-host papers.tech
      // subset using the wrong region key — wallets were probing the
      // full default set (including beacon-node-*.octez.io) and posting
      // responses to servers we weren't listening on, surfacing in
      // Temple as "No server responded".
      const wallet = new BeaconWallet({
        name: APP_NAME,
        network,
      })
      this.wallet = wallet

      wallet.client.subscribeToEvent(BeaconEvent.ACTIVE_ACCOUNT_SET, (account) => {
        this.broadcastWallet(account)
        this.socket.emit('walletConnection', account?.address ?? null)
        this.socket.emit('updateGames')
      })

      // Replace Beacon's default UI for these events with no-ops. The
      // default handler shows a blocking alert AND emits the same object
      // out as an error; subscribing here disables both. Our own
      // try/catch in startGameBC/continueBetBC/dealCard handles user-facing
      // status updates instead.
      //
      // GENERIC_ERROR is included because beacon-sdk re-runs init() on
      // session restore for non-p2p origins (extension, post-message);
      // if its parallel P2P transport connect fails (relay probe race
      // times out at 60s), DAppClient.js:589 emits GENERIC_ERROR with
      // err.message "No server responded." — which the default handler
      // surfaces as a modal alert with a Send Report button. The session
      // also gets torn down by abortHandler regardless. Swallowing here
      // hides the popup; the disconnect still happens (we don't control
      // the SDK's abort), but the noisy modal is gone.
      const swallowed = [
        BeaconEvent.OPERATION_REQUEST_ERROR,
        BeaconEvent.PERMISSION_REQUEST_ERROR,
        BeaconEvent.SIGN_REQUEST_ERROR,
        BeaconEvent.BROADCAST_REQUEST_ERROR,
        BeaconEvent.NO_PERMISSIONS,
        BeaconEvent.GENERIC_ERROR,
        BeaconEvent.UNKNOWN,
      ]
      for (const evt of swallowed) {
        if (evt) {
          try {
            wallet.client.subscribeToEvent(evt, (data) => {
              // eslint-disable-next-line no-console
              console.info(`[beacon] ${evt}:`, data)
            })
          } catch (_e) {
            // Not all SDK versions expose every event constant — skip
            // missing ones silently.
          }
        }
      }

      return wallet
    },
    async broadcastWallet(account) {
      if (!account) {
        this.socket.emit('newWallet', 'SYNC WALLET')
        this.socket.emit('updateGames')
        return
      }
      // Use the connected wallet as the signing provider. Beacon proxies signing
      // requests to the wallet; we should NOT instantiate a RemoteSigner here.
      this.tezos.setWalletProvider(this.wallet)
      const reducedAddress = await reduceAddress(account.address)
      this.socket.emit('newWallet', `UNSYNC WALLET ${reducedAddress}`)
    },
    async sendTezos(_activeAccount, amount) {
      this.tezos.setWalletProvider(this.wallet)
      await this.tezos.wallet.transfer({ amount, to: ADMIN_ADDRESS }).send()
    },
    onResize() {
      this.windowWidth = window.innerWidth
      this.socket.emit('resizeGame', window.innerWidth, this.socket.id)
    },
  },
}
</script>

<template>
  <div class="body">
    <mainBody :wallet="wallet" :socket="socket" :tezos="tezos" :gameSize="gameSize" />
  </div>
</template>

<style>
/* ─── Design tokens ─────────────────────────────────────────────────────
   Crypto/web3 dark aesthetic. Saturated gradient accents, violet hover
   glows, mixed type. These vars are consumed by .actionButton, .gameInfo,
   etc. in mainBody.vue, and by every component's scoped styles when they
   reference var(--ad-...). Tweak them here to retheme globally. */
/* ─── Theme: Imperial Bordeaux ──────────────────────────────────────
   Wine-dark base, burnished brass primary, jade-teal secondary. Warm
   ivory text instead of cool white. Replaces the prior navy / gold /
   violet palette.

   NAMING NOTE: token names (`--ad-gold-*`, `--ad-violet-*`) are
   preserved as semantic slots — gold = primary accent, violet =
   secondary accent — so the components don't need to be re-themed
   one by one. The *values* are what changed. In this palette:
       --ad-gold-*    → brass (cream-yellow → dark bronze)
       --ad-violet-*  → jade / teal (mint highlight → deep teal)
       --ad-red-*     → wine-red status
       --ad-green-*   → forest (kept — table felt still reads correctly) */
:root {
  /* Surface — wine-dark, not navy */
  --ad-bg-deep: #0d0408;
  --ad-bg-base: #1a0a0e;
  --ad-bg-elev-1: rgba(245, 236, 225, 0.04);
  --ad-bg-elev-2: rgba(245, 236, 225, 0.07);
  --ad-bg-elev-3: rgba(245, 236, 225, 0.11);

  /* Borders — warm-tinted instead of neutral white */
  --ad-border-faint: rgba(245, 236, 225, 0.06);
  --ad-border-soft:  rgba(245, 236, 225, 0.10);
  --ad-border-mid:   rgba(245, 236, 225, 0.18);

  /* Text — warm ivory rather than cool white */
  --ad-text-1: #f5ece1;
  --ad-text-2: rgba(245, 236, 225, 0.74);
  --ad-text-3: rgba(245, 236, 225, 0.46);

  /* Accents — brass (primary, mapped to the gold slot) */
  --ad-gold-1: #f4d29a;   /* polished brass highlight */
  --ad-gold-2: #c89a4e;   /* main brass */
  --ad-gold-3: #8a6326;   /* dark brass */

  /* Jade / teal (secondary, mapped to the violet slot — complementary
     to brass, classic high-stakes table feel) */
  --ad-violet-1: #7dd3c8;
  --ad-violet-2: #14a094;
  --ad-violet-3: #084f48;

  /* Status */
  --ad-red-1: #ff9d8a;
  --ad-red-2: #b94838;
  --ad-green-1: #88c89a;
  --ad-green-2: #1f5c3a;

  /* Gradients */
  --ad-grad-gold:   linear-gradient(135deg, #f4d29a 0%, #c89a4e 50%, #8a6326 100%);
  --ad-grad-violet: linear-gradient(135deg, #7dd3c8 0%, #14a094 100%);
  --ad-grad-fire:   linear-gradient(135deg, #f4d29a 0%, #c89a4e 35%, #b94838 100%);
  --ad-grad-bg:     radial-gradient(ellipse at 50% -10%, rgba(20, 160, 148, 0.20) 0%, transparent 60%),
                    radial-gradient(ellipse at 100% 100%, rgba(200, 154, 78, 0.12) 0%, transparent 50%),
                    linear-gradient(180deg, #1a0a0e 0%, #0d0408 100%);

  /* Shadows / glows — re-tuned for brass + teal */
  --ad-shadow-card:  0 10px 30px rgba(0, 0, 0, 0.60), 0 1px 2px rgba(0, 0, 0, 0.45);
  --ad-glow-gold:    0 0 0 1px rgba(200, 154, 78, 0.55), 0 6px 20px rgba(200, 154, 78, 0.22);
  --ad-glow-violet:  0 0 0 1px rgba(125, 211, 200, 0.55), 0 6px 22px rgba(20, 160, 148, 0.26);

  /* Radius */
  --ad-r-sm: 6px;
  --ad-r-md: 10px;
  --ad-r-lg: 14px;
  --ad-r-pill: 999px;

  /* Type */
  --ad-font-display: 'EB Garamond', ui-serif, Georgia, serif;
  --ad-font-body:    'Inter', system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif;
  --ad-font-mono:    'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}

html, body {
  margin: 0;
  padding: 0;
  overflow-x: hidden;
  background: var(--ad-bg-deep);
  color: var(--ad-text-1);
  font-family: var(--ad-font-body);
  font-feature-settings: 'cv11', 'ss01';
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}

body {
  /* Subtle ambient gradient backdrop that sits behind every screen. */
  min-height: 100vh;
  background: var(--ad-grad-bg);
  background-attachment: fixed;
  padding: 16px 0;
}

#app {
  text-align: center;
  color: var(--ad-text-1);
  margin: 0;
  padding: 0;
}

/* Native form controls — modernize the defaults so even unstyled selects
   and inputs feel native to the dark theme. */
input, select, textarea, button {
  font-family: inherit;
  color: inherit;
}
button { cursor: pointer; }

/* Crisper scrollbars on dark surfaces. WebKit only — Firefox has its own. */
::-webkit-scrollbar { width: 10px; height: 10px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.08);
  border-radius: 999px;
}
::-webkit-scrollbar-thumb:hover { background: rgba(255, 255, 255, 0.18); }

/* ─── Global animations ──────────────────────────────────────────────
   Reusable keyframes + utility classes. Components opt-in via class. */

/* Smooth fade + lift on first paint or view-switch. */
@keyframes adFadeUp {
  from { opacity: 0; transform: translateY(10px); }
  to   { opacity: 1; transform: translateY(0); }
}
@keyframes adFadeIn {
  from { opacity: 0; }
  to   { opacity: 1; }
}
@keyframes adShimmer {
  0%   { background-position: -200% 0; }
  100% { background-position: 200% 0; }
}
@keyframes adPulseDot {
  0%, 100% { transform: scale(1);   opacity: 1; }
  50%      { transform: scale(1.6); opacity: 0.55; }
}
@keyframes adGlowSoft {
  0%, 100% { box-shadow: 0 0 0 0 rgba(167, 139, 250, 0); }
  50%      { box-shadow: 0 0 0 6px rgba(167, 139, 250, 0.10); }
}

/* View container — every top-level app component gets a gentle entrance. */
.view-enter-active,
.view-leave-active {
  transition: opacity 0.28s ease, transform 0.28s ease;
}
.view-enter-from { opacity: 0; transform: translateY(8px); }
.view-leave-to   { opacity: 0; transform: translateY(-8px); }

/* Network-badge dot pulse — applied via .networkBadge__dot in mainBody. */
.networkBadge__dot {
  animation: adPulseDot 2.4s ease-in-out infinite;
}

/* Generic action-button hover lift. Components can drop the class on
   anything clickable to get a consistent micro-interaction. */
.actionLift {
  transition: transform 0.15s ease, box-shadow 0.2s ease, background 0.15s ease;
}
.actionLift:hover { transform: translateY(-2px); }
.actionLift:active { transform: translateY(0); }

/* Skeleton shimmer for loading states. */
.adSkel {
  background: linear-gradient(
    90deg,
    var(--ad-bg-elev-1) 0%,
    var(--ad-bg-elev-3) 50%,
    var(--ad-bg-elev-1) 100%
  );
  background-size: 200% 100%;
  animation: adShimmer 1.6s linear infinite;
  border-radius: var(--ad-r-sm);
}

/* Honor user's reduced-motion preference. */
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.001ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.001ms !important;
  }
}

/* ─── Mobile baseline ─────────────────────────────────────────────────
   App.vue scope: rules that need to win against everything, since the
   shell + game components inherit body styles. mainBody.vue carries
   the rest (button/nav touch targets). */

/* Belt-and-suspenders: prevent ANY child from causing the page to
   sideways-scroll on phones. Some game canvases briefly overflow during
   animation; without this they push the whole viewport. */
html, body {
  overflow-x: hidden;
  max-width: 100vw;
}
/* Phones: shrink ambient body padding, ensure tap-zoom doesn't kick in
   for input controls (font-size >= 16px is iOS's threshold). */
@media (max-width: 480px) {
  body { padding: 6px 0; }
  input, select, textarea {
    /* iOS Safari auto-zooms any focused control whose font-size is
       under 16px. Pinning to 16px keeps the viewport steady. */
    font-size: 16px;
  }
}
</style>
