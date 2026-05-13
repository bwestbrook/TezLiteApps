// App registry — single source of truth for every "feature" the suite hosts.
// Add a new app by appending an entry here; the nav and view-switching pick it
// up automatically. No edits to mainBody.vue required.
//
// Each entry:
//   id          string, unique. Used as the activeView key.
//   name        short tab label (≤16 chars renders nicely in the nav row)
//   blurb       one-liner shown on the welcome page tile
//   tag         category for grouping in the nav: 'game' | 'collection' | 'tools'
//   image       (optional) RESOLVED webpack URL for the welcome tile —
//               we use static require() per asset rather than a dynamic
//               require(`../assets/${name}`) because the latter makes
//               webpack scan the whole assets folder and fail on
//               non-loadable files like newteztac.html.
//   component   Vue component to mount when the app is active

import welcomeIn from '../components/welcomeIn.vue'
import oracleInfo from '../components/oracleInfo.vue'
import browseNFTs from '../components/browseNFTs.vue'
import aceyDuecey from '../components/aceyDuecey.vue'
import tezTacToe from '../components/tezTacToe.vue'
import squaresGame from '../components/squaresGame.vue'
import reversiGame from '../components/reversiGame.vue'
import plinkoGame from '../components/plinkoGame.vue'
import chessGame from '../components/chessGame.vue'
import warGame from '../components/warGame.vue'
import ecosystemLinks from '../components/ecosystemLinks.vue'

// Statically-resolved tile images. Each call is a static webpack require
// that resolves to a chunked URL at build time — no whole-folder scan.
const IMG = {
  nftExample:  require('../assets/nftExample.jpeg'),
  oracleLogo:  require('../assets/oracleLogo.jpg'),
  aceyDuecey:  require('../assets/aceyDuecey.png'),
  tezTacToe:   require('../assets/tezTacToe.png'),
  squares:     require('../assets/squaresTile.svg'),
  reversi:     require('../assets/reversiTile.svg'),
  plinko:      require('../assets/plinkoTile.svg'),
  chess:       require('../assets/chessTile.svg'),
  war:         require('../assets/warTile.svg'),
}

export const APPS = [
  {
    id: 'welcome',
    name: 'TXL Home',
    blurb: 'The lobby — pick a game or browse the collection.',
    tag: 'home',
    component: welcomeIn,
    pinnedAsHome: true,
  },
  {
    id: 'browseNFTs',
    name: 'Browse 2.725K',
    blurb: 'View the 275-piece TXL collection and claim earned ꜩ.',
    tag: 'collection',
    image: IMG.nftExample,
    component: browseNFTs,
  },
  {
    id: 'oracleInfo',
    name: 'Oracle',
    blurb: 'How the random-number oracle drives every TXL game.',
    tag: 'tools',
    image: IMG.oracleLogo,
    component: oracleInfo,
  },
  {
    id: 'aceyDuecey',
    name: 'Acey Duecey',
    blurb: 'Will the third card land between the two? Bet the pot.',
    tag: 'game',
    image: IMG.aceyDuecey,
    component: aceyDuecey,
  },
  {
    id: 'tezTacToe',
    name: 'TezTacToe',
    blurb: 'H2H 3D-4-in-a-row. Wager XTZ against another wallet.',
    tag: 'game',
    image: IMG.tezTacToe,
    component: tezTacToe,
  },
  {
    id: 'squares',
    name: 'Squares',
    blurb: '10×10 Super-Bowl-style score pool. Quarter-by-quarter payouts.',
    tag: 'game',
    image: IMG.squares,
    component: squaresGame,
  },
  {
    id: 'reversi',
    name: 'Reversi',
    blurb: 'H2H pure-skill 8×8 strategy. Stake against an opponent.',
    tag: 'game',
    image: IMG.reversi,
    component: reversiGame,
  },
  {
    id: 'plinko',
    name: 'Plinko',
    blurb: 'Drop a ball, hope it bounces to the edges. Up to 29× payout.',
    tag: 'game',
    image: IMG.plinko,
    component: plinkoGame,
  },
  {
    id: 'chess',
    name: 'Chess',
    blurb: 'Full standard chess. H2H, on-chain validated moves.',
    tag: 'game',
    image: IMG.chess,
    component: chessGame,
  },
  {
    id: 'war',
    name: 'War',
    blurb: '5-card showdown. Pure-luck H2H — exactly 50/50 by construction.',
    tag: 'game',
    image: IMG.war,
    component: warGame,
  },
  {
    id: 'ecosystem',
    name: 'Tezos Links',
    blurb: 'Explorers, docs, faucets, wallets, dApps — the rest of the Tezos world.',
    tag: 'tools',
    image: IMG.oracleLogo,
    component: ecosystemLinks,
  },
]

/** Lookup helpers used by the nav + welcome screens. */
export const APP_BY_ID = Object.fromEntries(APPS.map((a) => [a.id, a]))
export const HOME_APP = APPS.find((a) => a.pinnedAsHome) || APPS[0]
export const NAV_APPS = APPS.filter((a) => !a.pinnedAsHome)
export const TILE_APPS = APPS.filter((a) => a.tag !== 'home')
