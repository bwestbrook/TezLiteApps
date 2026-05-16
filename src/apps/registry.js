// App registry — single source of truth for every "feature" the suite hosts.
// Add a new app by appending an entry here; the nav and view-switching pick it
// up automatically. No edits to mainBody.vue required.
//
// Each entry:
//   id          string, unique. Used as the activeView key.
//   name        short tab label (≤16 chars renders nicely in the nav row)
//   blurb       one-liner shown on a tile
//   tag         category for grouping in the nav: 'game' | 'collection' | 'tools'
//   pinnedAsHome  (optional) renders first in the nav row, is excluded from
//                 NAV_APPS, and is the view mounted on app load. Exactly
//                 one entry should set this.
//   image       (optional) RESOLVED webpack URL for the tile image —
//               we use static require() per asset rather than a dynamic
//               require(`../assets/${name}`) because the latter makes
//               webpack scan the whole assets folder and fail on
//               non-loadable files like newteztac.html.
//   component   Vue component to mount when the app is active

import oracleInfo from '../components/oracleInfo.vue'
import browseNFTs from '../components/browseNFTs.vue'
import aceyDuecey from '../components/aceyDuecey.vue'
import tezTacToe from '../components/tezTacToe.vue'
import squaresGame from '../components/squaresGame.vue'
import plinkoGame from '../components/plinkoGame.vue'
import fortuneCookie from '../components/fortuneCookie.vue'
import chessGame from '../components/chessGame.vue'
import warGame from '../components/warGame.vue'
import mintTime from '../components/mintTime.vue'
import ecosystemLinks from '../components/ecosystemLinks.vue'

// Mainnet readiness — `mainnetReady: false` flags entries whose mainnet
// KT1 in src/constants.js is still the KT1XXX… placeholder. The nav UI
// surfaces a "soon" badge on those when NETWORK === 'mainnet'. On
// shadownet every app is reachable, so the badge is suppressed there.
import {
  AD_CONTRACT_ADDRESS_MAINNET,
  TTT_CONTRACT_ADDRESS_MAINNET,
  SQUARES_CONTRACT_ADDRESS_MAINNET,
  PLINKO_CONTRACT_ADDRESS_MAINNET,
  CHESS_CONTRACT_ADDRESS_MAINNET,
  WAR_CONTRACT_ADDRESS_MAINNET,
  FORTUNE_CONTRACT_ADDRESS_MAINNET,
  MINT_TIME_CONTRACT_ADDRESS_MAINNET,
  OBJECT_CONTRACT_MAINNET,
} from '../constants'
import { isPlaceholderAddress } from '../services/tzkt'
const isReady = (addr) => !isPlaceholderAddress(addr)

// Statically-resolved tile images. Each call is a static webpack require
// that resolves to a chunked URL at build time — no whole-folder scan.
const IMG = {
  nftExample:  require('../assets/nftExample.jpeg'),
  oracleLogo:  require('../assets/oracleLogo.jpg'),
  aceyDuecey:  require('../assets/aceyDuecey.png'),
  tezTacToe:   require('../assets/tezTacToe.png'),
  squares:     require('../assets/squaresTile.svg'),
  plinko:      require('../assets/plinkoTile.svg'),
  chess:       require('../assets/chessTile.svg'),
  war:         require('../assets/warTile.svg'),
}

// Nav order is the array order: the pinnedAsHome entry renders first,
// then the rest left-to-right. Games are listed by maturity (most
// shipped-ready first); the two 'tools' entries trail at the end.
export const APPS = [
  {
    id: 'browseNFTs',
    name: 'Browse 2.725K',
    blurb: 'View the 275-piece TXL collection and claim earned ꜩ.',
    tag: 'collection',
    image: IMG.nftExample,
    component: browseNFTs,
    pinnedAsHome: true,
    mainnetReady: isReady(OBJECT_CONTRACT_MAINNET),
  },
  {
    id: 'tezTacToe',
    name: 'TezTacToe',
    blurb: 'H2H 3D-4-in-a-row. Wager XTZ against another wallet.',
    tag: 'game',
    image: IMG.tezTacToe,
    component: tezTacToe,
    mainnetReady: isReady(TTT_CONTRACT_ADDRESS_MAINNET),
  },
  {
    id: 'squares',
    name: 'Squares',
    blurb: '10×10 Super-Bowl-style score pool. Quarter-by-quarter payouts.',
    tag: 'game',
    image: IMG.squares,
    component: squaresGame,
    mainnetReady: isReady(SQUARES_CONTRACT_ADDRESS_MAINNET),
  },
  {
    id: 'plinko',
    name: 'Plinko',
    blurb: 'Drop a ball, hope it bounces to the edges. Up to 29× payout.',
    tag: 'game',
    image: IMG.plinko,
    component: plinkoGame,
    mainnetReady: isReady(PLINKO_CONTRACT_ADDRESS_MAINNET),
  },
  {
    id: 'fortuneCookie',
    name: 'Fortune Cookie',
    blurb: 'Crack a cookie. Claude writes a deliberately mediocre fortune. Mint the good ones.',
    tag: 'game',
    component: fortuneCookie,
    mainnetReady: isReady(FORTUNE_CONTRACT_ADDRESS_MAINNET),
  },
  {
    id: 'aceyDuecey',
    name: 'Acey Duecey',
    blurb: 'Will the third card land between the two? Bet the pot.',
    tag: 'game',
    image: IMG.aceyDuecey,
    component: aceyDuecey,
    mainnetReady: isReady(AD_CONTRACT_ADDRESS_MAINNET),
  },
  {
    id: 'chess',
    name: 'Chess',
    blurb: 'Full standard chess. H2H, on-chain validated moves.',
    tag: 'game',
    image: IMG.chess,
    component: chessGame,
    mainnetReady: isReady(CHESS_CONTRACT_ADDRESS_MAINNET),
  },
  {
    id: 'war',
    name: 'War',
    blurb: '5-card showdown. Pure-luck H2H — exactly 50/50 by construction.',
    tag: 'game',
    image: IMG.war,
    component: warGame,
    mainnetReady: isReady(WAR_CONTRACT_ADDRESS_MAINNET),
  },
  {
    id: 'mintTime',
    name: 'Mint Time',
    blurb: 'Claim a UTC minute on planet Earth. Pick a frame, drop a note + image, mint a capsule.',
    tag: 'collection',
    image: IMG.nftExample,
    component: mintTime,
    mainnetReady: isReady(MINT_TIME_CONTRACT_ADDRESS_MAINNET),
  },
  {
    id: 'oracleInfo',
    name: 'Oracle',
    blurb: 'How the random-number oracle drives every TXL game.',
    tag: 'tools',
    image: IMG.oracleLogo,
    component: oracleInfo,
    mainnetReady: true,  // info page — works regardless of any contract state
  },
  {
    id: 'ecosystem',
    name: 'Tezos Links',
    blurb: 'Explorers, docs, faucets, wallets, dApps — the rest of the Tezos world.',
    tag: 'tools',
    image: IMG.oracleLogo,
    component: ecosystemLinks,
    mainnetReady: true,  // external links, no contract
  },
]

/** Lookup helpers used by the nav. */
export const APP_BY_ID = Object.fromEntries(APPS.map((a) => [a.id, a]))
export const HOME_APP = APPS.find((a) => a.pinnedAsHome) || APPS[0]
export const NAV_APPS = APPS.filter((a) => !a.pinnedAsHome)
export const TILE_APPS = APPS.filter((a) => a.tag !== 'home')
