# TezLiteApps

A Vue 3 + Tezos frontend that hosts a small suite of on-chain games and the
**TXL** NFT collection browser:

- **Acey Duecey** — Card-betting game settled on a Tezos smart contract.
- **TezTacToe** — Connect-Four-style 4x4x4 grid game between two wallets.
- **TXL NFT browser** — View the 275-piece TXL NFT collection.

The frontend talks to:

- The user's wallet via [Beacon](https://walletbeacon.io/) and `@taquito/*`.
- Tezos RPC nodes (Ghostnet by default — see `src/constants.js`).
- A small Express + Socket.IO relay (`server.js`) that brokers game state
  between connected clients. The smart contracts remain the source of truth
  for game outcomes.

## Project layout

```
.
├── server.js              # Express + Socket.IO relay (Heroku-deployed)
├── src/
│   ├── App.vue            # Root component — wallet + socket bootstrapping
│   ├── main.js
│   ├── constants.js       # Contract addresses, node URL, copy strings
│   ├── utilities.js       # Tiny helpers (math, address shortening, fetch)
│   ├── components/        # Vue components
│   ├── assets/            # Card images, NFT examples, table backgrounds
│   └── services/          # Python smart-contract scripts (pytezos)
└── public/                # Static index.html and favicons
```

## Setup

```sh
npm install
```

## Development

```sh
npm run serve   # vue-cli-service serve, hot reload
npm run lint    # eslint
npm run format  # prettier
npm run build   # production build to dist/
```

To run the relay server alongside the dev frontend:

```sh
npm start       # vue-cli-service serve & node server.js
```

## Deployment

The frontend + relay run together on Heroku via `Procfile`:

```sh
./git_push.sh "your commit message"
```

The script installs, builds, commits, and pushes to both `origin` and the
`heroku` remote.

## Configuration

All addresses, node URLs, and strings live in [`src/constants.js`](src/constants.js).
Switch RPC node by changing `NODE_URL`. Switch contract by changing the
matching `*_CONTRACT_ADDRESS`.

## License

Private project.
