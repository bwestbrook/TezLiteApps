<script>
// Tezos Ecosystem — curated links to the places you'll actually need when
// developing, debugging, or just exploring around TezLiteApps. Grouped so
// you can find what you want without scrolling a flat blob.
//
// To add a link: append to the appropriate group. Each link is
// { title, url, blurb }. If you add a new group, it shows automatically.

import { NETWORK } from '../constants'

const GROUPS = [
  {
    id: 'block-explorers',
    title: 'Block Explorers',
    blurb: 'Inspect contract state, operation history, and token flows.',
    links: [
      {
        title: 'TzKT',
        url: 'https://tzkt.io',
        blurb: 'Fast indexer + REST API. The same one this dApp queries for storage.',
      },
      {
        title: 'Better Call Dev',
        url: 'https://better-call.dev',
        blurb: 'Per-entrypoint operation explorer. Best for reading contract internals.',
      },
      {
        title: 'TzStats',
        url: 'https://tzstats.com',
        blurb: 'Chain stats + governance dashboards.',
      },
    ],
  },
  {
    id: 'dev-tools',
    title: 'Developer Tools',
    blurb: 'Compile contracts, sign ops, run tests.',
    links: [
      {
        title: 'SmartPy IDE',
        url: 'https://smartpy.io/ide',
        blurb: 'Browser-based contract IDE. Compile your .py → Michelson here.',
      },
      {
        title: 'Taquito Docs',
        url: 'https://tezostaquito.io/docs/quick_start',
        blurb: 'JS/TS SDK we use on the frontend.',
      },
      {
        title: 'PyTezos Docs',
        url: 'https://pytezos.org',
        blurb: 'Python SDK powering scripts/deploy.py and the oracle worker.',
      },
      {
        title: 'Beacon SDK Docs',
        url: 'https://docs.walletbeacon.io',
        blurb: 'Wallet-connection layer (works with Temple, Kukai, Umami, etc.).',
      },
      {
        title: 'Octez (Tezos node)',
        url: 'https://tezos.gitlab.io',
        blurb: 'Run your own node. Same code that the public RPCs run.',
      },
    ],
  },
  {
    id: 'testnet',
    title: 'Testnet Resources',
    blurb: 'Shadownet is our current dev target. Mainnet is live money.',
    links: [
      {
        title: 'Shadownet Faucet',
        url: 'https://faucet.shadownet.teztnets.com',
        blurb: 'Free testnet tez. Use this for the test wallet.',
      },
      {
        title: 'Teztnets Hub',
        url: 'https://teztnets.com',
        blurb: 'Index of all active Tezos testnets and their faucets.',
      },
      {
        title: 'TzKT — Shadownet',
        url: 'https://shadownet.tzkt.io',
        blurb: 'Same explorer, scoped to shadownet only.',
      },
    ],
  },
  {
    id: 'wallets',
    title: 'Wallets',
    blurb: 'Any Beacon-compatible wallet works with TezLiteApps.',
    links: [
      { title: 'Temple', url: 'https://templewallet.com', blurb: 'Browser extension; most common dev wallet.' },
      { title: 'Kukai', url: 'https://wallet.kukai.app', blurb: 'Web wallet, no install needed.' },
      { title: 'Umami', url: 'https://umamiwallet.com', blurb: 'Desktop, by the Nomadic Labs team.' },
      { title: 'Plenty', url: 'https://plentywallet.com', blurb: 'Mobile-first.' },
    ],
  },
  {
    id: 'apps',
    title: 'Notable dApps',
    blurb: 'See what others have built on Tezos.',
    links: [
      { title: 'Plenty DeFi', url: 'https://plenty.network', blurb: 'AMM + staking.' },
      { title: 'objkt.com', url: 'https://objkt.com', blurb: 'Largest Tezos NFT marketplace.' },
      { title: 'fxhash', url: 'https://fxhash.xyz', blurb: 'Generative-art NFT platform.' },
      { title: 'Quipuswap', url: 'https://quipuswap.com', blurb: 'AMM with launch tooling.' },
    ],
  },
  {
    id: 'learning',
    title: 'Docs & Learning',
    blurb: 'From "what is a contract" to "what does PROTO_BETA mean".',
    links: [
      { title: 'Tezos Developer Hub', url: 'https://docs.tezos.com', blurb: 'Canonical docs entry point.' },
      { title: 'OpenTezos', url: 'https://opentezos.com', blurb: 'Long-form tutorials and explainers.' },
      { title: 'Michelson Reference', url: 'https://tezos.gitlab.io/active/michelson.html', blurb: 'Every opcode, every type.' },
      { title: 'TZIP Standards', url: 'https://gitlab.com/tezos/tzip', blurb: 'Token + metadata standards (FA1.2, FA2, etc.).' },
    ],
  },
  {
    id: 'community',
    title: 'Community',
    blurb: 'Where the Tezos devs hang out.',
    links: [
      { title: 'Tezos Agora', url: 'https://forum.tezosagora.org', blurb: 'Long-form governance + ecosystem discussion.' },
      { title: 'Tezos Discord', url: 'https://discord.gg/tezos', blurb: 'Real-time chat, dev help channels.' },
      { title: 'r/tezos', url: 'https://www.reddit.com/r/tezos', blurb: 'Casual ecosystem news.' },
    ],
  },
]

export default {
  name: 'ecosystemLinks',
  data() {
    return {
      groups: GROUPS,
      NETWORK,
      copied: '',
    }
  },
  methods: {
    open(url) { window.open(url, '_blank', 'noopener,noreferrer') },
    async copy(url) {
      try {
        await navigator.clipboard.writeText(url)
        this.copied = url
        setTimeout(() => { if (this.copied === url) this.copied = '' }, 1200)
      } catch (_e) { /* ignore */ }
    },
  },
}
</script>

<template>
  <div class="ecosystemRoot">
    <div class="ecoHeader">
      <div class="ecoTitle">TEZOS ECOSYSTEM</div>
      <div class="ecoSub">
        You're on <span class="ecoNet">{{ NETWORK }}</span>. The links below are network-agnostic
        unless tagged otherwise.
      </div>
    </div>

    <div class="groups">
      <div v-for="g in groups" :key="g.id" class="group">
        <div class="groupHdr">
          <div class="groupTitle">{{ g.title }}</div>
          <div class="groupBlurb">{{ g.blurb }}</div>
        </div>
        <div class="links">
          <div
            v-for="l in g.links"
            :key="l.url"
            class="linkCard"
            @click="open(l.url)"
          >
            <div class="linkTitleRow">
              <span class="linkTitle">{{ l.title }}</span>
              <button
                :class="['copyBtn', copied === l.url ? 'copyBtn--ok' : '']"
                @click.stop="copy(l.url)"
                :title="copied === l.url ? 'Copied!' : 'Copy URL'"
              >
                {{ copied === l.url ? '✓' : '⧉' }}
              </button>
            </div>
            <div class="linkBlurb">{{ l.blurb }}</div>
            <div class="linkUrl">{{ l.url.replace(/^https?:\/\//, '') }}</div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.ecosystemRoot {
  padding: 16px;
  max-width: 920px;
  margin: 0 auto;
  color: var(--ad-text-1);
}

.ecoHeader { text-align: center; margin-bottom: 18px; }
.ecoTitle {
  font-family: var(--ad-font-display);
  font-size: 26px;
  letter-spacing: 0.14em;
  background: var(--ad-grad-violet);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}
.ecoSub {
  font-family: var(--ad-font-mono);
  font-size: 11px;
  color: var(--ad-text-3);
  margin-top: 4px;
}
.ecoNet {
  display: inline-block;
  padding: 1px 8px;
  border-radius: 999px;
  border: 1px solid var(--ad-border-mid);
  color: var(--ad-gold-1);
  text-transform: lowercase;
}

.groups { display: flex; flex-direction: column; gap: 18px; }
.group { animation: fadeUp 0.45s ease-out backwards; }
.group:nth-child(1) { animation-delay: 0.00s; }
.group:nth-child(2) { animation-delay: 0.05s; }
.group:nth-child(3) { animation-delay: 0.10s; }
.group:nth-child(4) { animation-delay: 0.15s; }
.group:nth-child(5) { animation-delay: 0.20s; }
.group:nth-child(6) { animation-delay: 0.25s; }
.group:nth-child(7) { animation-delay: 0.30s; }
@keyframes fadeUp {
  from { opacity: 0; transform: translateY(8px); }
  to   { opacity: 1; transform: translateY(0); }
}

.groupHdr { margin-bottom: 8px; }
.groupTitle {
  font-family: var(--ad-font-display);
  font-size: 16px;
  letter-spacing: 0.08em;
  color: var(--ad-text-1);
}
.groupBlurb {
  font-family: var(--ad-font-body);
  font-size: 12px;
  color: var(--ad-text-3);
  margin-top: 2px;
}

.links {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 8px;
}
.linkCard {
  position: relative;
  background: var(--ad-bg-elev-1);
  border: 1px solid var(--ad-border-soft);
  border-radius: var(--ad-r-md);
  padding: 10px 12px;
  cursor: pointer;
  transition: transform 0.15s ease, border-color 0.15s ease, background 0.15s ease;
}
.linkCard:hover {
  background: var(--ad-bg-elev-2);
  border-color: var(--ad-violet-1);
  transform: translateY(-2px);
  box-shadow: var(--ad-glow-violet);
}
.linkTitleRow {
  display: flex; align-items: center; justify-content: space-between;
  gap: 8px;
  margin-bottom: 4px;
}
.linkTitle {
  font-family: var(--ad-font-display);
  font-size: 14px;
  color: var(--ad-gold-1);
}
.copyBtn {
  width: 22px; height: 22px;
  background: var(--ad-bg-elev-2);
  border: 1px solid var(--ad-border-soft);
  border-radius: 4px;
  color: var(--ad-text-2);
  font-family: var(--ad-font-mono);
  font-size: 11px;
  cursor: pointer;
  transition: all 0.15s ease;
}
.copyBtn:hover { background: var(--ad-bg-elev-3); color: var(--ad-text-1); }
.copyBtn--ok { color: var(--ad-green-1); border-color: var(--ad-green-1); }

.linkBlurb {
  font-family: var(--ad-font-body);
  font-size: 11.5px;
  color: var(--ad-text-2);
  line-height: 1.4;
}
.linkUrl {
  font-family: var(--ad-font-mono);
  font-size: 10px;
  color: var(--ad-text-3);
  margin-top: 6px;
  text-overflow: ellipsis;
  overflow: hidden;
  white-space: nowrap;
}
</style>
