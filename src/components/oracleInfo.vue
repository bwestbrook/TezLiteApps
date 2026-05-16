<template>
  <div class="oracleRoot">

    <!-- Hero -->
    <div class="hero">
      <img class="heroLogo" src="../assets/oracleLogo.jpg" alt="Oracle logo" />
      <div class="heroBody">
        <div class="heroTitle">RANDOM ORACLE</div>
        <div class="heroSub">
          The randomness service that drives every TXL game — and a drop-in
          primitive any Tezos contract can call.
        </div>
        <div class="heroChips">
          <span class="chip chip--net">{{ NETWORK }}</span>
          <span class="chip chip--mono">{{ ORACLE_CONTRACT }}</span>
          <a
            class="chip chip--link"
            :href="explorerUrl"
            target="_blank"
            rel="noopener noreferrer"
          >view on tzkt ↗</a>
        </div>
      </div>
    </div>

    <!-- Live status -->
    <section class="card">
      <div class="cardHdr">
        <div class="cardTitle">LIVE STATUS</div>
        <div class="cardBlurb">
          On-chain storage pulled from TzKT. Refreshes on mount and on demand.
          <button class="refreshBtn" @click="loadStorage" :disabled="loading">
            {{ loading ? 'loading…' : 'refresh' }}
          </button>
        </div>
      </div>
      <div v-if="loadError" class="errBox">{{ loadError }}</div>
      <div class="statGrid">
        <div class="stat">
          <div class="statLbl">Fee per request</div>
          <div class="statVal">{{ feeDisplay }}</div>
        </div>
        <div class="stat">
          <div class="statLbl">Max nRandoms / request</div>
          <div class="statVal">{{ storage ? storage.maxRandomsPerRequest : '—' }}</div>
        </div>
        <div class="stat">
          <div class="statLbl">Total requests served</div>
          <div class="statVal">{{ storage ? storage.currentRequestId : '—' }}</div>
        </div>
        <div class="stat">
          <div class="statLbl">Operator pool (unwithdrawn)</div>
          <div class="statVal">{{ operatorPoolDisplay }}</div>
        </div>
        <div class="stat stat--wide">
          <div class="statLbl">Operator key (off-chain worker)</div>
          <div class="statVal statVal--mono">{{ storage ? storage.oracle : '—' }}</div>
        </div>
        <div class="stat stat--wide">
          <div class="statLbl">Admin key (fees, key rotation)</div>
          <div class="statVal statVal--mono">{{ storage ? storage.admin : '—' }}</div>
        </div>
      </div>
    </section>

    <!-- FAQ -->
    <section class="card">
      <div class="cardHdr">
        <div class="cardTitle">HOW IT WORKS</div>
      </div>
      <div class="faqList">
        <div v-for="f in faq" :key="f.q" class="faqRow">
          <div class="faqQ">{{ f.q }}</div>
          <div class="faqA">{{ f.a }}</div>
        </div>
      </div>
    </section>

    <!-- Integration -->
    <section class="card">
      <div class="cardHdr">
        <div class="cardTitle">USE IT FROM YOUR OWN CONTRACT</div>
        <div class="cardBlurb">
          Any Tezos contract — not just the ones in this repo — can request
          randomness from this oracle. Wire up a single callback entrypoint
          and a single requestRandom call.
        </div>
      </div>

      <ol class="stepList">
        <li>
          <strong>Add a callback entrypoint</strong> to your contract that
          accepts <code>(requestId: nat, randomValues: list[nat])</code>. Verify
          <code>sp.sender == oracle_address</code> inside it — otherwise anyone
          can spoof a result and steal your payout.
        </li>
        <li>
          <strong>Call requestRandom</strong> from any entrypoint, attaching
          at least <code>fee</code> ꜩ. Pass <code>sp.self_address</code> +
          the callback entrypoint name, plus how many values you want
          (1–{{ storage ? storage.maxRandomsPerRequest : 32 }}) and the
          inclusive maxValue per draw.
        </li>
        <li>
          <strong>Wait ≤30 s</strong>. The off-chain worker sees the pending
          request, draws values, and invokes your callback in a single
          fulfillRandom op. If your callback reverts the whole op reverts, so
          keep the callback total-fn-safe.
        </li>
        <li>
          <strong>(Optional) Run your own worker.</strong> The default operator
          is honest-but-trusted. If your game settles real money, point a copy
          of <code>scripts/oracle-worker.sh --game randomness</code> at the
          same oracle contract using your own funded tz1 key — the worker is
          stateless, restart-safe, and one daemon serves every requester.
        </li>
      </ol>

      <div class="codeWrap">
        <div class="codeHdr">
          <span>SmartPy — minimal integration snippet</span>
          <button
            :class="['copyBtn', codeCopied ? 'copyBtn--ok' : '']"
            @click="copyCode"
          >{{ codeCopied ? '✓ copied' : 'copy' }}</button>
        </div>
        <pre class="code"><code>{{ codeSample }}</code></pre>
        <div class="codeFoot">
          A 60-line working example sits at
          <code>src/services/smart_contract_oracle_reference.py</code> — a
          one-coin-flip dApp you can compile in the SmartPy IDE and deploy
          with <code>scripts/deploy.py</code>.
        </div>
      </div>
    </section>

    <!-- Worker -->
    <section class="card">
      <div class="cardHdr">
        <div class="cardTitle">THE OFF-CHAIN WORKER</div>
        <div class="cardBlurb">
          <code>scripts/oracle_worker.py</code> is the daemon that turns pending
          requests into fulfillments. It serves all of TXL's games AND any 3rd-
          party contract requesting from the same RandomOracle in one process.
        </div>
      </div>
      <div class="workerGrid">
        <div class="workerCol">
          <div class="workerLbl">What it polls</div>
          <div class="workerVal">
            Every <code>--poll</code> seconds (default 5s), the worker scans
            the oracle's <code>requests</code> map for rows with
            <code>requestStatus == 0</code> and fulfills them. Each request
            row carries the requester's callback address + entrypoint, so the
            worker doesn't need to know anything about your contract.
          </div>
        </div>
        <div class="workerCol">
          <div class="workerLbl">Run it yourself</div>
          <div class="workerVal">
            <pre class="codeInline"># shadownet, all game flavours + generic requests
./scripts/oracle-worker.sh

# only the generic RandomOracle (no game-specific logic)
./scripts/oracle-worker.sh --game randomness

# point at a different oracle KT1 (single-game mode required)
./scripts/oracle-worker.sh --game randomness --address KT1…</pre>
          </div>
        </div>
        <div class="workerCol">
          <div class="workerLbl">What you need</div>
          <div class="workerVal">
            A funded tz1 key matching <code>storage.oracle</code> (rotate via
            <code>scripts/rotate_oracle.sh</code>), Python 3.10+ with pytezos
            installed, and an always-on machine. Restarts are safe — the
            worker is stateless, all decisions come from re-reading on-chain
            storage.
          </div>
        </div>
      </div>
    </section>

    <!-- Trust -->
    <section class="card card--warn">
      <div class="cardHdr">
        <div class="cardTitle">⚠ TRUST MODEL — READ BEFORE INTEGRATING FOR VALUE</div>
      </div>
      <div class="warnBody">
        <p>
          The current v2 oracle gives clients <strong>no cryptographic
          defense against a malicious operator</strong>. The operator sees the
          pending request and is free to pick any result it wants — then
          publishes a seed that "reproduces" it. The seed proves internal
          consistency; it proves nothing about fairness.
        </p>
        <p>
          The security model of any contract that settles a payout on an
          oracle value is therefore <em>"this single key is honest."</em> If
          the key is compromised or the operator is adversarial, the operator
          can bias every dependent game.
        </p>
        <p>
          For real guarantees, the planned v3 design uses a
          <strong>commit-reveal scheme</strong>: the operator commits to a
          hash before it can see the request, and the reveal must match the
          hash or be rejected on chain. Not shipped yet. Until then, treat the
          oracle as a trusted operator, not a trustless primitive.
        </p>
      </div>
    </section>

  </div>
</template>

<script>
// oracleInfo — operator-facing landing page for the RandomOracle.
//
// Two audiences:
//   1. End users curious about "what is this oracle that drives the games?"
//   2. dApp devs who want to call requestRandom from their OWN contract and
//      have the same off-chain worker fulfill it.
//
// Mostly static copy + a small live-status panel that pings TzKT for the
// oracle contract's storage so the displayed fee, request count, and
// operator key always match what's actually on chain.

import { NETWORK, ORACLE_CONTRACT } from '../constants'
import { getContractStorage, isPlaceholderAddress } from '../services/tzkt'

const FAQ = [
  {
    q: 'What is the oracle?',
    a: `A standalone Tezos contract (RandomOracle v2) that any other contract on
       chain can call to get cryptographically-random nat values delivered back
       to a callback entrypoint. It's the randomness source behind every TXL
       game — Acey-Duecey card draws, Plinko deflections, War card flips, the
       TezTacToe first-move coin, and the Squares score-bucket assignment.`,
  },
  {
    q: 'How does it work?',
    a: `Two phases. Your contract calls requestRandom(callback, entrypoint,
       nRandoms, maxValue) and attaches the fee. The on-chain request is
       recorded with status = pending. An off-chain worker daemon
       (scripts/oracle_worker.py) sees the pending row, draws values from a
       CSPRNG, and calls fulfillRandom — which atomically credits the
       operator fee, records the result on chain, and invokes your callback
       entrypoint with the values.`,
  },
  {
    q: 'What guarantees does it give me?',
    a: `Auditability, not trustlessness. Every fulfillment writes the result
       AND a seed string on chain, so anyone can replay what the operator
       did. It does NOT prove the operator picked the seed without seeing the
       pending request first. For high-stakes use, either (a) run your own
       worker against the same contract, or (b) wait for the planned v3
       commit-reveal upgrade. See docs/ORACLE_INTEGRATION.md for the full
       trust model writeup.`,
  },
]

export default {
  name: 'oracleInfo',
  // wallet / socket are wired by registry.js but we don't currently need them
  // here — leaving them in the prop list so future "request randomness from
  // the UI" actions don't have to re-thread the plumbing.
  props: ['wallet', 'socket', 'tezos'],
  data() {
    return {
      NETWORK,
      ORACLE_CONTRACT,
      faq: FAQ,
      storage: null,
      loading: false,
      loadError: '',
      codeCopied: false,
    }
  },
  computed: {
    // tzkt frontend URL — same as src/services/tzkt.js' API host minus the
    // 'api.' prefix. Skipped entirely if the contract address is still the
    // KT1XXX… placeholder for this network.
    explorerUrl() {
      if (isPlaceholderAddress(ORACLE_CONTRACT)) return '#'
      const host = NETWORK === 'mainnet' ? 'tzkt.io' : `${NETWORK}.tzkt.io`
      return `https://${host}/${ORACLE_CONTRACT}`
    },
    feeDisplay() {
      if (!this.storage || this.storage.fee == null) return '—'
      // TzKT returns mutez as a string. 1 ꜩ = 1,000,000 mutez.
      const tez = Number(this.storage.fee) / 1_000_000
      return `${tez} ꜩ`
    },
    operatorPoolDisplay() {
      if (!this.storage || this.storage.operatorEarnings == null) return '—'
      const tez = Number(this.storage.operatorEarnings) / 1_000_000
      return `${tez.toFixed(6)} ꜩ`
    },
    codeSample() {
      // Pull the actual fee from live storage when available so the snippet
      // mirrors the on-chain value. Falls back to 0.1 ꜩ (100k mutez).
      const fee = this.storage && this.storage.fee ? this.storage.fee : '100000'
      return `@sp.entrypoint()
def rollDice(self):
    """User pays the fee; oracle calls onRandomFulfilled next block."""
    assert sp.amount >= sp.mutez(${fee}), "attach oracle fee"
    oracle = sp.contract(
        sp.record(
            callback=sp.address,
            callbackEntrypoint=sp.string,
            nRandoms=sp.nat,
            maxValue=sp.nat,
        ),
        sp.address("${ORACLE_CONTRACT}"),
        entrypoint="requestRandom",
    ).unwrap_some()
    sp.transfer(
        sp.record(
            callback=sp.self_address,
            callbackEntrypoint="onRandomFulfilled",
            nRandoms=2,        # roll 2 dice
            maxValue=5,        # values in [0,5], add 1 each for a d6
        ),
        sp.mutez(${fee}),
        oracle,
    )

@sp.entrypoint()
def onRandomFulfilled(self, params):
    """Oracle delivers here. NEVER skip the sp.sender check."""
    sp.cast(params.requestId, sp.nat)
    sp.cast(params.randomValues, sp.list[sp.nat])
    assert sp.sender == sp.address("${ORACLE_CONTRACT}"), "not oracle"
    # ... use params.randomValues ...`
    },
  },
  async mounted() {
    await this.loadStorage()
  },
  methods: {
    async loadStorage() {
      if (isPlaceholderAddress(ORACLE_CONTRACT)) {
        this.loadError = `No oracle deployed on ${NETWORK} yet.`
        return
      }
      this.loading = true
      this.loadError = ''
      try {
        const data = await getContractStorage(ORACLE_CONTRACT)
        if (!data) throw new Error('empty response from TzKT')
        this.storage = data
      } catch (err) {
        this.loadError = `Could not load oracle storage: ${err.message || err}`
      } finally {
        this.loading = false
      }
    },
    async copyCode() {
      try {
        await navigator.clipboard.writeText(this.codeSample)
        this.codeCopied = true
        setTimeout(() => { this.codeCopied = false }, 1500)
      } catch (_e) { /* clipboard unavailable */ }
    },
  },
}
</script>

<style scoped>
.oracleRoot {
  padding: 16px;
  max-width: 960px;
  margin: 0 auto;
  color: var(--ad-text-1);
  text-align: left;
  display: flex;
  flex-direction: column;
  gap: 18px;
}

/* ─── Hero ────────────────────────────────────────────────────────────── */
.hero {
  display: flex;
  gap: 18px;
  align-items: center;
  background: var(--ad-bg-elev-1);
  border: 1px solid var(--ad-border-soft);
  border-radius: var(--ad-r-lg);
  padding: 18px 20px;
  box-shadow: var(--ad-shadow-card);
}
.heroLogo {
  width: 88px; height: 88px;
  border-radius: var(--ad-r-md);
  object-fit: cover;
  flex-shrink: 0;
  border: 1px solid var(--ad-border-mid);
}
.heroBody { flex: 1; min-width: 0; }
.heroTitle {
  font-family: var(--ad-font-display);
  font-size: 28px;
  letter-spacing: 0.16em;
  background: var(--ad-grad-violet);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}
.heroSub {
  font-size: 13.5px;
  color: var(--ad-text-2);
  margin-top: 4px;
  line-height: 1.5;
}
.heroChips {
  display: flex; flex-wrap: wrap;
  gap: 6px; margin-top: 10px;
}
.chip {
  display: inline-block;
  padding: 2px 9px;
  border-radius: 999px;
  border: 1px solid var(--ad-border-mid);
  font-size: 11px;
  background: var(--ad-bg-elev-1);
  color: var(--ad-text-2);
}
.chip--net {
  color: var(--ad-gold-1);
  text-transform: lowercase;
  letter-spacing: 0.06em;
}
.chip--mono {
  font-family: var(--ad-font-mono);
  font-size: 10.5px;
  word-break: break-all;
}
.chip--link {
  color: var(--ad-violet-1);
  text-decoration: none;
  cursor: pointer;
  transition: all 0.15s ease;
}
.chip--link:hover {
  background: var(--ad-bg-elev-2);
  color: var(--ad-text-1);
  border-color: var(--ad-violet-1);
}

/* ─── Card scaffolding ───────────────────────────────────────────────── */
.card {
  background: var(--ad-bg-elev-1);
  border: 1px solid var(--ad-border-soft);
  border-radius: var(--ad-r-lg);
  padding: 16px 20px;
  box-shadow: var(--ad-shadow-card);
}
.card--warn {
  border-color: var(--ad-red-2);
  background:
    linear-gradient(180deg,
      rgba(196, 82, 79, 0.10) 0%,
      rgba(196, 82, 79, 0.04) 100%);
}
.cardHdr { margin-bottom: 12px; }
.cardTitle {
  font-family: var(--ad-font-display);
  font-size: 16px;
  letter-spacing: 0.12em;
  color: var(--ad-gold-1);
}
.cardBlurb {
  font-size: 12.5px;
  color: var(--ad-text-2);
  margin-top: 4px;
  line-height: 1.5;
}

/* ─── Live status grid ───────────────────────────────────────────────── */
.refreshBtn {
  margin-left: 8px;
  background: var(--ad-bg-elev-2);
  border: 1px solid var(--ad-border-soft);
  border-radius: var(--ad-r-sm);
  color: var(--ad-text-2);
  font-family: var(--ad-font-mono);
  font-size: 11px;
  padding: 2px 8px;
  cursor: pointer;
  transition: all 0.15s ease;
}
.refreshBtn:hover:not(:disabled) {
  color: var(--ad-text-1);
  background: var(--ad-bg-elev-3);
  border-color: var(--ad-violet-1);
}
.refreshBtn:disabled { opacity: 0.5; cursor: default; }

.errBox {
  margin-bottom: 8px;
  padding: 8px 10px;
  border-radius: var(--ad-r-sm);
  border: 1px solid var(--ad-red-2);
  background: rgba(196, 82, 79, 0.12);
  color: var(--ad-red-1);
  font-family: var(--ad-font-mono);
  font-size: 12px;
}

.statGrid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 10px;
}
.stat {
  background: var(--ad-bg-elev-2);
  border: 1px solid var(--ad-border-faint);
  border-radius: var(--ad-r-md);
  padding: 10px 12px;
}
.stat--wide { grid-column: 1 / -1; }
.statLbl {
  font-family: var(--ad-font-mono);
  font-size: 10.5px;
  color: var(--ad-text-3);
  text-transform: uppercase;
  letter-spacing: 0.08em;
}
.statVal {
  font-family: var(--ad-font-display);
  font-size: 18px;
  color: var(--ad-text-1);
  margin-top: 3px;
}
.statVal--mono {
  font-family: var(--ad-font-mono);
  font-size: 12px;
  word-break: break-all;
  color: var(--ad-text-2);
}

/* ─── FAQ ────────────────────────────────────────────────────────────── */
.faqList { display: flex; flex-direction: column; gap: 12px; }
.faqRow {
  border-left: 2px solid var(--ad-violet-2);
  padding-left: 12px;
}
.faqQ {
  font-family: var(--ad-font-display);
  font-size: 14px;
  color: var(--ad-gold-1);
  letter-spacing: 0.04em;
}
.faqA {
  font-size: 13px;
  color: var(--ad-text-2);
  margin-top: 4px;
  line-height: 1.55;
  white-space: pre-line;
}

/* ─── Step list + code ───────────────────────────────────────────────── */
.stepList {
  margin: 0 0 14px 0;
  padding-left: 20px;
  color: var(--ad-text-2);
  font-size: 13px;
  line-height: 1.6;
}
.stepList li { margin-bottom: 8px; }
.stepList strong { color: var(--ad-text-1); }
.stepList code,
.workerCol code,
.warnBody code,
.codeFoot code {
  font-family: var(--ad-font-mono);
  font-size: 11.5px;
  background: var(--ad-bg-elev-2);
  border: 1px solid var(--ad-border-faint);
  border-radius: 4px;
  padding: 0 4px;
  color: var(--ad-gold-2);
}

.codeWrap {
  background: var(--ad-bg-deep);
  border: 1px solid var(--ad-border-soft);
  border-radius: var(--ad-r-md);
  overflow: hidden;
}
.codeHdr {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  background: var(--ad-bg-elev-2);
  border-bottom: 1px solid var(--ad-border-faint);
  font-family: var(--ad-font-mono);
  font-size: 11px;
  color: var(--ad-text-3);
  text-transform: uppercase;
  letter-spacing: 0.08em;
}
.copyBtn {
  background: var(--ad-bg-elev-3);
  border: 1px solid var(--ad-border-soft);
  border-radius: var(--ad-r-sm);
  color: var(--ad-text-2);
  font-family: var(--ad-font-mono);
  font-size: 10.5px;
  padding: 3px 9px;
  cursor: pointer;
  transition: all 0.15s ease;
}
.copyBtn:hover { color: var(--ad-text-1); border-color: var(--ad-violet-1); }
.copyBtn--ok { color: var(--ad-green-1); border-color: var(--ad-green-1); }
.code {
  margin: 0;
  padding: 12px 14px;
  font-family: var(--ad-font-mono);
  font-size: 11.5px;
  line-height: 1.55;
  color: var(--ad-text-1);
  overflow-x: auto;
  white-space: pre;
}
.codeFoot {
  padding: 8px 12px;
  border-top: 1px solid var(--ad-border-faint);
  background: var(--ad-bg-elev-1);
  font-size: 11.5px;
  color: var(--ad-text-3);
  line-height: 1.5;
}

/* ─── Worker grid ────────────────────────────────────────────────────── */
.workerGrid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 12px;
}
.workerCol {
  background: var(--ad-bg-elev-2);
  border: 1px solid var(--ad-border-faint);
  border-radius: var(--ad-r-md);
  padding: 12px;
}
.workerLbl {
  font-family: var(--ad-font-mono);
  font-size: 10.5px;
  color: var(--ad-text-3);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  margin-bottom: 6px;
}
.workerVal {
  font-size: 12.5px;
  color: var(--ad-text-2);
  line-height: 1.5;
}
.codeInline {
  margin: 0;
  padding: 8px 10px;
  background: var(--ad-bg-deep);
  border: 1px solid var(--ad-border-faint);
  border-radius: var(--ad-r-sm);
  font-family: var(--ad-font-mono);
  font-size: 11px;
  line-height: 1.55;
  color: var(--ad-text-1);
  overflow-x: auto;
  white-space: pre;
}

/* ─── Warning card ───────────────────────────────────────────────────── */
.warnBody {
  font-size: 13px;
  color: var(--ad-text-2);
  line-height: 1.6;
}
.warnBody p { margin: 0 0 10px 0; }
.warnBody p:last-child { margin-bottom: 0; }
.warnBody strong { color: var(--ad-red-1); }
.warnBody em { color: var(--ad-text-1); font-style: italic; }

/* ─── Mobile ────────────────────────────────────────────────────────
   Most of this page is text-heavy cards; the dense grids (.statGrid,
   .workerGrid) already auto-fit. The hero collapses to a vertical
   stack on small screens so the logo + title don't fight for width. */
@media (max-width: 480px) {
  .oracleRoot { padding: 10px 8px; gap: 12px; }
  .hero {
    flex-direction: column;
    align-items: stretch;
    text-align: center;
    padding: 14px 12px;
    gap: 10px;
  }
  .heroLogo { width: 72px; height: 72px; margin: 0 auto; }
  .heroTitle { font-size: 22px; letter-spacing: 0.12em; }
  .heroSub { font-size: 12.5px; }
  .heroChips { justify-content: center; }
  .card { padding: 12px 14px; }
  .cardTitle { font-size: 14px; letter-spacing: 0.1em; }
  .cardBlurb { font-size: 12px; }
  .statGrid { grid-template-columns: 1fr; }
  .workerGrid { grid-template-columns: 1fr; }
  .stepList { font-size: 12.5px; }
  .code { font-size: 11px; }
  .codeInline { font-size: 10px; }
}
@media (min-width: 481px) and (max-width: 768px) {
  .hero { padding: 14px 16px; }
  .heroLogo { width: 78px; height: 78px; }
  .heroTitle { font-size: 24px; }
}
</style>
