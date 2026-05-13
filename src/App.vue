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
  BEACON_MATRIX_NODES,
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
  window.addEventListener('unhandledrejection', (event) => {
    if (isBeaconAbort(event.reason)) {
      event.preventDefault()
      // Surface a quiet console note so devs can still see it happened.
      // eslint-disable-next-line no-console
      console.info('[beacon] user dismissed wallet popup — suppressing overlay')
    }
  })
  window.addEventListener('error', (event) => {
    if (isBeaconAbort(event.error) || isBeaconAbort(event)) {
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
      // Override Beacon's default Matrix relay list. The default
      // beacon-server-2.papers.tech hostname doesn't resolve from some
      // ISPs and the SDK waits ~45s on it before failing over. We give
      // it a known-good list up front so it skips that timeout.
      //
      // @airgap/beacon-sdk@4.x types matrixNodes as a per-region object
      //   { EUROPE: string[], NORTH_AMERICA: string[], ... }
      // Passing a flat array makes the SDK iterate string characters as
      // hostnames — that's where the `https://a/`, `https://h/` errors
      // come from. Pass the right shape, with our overrides in EUROPE
      // (papers.tech's primary cluster).
      const wallet = new BeaconWallet({
        name: APP_NAME,
        network,
        matrixNodes: { EUROPE: BEACON_MATRIX_NODES },
      })
      this.wallet = wallet

      wallet.client.subscribeToEvent(BeaconEvent.ACTIVE_ACCOUNT_SET, (account) => {
        this.broadcastWallet(account)
        this.socket.emit('walletConnection', account.address)
        this.socket.emit('updateGames')
      })

      // Replace Beacon's default UI for these events with no-ops. The
      // default handler shows a blocking alert AND emits the same object
      // out as an error; subscribing here disables both. Our own
      // try/catch in startGameBC/continueBetBC/dealCard handles user-facing
      // status updates instead.
      const swallowed = [
        BeaconEvent.OPERATION_REQUEST_ERROR,
        BeaconEvent.PERMISSION_REQUEST_ERROR,
        BeaconEvent.SIGN_REQUEST_ERROR,
        BeaconEvent.BROADCAST_REQUEST_ERROR,
        BeaconEvent.NO_PERMISSIONS,
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
:root {
  /* Surface */
  --ad-bg-deep: #04030f;
  --ad-bg-base: #0a0820;
  --ad-bg-elev-1: rgba(255, 255, 255, 0.04);
  --ad-bg-elev-2: rgba(255, 255, 255, 0.07);
  --ad-bg-elev-3: rgba(255, 255, 255, 0.10);

  /* Borders */
  --ad-border-faint: rgba(255, 255, 255, 0.06);
  --ad-border-soft:  rgba(255, 255, 255, 0.10);
  --ad-border-mid:   rgba(255, 255, 255, 0.18);

  /* Text */
  --ad-text-1: #f3f1ee;
  --ad-text-2: rgba(243, 241, 238, 0.72);
  --ad-text-3: rgba(243, 241, 238, 0.45);

  /* Accents */
  --ad-gold-1: #ffe089;
  --ad-gold-2: #f5c451;
  --ad-gold-3: #d4a24e;
  --ad-violet-1: #a78bfa;
  --ad-violet-2: #7c3aed;
  --ad-violet-3: #4c1d95;
  --ad-red-1: #ff8a87;
  --ad-red-2: #c4524f;
  --ad-green-1: #76c48a;
  --ad-green-2: #1f5c3a;

  /* Gradients */
  --ad-grad-gold:   linear-gradient(135deg, #ffe089 0%, #f5c451 50%, #d4a24e 100%);
  --ad-grad-violet: linear-gradient(135deg, #a78bfa 0%, #7c3aed 100%);
  --ad-grad-fire:   linear-gradient(135deg, #ffe089 0%, #f5c451 35%, #c4524f 100%);
  --ad-grad-bg:     radial-gradient(ellipse at 50% -10%, rgba(124, 58, 237, 0.18) 0%, transparent 60%),
                    radial-gradient(ellipse at 100% 100%, rgba(245, 196, 81, 0.10) 0%, transparent 50%),
                    linear-gradient(180deg, #0a0820 0%, #04030f 100%);

  /* Shadows / glows */
  --ad-shadow-card:  0 10px 30px rgba(0, 0, 0, 0.55), 0 1px 2px rgba(0, 0, 0, 0.4);
  --ad-glow-gold:    0 0 0 1px rgba(245, 196, 81, 0.5), 0 6px 20px rgba(245, 196, 81, 0.18);
  --ad-glow-violet:  0 0 0 1px rgba(167, 139, 250, 0.55), 0 6px 22px rgba(124, 58, 237, 0.25);

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
</style>
