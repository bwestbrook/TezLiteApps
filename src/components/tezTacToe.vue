<script>
import { PollingSubscribeProvider } from '@taquito/taquito'
import { RpcClient } from '@taquito/rpc'
import tttGameGrid from './tttGameGrid.vue'
import { NODE_URL, TTT_CONTRACT_ADDRESS, GAME_INFO, BLOCKCHAIN_ENABLED } from '../constants'
import { reduceAddress } from '../utilities'
import { isPlaceholderAddress } from '../services/tzkt'

// Ghostnet chain ID — used to scope the RPC client.
const GHOSTNET_CHAIN_ID = 'NetXnHfVqm9iesp'

export default {
  name: 'tezTacToe',
  components: { tttGameGrid },
  props: ['socket', 'wallet', 'tezos'],
    data () {
        return {
            gameInfo: GAME_INFO,
            allGamesStatus: {},
            gamesObject: {},
            gameId: -1,
            // Connected wallet address (empty until synced). Drives the
            // "is this mine" badge + contextual action in the lobby.
            myAddress: '',
            leavableGames: false,
            joinableGames: false,
            viewableGames: false,
            loadedGames: false,
            blockWaits: '',
            fee: 0.1,
            gameStatus: 'No Players',
            playerTurnStr: 'No Game',
            playerTurn: -1,
            playersInGame: '',
            player1Connected: '',
            player2Connected: '',
            addressesInGame: [],
            blockchainStatus: 'No Activity',
            pointToPlay: 'XXX',
            tezosSymbol: 'ꜩ',
            showInfo: false,
            // ── First-move oracle flip ────────────────────────────────
            // After both players pair, the game sits at gameStatus 2 with
            // firstMoveDecided 0 until the oracle's flipForFirst runs.
            // awaitingFlip gates play; firstMoveWinner (1|2, 0=unknown) is
            // captured the moment the flip resolves so we can show who got
            // the first move.
            awaitingFlip: false,
            firstMoveWinner: 0,
            // ── Move-in-flight lock ───────────────────────────────────
            // True from the moment a player submits a move until the
            // chain confirms it. Mirrored to BOTH players via the
            // updateMovePending socket event so the turn can't switch —
            // and neither board is interactive — on an unconfirmed move.
            movePending: false,
            // ── Wager controls (gambling) ─────────────────────────────
            wagerTez: 1.0,
            minWagerTez: 0,
            maxWagerTez: 50,
            // House cut in basis points (250 = 2.5%) — refreshed from storage.
            houseCutBps: 250,
        }
    },
    computed: {
        houseCutPercent() {
            return (this.houseCutBps / 100).toFixed(2)
        },
        // Prominent whose-turn badge. Both players see the same source
        // state (playerTurn + gameStatus from chain); the label just
        // differs by which side is reading it.
        turnBadge() {
            // A move in flight overrides everything — both players see
            // this until the chain confirms and the turn can switch.
            if (this.movePending) {
                return { label: 'WRITING TO BLOCKCHAIN…', cls: 'turnFlip' }
            }
            if (this.awaitingFlip) {
                return { label: 'ORACLE COIN FLIP…', cls: 'turnFlip' }
            }
            if (this.playerTurnStr === 'YOUR TURN') {
                return { label: 'YOUR TURN', cls: 'turnYou' }
            }
            if (this.playerTurnStr === 'OPP TURN') {
                return { label: "OPPONENT'S TURN", cls: 'turnOpp' }
            }
            return { label: this.playerTurnStr || '—', cls: 'turnNone' }
        },
        // One-line feedback on the oracle's first-move flip, shown once
        // it's resolved. Empty until firstMoveWinner is captured.
        firstMoveLine() {
            if (!this.firstMoveWinner) return ''
            const who = this.playersInGame?.[this.firstMoveWinner - 1] || ''
            return `Oracle coin flip → Player ${this.firstMoveWinner} (${who}) won the first move`
        },
        // Pot math for the slider preview (before a game is joined).
        sliderGrossPotTez() {
            return this.wagerTez * 2
        },
        sliderHouseCutTez() {
            return this.sliderGrossPotTez * (this.houseCutBps / 10000)
        },
        sliderNetPotTez() {
            return this.sliderGrossPotTez - this.sliderHouseCutTez
        },
        // Pot math for the currently loaded game (after wagers locked).
        loadedGameWagerTez() {
            const g = this.gamesObject?.[this.gameId]
            if (!g || g.tzGameBet == null) return 0
            return Number(g.tzGameBet) / 1_000_000
        },
        loadedGameHouseCutBps() {
            const g = this.gamesObject?.[this.gameId]
            if (!g || g.houseCutBps == null) return this.houseCutBps
            return Number(g.houseCutBps)
        },
        loadedGameGrossPotTez() {
            return this.loadedGameWagerTez * 2
        },
        loadedGameHouseCutTez() {
            return this.loadedGameGrossPotTez * (this.loadedGameHouseCutBps / 10000)
        },
        loadedGameNetPotTez() {
            return this.loadedGameGrossPotTez - this.loadedGameHouseCutTez
        },
        // The shared lobby — one row per on-chain game, visible to both
        // players (and spectators) regardless of wallet state. Built from
        // gamesObject + myAddress; reactively re-derives as games refresh.
        //
        // gameStatus encoding (from the contract):
        //   0 cancelled · 1 open · 2 in progress · 3 winner · 4 cat's · 5 surrender
        lobbyGames() {
            const obj = this.gamesObject || {}
            const me = this.myAddress
            const ids = Object.keys(obj)
                .map(Number)
                .filter((n) => !Number.isNaN(n))
                .sort((a, b) => b - a) // newest first
            const rows = []
            for (const id of ids) {
                const g = obj[id]
                if (!g) continue
                const players = g.players || []
                const isMine = !!me && players.includes(me)
                const status = Number(g.gameStatus)
                const wagerMutez = g.tzGameBet != null ? Number(g.tzGameBet) : null
                let statusLabel = 'Unknown'
                let statusClass = 'tttStatus--other'
                let action = null
                let actionLabel = ''
                if (status === 0) {
                    statusLabel = 'Cancelled'
                    statusClass = 'tttStatus--dead'
                } else if (status === 1) {
                    statusLabel = 'Open'
                    statusClass = 'tttStatus--open'
                    action = isMine ? 'leave' : 'join'
                    actionLabel = isMine ? 'Leave' : 'Join'
                } else if (status === 2) {
                    // Paired but the oracle hasn't flipped for first move
                    // yet → "Coin flip"; once decided → "In progress".
                    const decided = Number(g.firstMoveDecided) === 1
                    statusLabel = decided ? 'In progress' : 'Coin flip'
                    statusClass = decided ? 'tttStatus--live' : 'tttStatus--flip'
                    action = isMine ? 'play' : 'view'
                    actionLabel = isMine ? 'Play' : 'View'
                } else if (status === 3) {
                    statusLabel = 'Finished'
                    statusClass = 'tttStatus--done'
                    action = 'view'
                    actionLabel = 'View'
                } else if (status === 4) {
                    statusLabel = "Cat's game"
                    statusClass = 'tttStatus--done'
                    action = 'view'
                    actionLabel = 'View'
                } else if (status === 5) {
                    statusLabel = 'Surrendered'
                    statusClass = 'tttStatus--done'
                    action = 'view'
                    actionLabel = 'View'
                }
                rows.push({
                    id,
                    status,
                    statusLabel,
                    statusClass,
                    isMine,
                    p1: players[0] ? reduceAddress(players[0]) : 'waiting…',
                    p2: players[1] ? reduceAddress(players[1]) : 'open seat',
                    wagerLabel:
                        wagerMutez != null
                            ? (wagerMutez / 1_000_000).toFixed(2) + ' ꜩ'
                            : '—',
                    action,
                    actionLabel,
                })
            }
            return rows
        },
    },
    created() {
        this.rpcclient = new RpcClient(NODE_URL, GHOSTNET_CHAIN_ID);
        this.streamSubs = []
        this.socket.on("updateGames", () => {
            this.getGamesFromContractAsync()
        })
        this.socket.on("newWallet", (newWallet) => {
            this.walletAddres = newWallet
        })
        this.socket.on("updatePlayerControl", (gamesObject) => {
            this.updatePlayerControl(gamesObject)
        })
        this.socket.on("updateConnectedUsers", (address) => {
            this.updateConnectedUsers(address)
        })
        this.socket.on("loadGame", (gameId, updateGrid) => {
            this.getGameGrid(gameId, updateGrid)
            this.updatePlayerControl()
        })

        this.socket.on('playedPoint', (playedPoint, bcStatus) => {
            this.pointToPlay = playedPoint
            this.blockchainStatus = bcStatus
        })
        this.socket.on('updateBCStatus', (bcStatus) => {
            this.blockchainStatus = bcStatus
        })
        this.socket.on('updateGamePlayable', (gamePlayable) => {
            this.gamePlayable = gamePlayable
        })
        // A move is being written to chain (or just finished). Mirrored
        // to both players so neither can act until it's confirmed.
        this.socket.on('updateMovePending', (pending) => {
            this.movePending = !!pending
            if (this._movePendingTimer) {
                clearTimeout(this._movePendingTimer)
                this._movePendingTimer = 0
            }
            if (pending) {
                // Safety net — if the submitter's client dies mid-write
                // the clear never arrives; auto-release after 90s so the
                // board can't brick. The poll then re-derives from chain.
                this._movePendingTimer = setTimeout(() => {
                    this.movePending = false
                }, 90000)
            }
        })
        // Opponent's move just confirmed — re-read chain now instead of
        // waiting for the next poll tick.
        this.socket.on('refreshGameState', () => {
            this.pollTick()
        })

        // Listen to contracts for changes — gated on BLOCKCHAIN_ENABLED so
        // we don't spam the RPC every second while UI is in development.
        if (BLOCKCHAIN_ENABLED) {
            this.tezos.setStreamProvider(
                this.tezos.getFactory(PollingSubscribeProvider)({
                    shouldObservableSubscriptionRetry: true,
                    pollingIntervalMilliseconds: 1000,
                })
            )
            this.subscribeContractEvent('notPlayerTurnError', (data) => {
                console.warn('notPlayerTurnError', data)
            })
            this.subscribeContractEvent('gameNotActiveError', (data) => {
                console.warn('gameNotActiveError', data)
            })
            this.subscribeContractEvent('contractUpdated', (data) => {
                this.delayGetGamesFromContract(data.level)
            })
        }
        // Populate the lobby on mount so both players see the game list
        // immediately — no wallet required, no socket event to wait for.
        this.getGamesFromContractAsync()
        // Poll on-chain state so both clients stay in sync without anyone
        // re-clicking: the oracle's first-move flip, turn flips, and the
        // opponent's committed moves all land here. The TTT contract emits
        // no `contractUpdated` event, so the stream subscription never
        // fires for state changes — this interval is what keeps the UI live.
        this._statePoll = setInterval(() => this.pollTick(), 6000)
    },
    beforeUnmount() {
        // Unsubscribe from any contract event streams set up in created()
        for (const sub of this.streamSubs || []) {
            try { sub.removeAllListeners?.() } catch { /* noop */ }
        }
        this.streamSubs = []
        if (this._statePoll) {
            clearInterval(this._statePoll)
            this._statePoll = 0
        }
        if (this._movePendingTimer) {
            clearTimeout(this._movePendingTimer)
            this._movePendingTimer = 0
        }
    },
    methods: {
        subscribeContractEvent(tag, onData) {
            try {
                const sub = this.tezos.stream.subscribeEvent({
                    tag,
                    address: TTT_CONTRACT_ADDRESS,
                })
                sub.on('data', onData)
                this.streamSubs.push(sub)
            } catch (e) {
                console.error(`subscribeContractEvent(${tag}) failed:`, e)
            }
        },
        //Wallet Control
        async getNextBlockLevel(transactionBlockLevel){
            let currentBlock = await this.rpcclient.getBlock();
            let currentBlockLevel = await currentBlock.header.level
            const finalBlockLevel = transactionBlockLevel + this.blockWaits
            while (currentBlockLevel < finalBlockLevel) {
                let currentBlock = await this.rpcclient.getBlock();                              
                currentBlockLevel = await currentBlock.header.level 
                let bcString = 'Waiting 2 blocks at block ' + currentBlockLevel.toString() + ' / ' + finalBlockLevel.toString()
                this.blockchainStatus = bcString
            }
            this.blockchainStatus = 'Confirmed!'                  
        },
        async delayGetGamesFromContract(transactionBlockLevel){
            await this.getNextBlockLevel(transactionBlockLevel)
            this.updatePlayerControl()
            if (this.gameId == -1 && this.gameCount > 0) {
                this.gameId = this.gameCount - 1
            } else if (this.gameId == -1 && this.gameCount == 0) {
                this.gameId = 0
            }            
            await this.getGameGrid(this.gameId)
            await this.loadGameBC(this.gameId)
        }, 
        async updateConnectedUsers(connectedUsers) {
            if (connectedUsers.length == 1 ) { // reset
                this.player1Connected = 'inactive'
                this.player2Connected = 'inactive'
            }
            for (let user in connectedUsers) {
                if (this.addressesInGame.includes(connectedUsers[user])) {
                    if (this.addressesInGame.indexOf(connectedUsers[user]) == 0) {
                        this.player1Connected = 'active'
                    } else if (this.addressesInGame.indexOf(connectedUsers[user]) == 1) {
                        this.player2Connected = 'active'
                    }
                }
            }
        },
        // Interact with Smart Contract
        async createGameBC(tezAmount) {            
            this.blockchainStatus = 'Creating Game on Smart Contract'
            const activeAccount = await this.wallet.client.getActiveAccount()   
            if (!activeAccount) {
                return
            }   
            const sendAmount = tezAmount + this.fee
            if (!this.useWalletProvider()) return
            this.tezos.wallet
                .at(TTT_CONTRACT_ADDRESS)
                .then((contract) => {
                    return contract.methodsObject.startGame().send({amount: sendAmount});
                })
                .then((op) => op.confirmation().then(() => op.opHash))
                .then((opHash) => {
                    this.blockchainStatus =
                        `Game created (${String(opHash).slice(0, 12)}…) — broadcasting to players`
                    // Tell every connected client to re-fetch the
                    // contract's game list so the new game lands in
                    // their hub right away. The server rebroadcasts
                    // this with io.emit (all clients), not just us.
                    this.socket.emit('updateGames')
                })
                .catch((error) => {
                    console.error('Tezos contract call failed:', error)
                    this.blockchainStatus = 'Create game failed — see console'
                })
        },
        async joinGameBC(gameId) {
            if (gameId < 0) {
                return
            }
            const activeAccount = await this.wallet.client.getActiveAccount()
            if (!activeAccount) {
                return
            }
            // Look up the game's actual wager from contract storage. The old
            // code sent a hardcoded 1 ꜩ + fee regardless of game wager —
            // that meant joining a 5 ꜩ game would silently underfund and
            // revert (or, worse, succeed against a 0 ꜩ game and trap funds).
            const g = this.gamesObject?.[gameId]
            const gameWagerTez = g && g.tzGameBet != null
                ? Number(g.tzGameBet) / 1_000_000
                : this.wagerTez
            const sendAmount = gameWagerTez + this.fee
            this.blockchainStatus = `Joining game ${gameId} (${gameWagerTez} ꜩ wager + ${this.fee} ꜩ fee)`
            if (!this.useWalletProvider()) return
            this.tezos.wallet
                .at(TTT_CONTRACT_ADDRESS)
                .then((contract) => {
                    // joinGame's params record has a single field (gameId),
                    // which SmartPy compiles to a bare int — so it's a
                    // positional .methods call, not .methodsObject({...}).
                    return contract.methods.joinGame(Number(gameId))
                        .send({ amount: sendAmount })
                })
                .then((op) => op.confirmation().then(() => op.opHash))
                .then(() => { this.blockchainStatus = `Joined Game on Smart Contract ${gameId}` })
                .catch((error) => console.error('joinGameBC error:', error))
        },
        async leaveGameBC(gameId) {
            if (gameId < 0) {
                return
            }    
            const activeAccount = await this.wallet.client.getActiveAccount() 
            if (!activeAccount) {
                return
            }    
            this.blockchainStatus = 'Leaving Game on Smart Contract'
            if (!this.useWalletProvider()) return
            this.tezos.wallet
                .at(TTT_CONTRACT_ADDRESS)
                .then((contract) => {
                    return contract.methods.leaveGame(Number(gameId)).send()
                })
                .then((op) => op.confirmation().then(() => op.opHash))
                .then(() => { this.blockchainStatus = `Left Game on Smart Contract ${gameId}` })
                .catch((error) => console.error('leaveGameBC error:', error))
        },
        async submitMoveBC(pointToPlay, gameId) {
            // Need a vertex selected first — guard before locking anything.
            if (!Array.isArray(pointToPlay) || pointToPlay.length !== 3) {
                this.blockchainStatus = 'Select a vertex on the board first.'
                return
            }
            // Lock BOTH players the moment we submit — BEFORE any await.
            // A poll tick landing mid-submit must see movePending already
            // true, or it would re-sync the board from chain and wipe the
            // uncommitted move marker. updateMovePending + updateBCStatus
            // relay to the whole game room, so the opponent's board locks
            // and shows "writing to bc" too. The turn must not switch
            // until the chain confirms the move.
            this.movePending = true
            this.socket.emit('updateMovePending', true, gameId)
            this.socket.emit(
                'updateBCStatus',
                'Writing move to blockchain — waiting for confirmation…',
                gameId,
            )
            this.blockchainStatus = 'Writing move to blockchain — waiting for confirmation…'

            const x = pointToPlay[0] + 2 // shift to BC coords
            const y = pointToPlay[1] + 2 // shift to BC coords
            const z = pointToPlay[2] + 2 // shift to BC coords
            let bcPoint = x.toString() +  y.toString() + z.toString()
            this.bcNum = parseInt(bcPoint);
            const activeAccount = await this.wallet.client.getActiveAccount()
            if (!activeAccount) {
                // Release the lock — nothing was submitted.
                this.movePending = false
                this.socket.emit('updateMovePending', false, gameId)
                this.socket.emit('updateBCStatus', 'Sync your wallet to submit a move.', gameId)
                this.blockchainStatus = 'Sync your wallet to submit a move.'
                return
            }
            if (!this.useWalletProvider()) {
                this.movePending = false
                this.socket.emit('updateMovePending', false, gameId)
                return
            }
            await this.tezos.wallet
                .at(TTT_CONTRACT_ADDRESS)
                .then((contract) => {
                    return contract.methodsObject.makeMove({
                            gameId: gameId,
                            player: activeAccount.address,
                            move: this.bcNum
                        })
                        .send()
                })
                .then((op) => op.confirmation().then(() => op.opHash))
                .then(() => {
                    // Confirmed on-chain — now it's safe to switch turns.
                    // Clear the lock for both players, push a fresh status,
                    // and nudge both clients to re-read state so the
                    // opponent unlocks immediately (not on the next poll).
                    this.movePending = false
                    this.socket.emit('updateMovePending', false, gameId)
                    this.socket.emit('updateBCStatus', 'Move confirmed', gameId)
                    this.socket.emit('refreshGameState', gameId)
                    this.blockchainStatus = 'Move confirmed'
                    return this.pollTick()
                })
                .catch((error) => {
                    console.error('Tezos contract call failed:', error)
                    // Failed/rejected — release the lock so play can resume.
                    this.movePending = false
                    this.socket.emit('updateMovePending', false, gameId)
                    this.socket.emit('updateBCStatus', 'Move failed — try again', gameId)
                    this.blockchainStatus = 'Move failed — try again'
                })
        },
        async surrenderGameBC() {
            const activeAccount = await this.wallet.client.getActiveAccount()
            if (!activeAccount) {
                return
            }
            if (this.gameId < 0) {
                console.warn('surrenderGameBC: no active gameId')
                return
            }
            // The new contract requires { gameId } — the old call signature
            // (no params) reverted because surrenderGame referenced
            // params.gameId without declaring params.
            if (!this.useWalletProvider()) return
            await this.tezos.wallet
                .at(TTT_CONTRACT_ADDRESS)
                .then((contract) => {
                    // Single-field params record → bare int → positional
                    // .methods call (same as joinGame / leaveGame).
                    return contract.methods
                        .surrenderGame(Number(this.gameId))
                        .send()
                })
                .then((op) => op.confirmation().then(() => op.opHash))
                .then(() => { this.blockchainStatus = `Surrendered game ${this.gameId}` })
                .catch((error) => console.error('Tezos contract call failed:', error))
        },
        // The connected Beacon wallet IS the signer — Beacon proxies signing
        // requests to the user's wallet (Temple, Kukai, etc.). RemoteSigner
        // is for remote signing servers and was the wrong primitive here.
        //
        // Returns false (and sets a friendly status) when TTT_CONTRACT_ADDRESS
        // is still a KT1XXX… placeholder for the active network — feeding one
        // to tezos.wallet.at() throws an uncaught InvalidContractAddressError.
        // Every write path checks this first: `if (!this.useWalletProvider()) return`.
        useWalletProvider() {
            if (isPlaceholderAddress(TTT_CONTRACT_ADDRESS)) {
                this.blockchainStatus = 'TezTacToe is not deployed on this network yet.'
                return false
            }
            this.tezos.setWalletProvider(this.wallet)
            return true
        },
        // Reading Smart Contract
        async getGamesFromContractBC() {
            // Returns the bigmap of games, or null if the contract isn't reachable
            // (e.g. wrong network, contract not yet redeployed, RPC down).
            // Side effect: refreshes contract-wide config (houseCutBps, fee,
            // wager bounds) into reactive data.
            if (!BLOCKCHAIN_ENABLED) return null
            // Placeholder address → wallet.at() throws; short-circuit.
            if (isPlaceholderAddress(TTT_CONTRACT_ADDRESS)) return null
            try {
                const contract = await this.tezos.wallet.at(TTT_CONTRACT_ADDRESS)
                const storage = await contract.storage()
                if (storage.houseCutBps != null) {
                    this.houseCutBps = Number(storage.houseCutBps)
                }
                if (storage.fee != null) {
                    this.fee = Number(storage.fee) / 1_000_000
                }
                if (storage.minWager != null) {
                    this.minWagerTez = Number(storage.minWager) / 1_000_000
                }
                if (storage.maxWager != null) {
                    this.maxWagerTez = Number(storage.maxWager) / 1_000_000
                }
                // Clamp wager into bounds (admin may have moved them).
                if (this.wagerTez < this.minWagerTez) this.wagerTez = this.minWagerTez
                if (this.wagerTez > this.maxWagerTez) this.wagerTez = this.maxWagerTez
                return await storage.games
            } catch (err) {
                if (!this._loggedContractMissing) {
                    console.warn(
                        `[tezTacToe] contract ${TTT_CONTRACT_ADDRESS} not reachable on this network — skipping game polls. (${err.message})`
                    )
                    this._loggedContractMissing = true
                }
                this.blockchainStatus = 'Contract not deployed on this network'
                return null
            }
        },
        async getGamesFromContractAsync() {
            // The lobby is visible to everyone — populate the games list
            // whether or not a wallet is connected. myAddress drives the
            // "is this mine" badge + contextual action; per-row actions
            // prompt for a wallet on click (see lobbyAction).
            const activeAccount = await this.wallet.client
                .getActiveAccount()
                .catch(() => null)
            this.myAddress = activeAccount?.address || ''
            const gamesObject = await this.getGamesFromContract()
            this.updatePlayerControl(gamesObject)
        },
        // Periodic sync (see the interval in created()). Refreshes the
        // lobby always; when a game is loaded, also re-derives its turn
        // state and re-syncs the board to both clients.
        async pollTick() {
            try {
                await this.getGamesFromContractAsync()
                // While a move is being written to chain, don't re-derive
                // turn state — the chain hasn't advanced yet, and
                // re-emitting playable state would unlock the wrong side.
                // The post-confirmation refreshGameState fires a fresh
                // pollTick once movePending has cleared.
                if (this.movePending) return
                if (this.gameId >= 0 && this.gamesObject?.[this.gameId]) {
                    await this.updateLoadedGameStatus(this.gameId)
                    // Always re-sync the board from chain — the grid's
                    // updateGameGrid handler re-stamps any tentative pick
                    // on top, so a sync can't wipe an uncommitted move,
                    // and the player who just got the turn still sees the
                    // opponent's committed move right away.
                    await this.getGameGrid(this.gameId)
                }
            } catch (e) {
                // Best-effort poll — next tick retries.
            }
        },
        async getGamesFromContract() {
            const games = await this.getGamesFromContractBC()
            if (!games) return {}
            const allGames = await games.values()
            let gamesObject = {}
            let j = 0;
            for (let game of allGames) {
                const players = await game.players.values()
                let gameData = {}
                gameData['gameId'] = j
                // Read metaData by KEY, not by index. The map's value
                // order is the contract's (alphabetical) key order, so an
                // index-based read silently shifts the moment a key is
                // added — which is exactly what happened when the contract
                // gained "firstMoveDecided". We iterate .entries() to build
                // a plain {key: number} object — Taquito's MichelsonMap.get()
                // is unreliable for string keys here, but .entries() (the
                // same iterator .values() used) is solid.
                const meta = {}
                const rawMeta = game.metaData
                if (rawMeta && typeof rawMeta.entries === 'function') {
                    for (const [k, v] of rawMeta.entries()) {
                        meta[k] = Number(v && v.toNumber ? v.toNumber() : v) || 0
                    }
                }
                gameData['gameStatus'] = meta['gameStatus'] || 0
                gameData['player1Paid'] = meta['player1Paid'] || 0
                gameData['player2Paid'] = meta['player2Paid'] || 0
                gameData['playerTurn'] = meta['playerTurn'] || 0
                gameData['winningPlayer'] = meta['winningPlayer'] || 0
                gameData['firstMoveDecided'] = meta['firstMoveDecided'] || 0
                let playerList = []
                for (let player of players) {
                    playerList.push(player)
                }
                gameData['players'] = playerList
                gameData['grid'] = await game.grid
                // New per-game gambling fields. Defensive accessors so the
                // UI tolerates contracts deployed before these were added.
                if (game.tzGameBet != null) {
                    gameData['tzGameBet'] = Number(game.tzGameBet?.toNumber
                        ? game.tzGameBet.toNumber()
                        : game.tzGameBet)
                }
                if (game.houseCutBps != null) {
                    gameData['houseCutBps'] = Number(game.houseCutBps?.toNumber
                        ? game.houseCutBps.toNumber()
                        : game.houseCutBps)
                }
                gamesObject[j] = gameData
                j ++;
            }
            this.gameCount = j
            this.gamesObject = await gamesObject
            return gamesObject
        },
        async loadGameBC(gameId) {
            if (gameId < 0) {
                return
            }
            // Switching games — drop any first-move state from the prior
            // game so the flip feedback doesn't bleed across.
            if (gameId !== this.gameId) {
                this.awaitingFlip = false
                this.firstMoveWinner = 0
            }
            this.blockchainStatus = 'Loading Game from Smart Contract'
            const activeAccount = await this.wallet.client.getActiveAccount()
            if (!activeAccount) {
                return
            }
            this.socket.emit("setUserActiveGameRoom", activeAccount.address, this.gameCount, gameId)
            await this.updateLoadedGameStatus(gameId)
            this.socket.emit("updatePlayedPoint", 'NO MOVE', 'Active', this.gameId)
            this.socket.emit('loadGame', gameId, false)   
            this.socket.emit('resizeGameGrid', window.inner)            
            this.blockchainStatus = `Game ${gameId} loaded`  
        },
        async getGameGrid(gameId, updateGrid=true) {
            let loadedGridPoints = []
            await this.getGamesFromContract()
            const game = await this.gamesObject[gameId].grid
            let n = 0;
            for (let gridPoint of game.valueMap) {
                loadedGridPoints[n] = gridPoint[1].c[0]
                n ++;
            }
            let gameGrid = {}
            let i = -1;
            n = 0
            for (i; i < 3; i++) {
                let j = -1
                if (!gameGrid[i]) {
                gameGrid[i] = {}
                }
                for (j; j < 3; j++) {
                    if (!gameGrid[i][j]) {
                    gameGrid[i][j] = {}
                    }
                    let k = -1
                    for (k; k < 3; k++) {  
                        gameGrid[i][j][k] = loadedGridPoints[n]
                        n ++;
                    }
                }
            }
            this.socket.emit("updateGameGrid", gameGrid, gameId, updateGrid)
        },
        // Contextual lobby action — Join / Play / View / Leave, dispatched
        // from a game row. Read-only View needs no wallet; the rest prompt
        // for a wallet sync on click rather than silently no-op'ing.
        async lobbyAction(g) {
            if (!g || !g.action) return
            this.gameId = g.id
            if (g.action === 'view') {
                this.loadGameBC(g.id)
                return
            }
            const activeAccount = await this.wallet.client
                .getActiveAccount()
                .catch(() => null)
            if (!activeAccount) {
                this.blockchainStatus = `Sync your wallet to ${g.action} game ${g.id}.`
                return
            }
            if (g.action === 'join') {
                this.joinGameBC(g.id)
            } else if (g.action === 'leave') {
                this.leaveGameBC(g.id)
            } else if (g.action === 'play') {
                this.loadGameBC(g.id)
            }
        },
             // Populating the page
             async togglePlayer(){
            const activeAccount = await this.wallet.client.getActiveAccount()  
            if (!activeAccount) {                  
                return         
            } 
            if (this.playerTurn == 1) {
                this.socket.emit('updatePlayerTurn', 2, this.addressesInGame, activeAccount.address, this.gameId)
                this.playerTurn = 2
            } else if (this.playerTurn == 2) {
                this.socket.emit('updatePlayerTurn', 1, this.addressesInGame, activeAccount.address, this.gameId)
                this.playerTurn = 1
            }
        },
        async updatePlayerControl(gamesObject) {
            if (!gamesObject) {
                gamesObject = await this.getGamesFromContract()
            }
            const activeAccount = await this.wallet.client.getActiveAccount()   
            if (!activeAccount) {
                gamesObject = {}
                this.loadedGames = false
                return
            }  
            this.gameCount = Object.keys(gamesObject).length
            let i = 0
            this.allGamesStatus = {}       
            this.joinableGames = false   
            this.leavableGames = false 
            this.viewableGames = false   
            for (i; i < this.gameCount; i++) {
                if (gamesObject[i].players.includes(activeAccount.address)) {
                    this.allGamesStatus[i] = gamesObject[i].gameStatus
                    if (gamesObject[i].gameStatus == 3 ) {
                        this.viewableGames = true
                    } else if (gamesObject[i].gameStatus == 1 ) {
                        this.leavableGames = true
                    }
                } else if (gamesObject[i].gameStatus <= 1 ) {
                    this.allGamesStatus[i] = 4
                    this.joinableGames = true
                } else {
                    this.allGamesStatus[i] = 6
                }                    
            }    
            if (Object.keys(this.allGamesStatus).length > 0 ) {
                this.loadedGames = true
            } else {
                this.loadedGames = false
            }
        },
        async updateLoadedGameStatus(gameId) {
            const activeAccount = await this.wallet.client.getActiveAccount()   
            if (!activeAccount) {
                return
            }  
            if (!this.gamesObject) {
                return
            }
            const game = await this.gamesObject[gameId]
            this.gameId = game.gameId
            this.socket.emit("updateGameId", this.gameId)
            this.socket.emit("updatePlayersInGame", game.players, this.gameId)
            this.addressesInGame = game.players
            if (game.gameStatus == 1 ) {
                this.pendingGame = gameId
                this.gameStatus = 'Pending'
                this.playersInGame = [await reduceAddress(game.players[0]), 'None']
                this.playerTurnStr = 'NA'
            } else if (game.gameStatus == 2 ) {
                this.gameStatus = 'None'
                this.gameId = await game.gameId
                this.walletPlayerTurn1 = await reduceAddress(game.players[0])
                this.walletPlayerTurn2 = await reduceAddress(game.players[1])
                this.playersInGame = [this.walletPlayerTurn1, this.walletPlayerTurn2]
                this.playerTurn = game.playerTurn
                this.socket.emit('updateConnectedUsersInGame', activeAccount.address, this.gameId)
                if (game.firstMoveDecided !== 1) {
                    // Paired, but the oracle hasn't flipped for first move
                    // yet — the board is not playable for either side.
                    this.awaitingFlip = true
                    this.playerTurnStr = 'COIN FLIP'
                    this.blockchainStatus =
                        'Both players in — waiting for the oracle to flip for first move'
                    this.socket.emit('updatePlayerTurn', this.playerTurn, this.gameId)
                    this.socket.emit('updateGamePlayable', false, this.gameId)
                } else {
                    // The flip resolved. The first time we observe it (we
                    // were watching the awaitingFlip state), playerTurn is
                    // the flip winner — no moves have been made yet — so
                    // capture it for the "who won first move" feedback.
                    if (this.awaitingFlip) {
                        this.firstMoveWinner = this.playerTurn
                    }
                    this.awaitingFlip = false
                    this.socket.emit('updatePlayerTurn', this.playerTurn, this.gameId)
                    this.blockchainStatus = 'Active'
                    if (game.players[this.playerTurn - 1] == activeAccount.address) {
                        this.playerTurnStr = 'YOUR TURN'
                        this.socket.emit('updateGamePlayable', true, this.gameId)
                    } else {
                        this.playerTurnStr = 'OPP TURN'
                        this.socket.emit('updateGamePlayable', false, this.gameId)
                    }
                }
            } else if (game.gameStatus > 2) {
                this.awaitingFlip = false
                this.playerTurnStr = 'GAME OVER'
                this.socket.emit('updateGamePlayable', false, this.gameId)
            }
        },
        async showLearnMore() {
            if (this.showInfo)  {
                this.showInfo = false
            } else {
                this.showInfo = true
            }
        }
    }
}

</script>

<template>
        <!-- ── Current-game status — above the board so both players see
             whose turn it is + the game state before the grid. Both
             clients read the same on-chain state, so this bar shows the
             same thing to both (only the turn badge label differs by
             which side is reading it). ───────────────────────────────── -->
        <div class="rowFlex tttStatusBar">
            <div class="gameInfo">Game #{{ gameId }}</div>
            <div class="gameInfo">
                {{ playersInGame[0] }} {{ player1Connected }}
                vs {{ playersInGame[1] }} {{ player2Connected }}
            </div>
            <div :class="['tttTurnBadge', turnBadge.cls]">{{ turnBadge.label }}</div>
        </div>

        <!-- Oracle first-move flip feedback. -->
        <div v-if="awaitingFlip" class="tttFlipLine tttFlipLine--pending">
            <span class="tttFlipDot"></span>
            Both players in — the oracle is flipping for first move…
        </div>
        <div v-else-if="firstMoveLine" class="tttFlipLine">
            {{ firstMoveLine }}
        </div>

        <!-- Per-game pot summary (only when a game is loaded with a wager) -->
        <div v-if="loadedGameWagerTez > 0" class="tttPotLine">
            Wager: <strong>{{ loadedGameWagerTez.toFixed(3) }} ꜩ</strong> each
            · Pot: <strong>{{ loadedGameGrossPotTez.toFixed(3) }} ꜩ</strong>
            · House keeps <strong>{{ loadedGameHouseCutTez.toFixed(4) }} ꜩ</strong>
            ({{ (loadedGameHouseCutBps / 100).toFixed(2) }}%)
            → Winner takes <strong>{{ loadedGameNetPotTez.toFixed(3) }} ꜩ</strong>
        </div>

        <div class="rowFlex">
            <div class="gameInfo" > Status: {{ blockchainStatus }}</div>
        </div>

        <!-- ── Game area: board + per-game controls ──────────────────── -->
        <tttGameGrid
            :wallet="wallet"
            :socket="socket"
            :tezos="tezos"
        />
        <div class="rowFlex" >
            <div class="actionButton" @click="submitMoveBC(pointToPlay, gameId)" > Submit Move </div>
            <div class="actionButton" @click="surrenderGameBC" > Surrender </div>
            <div class="actionButtonHelp" @click="showLearnMore"> HOW TO PLAY </div>
        </div>
        <div class="infoPopup" v-if="showInfo" @click="showLearnMore" >
            <div>
            <ul>
              <li class="listItem" v-for="(key, value) in gameInfo" :key="key" :value="value">{{ key }}</li>
            </ul>
            </div>
        </div>

        <!-- ── Game lobby — every game, visible to both players ───────── -->
        <div class="tttLobby">
            <div class="tttLobbyHead">
                <span class="tttLobbyTitle">GAME LOBBY</span>
                <span class="tttLobbyCount">
                    {{ lobbyGames.length }} game{{ lobbyGames.length === 1 ? '' : 's' }}
                </span>
                <div class="actionButtonHelp tttLobbyRefresh" @click="getGamesFromContractAsync">
                    Refresh
                </div>
            </div>
            <div v-if="!lobbyGames.length" class="gameInfo tttLobbyEmpty">
                No games yet — set a wager below and start one.
            </div>
            <div v-else class="tttLobbyList">
                <div
                    v-for="g in lobbyGames"
                    :key="g.id"
                    :class="[
                        'tttLobbyRow',
                        g.isMine ? 'tttLobbyRow--mine' : '',
                        gameId === g.id ? 'tttLobbyRow--active' : '',
                    ]"
                >
                    <span class="tttLobbyId">#{{ g.id }}</span>
                    <span :class="['tttLobbyStatus', g.statusClass]">{{ g.statusLabel }}</span>
                    <span class="tttLobbyPlayers">
                        {{ g.p1 }} <span class="tttLobbyVs">vs</span> {{ g.p2 }}
                        <span v-if="g.isMine" class="tttLobbyMine">you</span>
                    </span>
                    <span class="tttLobbyWager">{{ g.wagerLabel }}</span>
                    <div
                        v-if="g.action"
                        :class="['actionButton', 'tttLobbyAction']"
                        @click="lobbyAction(g)"
                    >{{ g.actionLabel }}</div>
                    <span v-else class="tttLobbyNoAction">—</span>
                </div>
            </div>
        </div>

        <!-- ── Wager card (gambling + house cut) — below the game area ─ -->
        <div class="tttWagerCard">
            <div class="tttWagerHead">
                <div class="tttWagerTitle">Set your wager</div>
                <div class="tttWagerHint">
                    min {{ minWagerTez.toFixed(2) }} ꜩ · max {{ maxWagerTez.toFixed(2) }} ꜩ ·
                    house cut {{ houseCutPercent }}%
                </div>
            </div>
            <div class="tttWagerRow">
                <input
                    type="range"
                    class="tttWagerSlider"
                    :min="minWagerTez"
                    :max="maxWagerTez"
                    step="0.05"
                    v-model.number="wagerTez"
                />
                <div class="tttWagerValue">{{ wagerTez.toFixed(3) }} {{ tezosSymbol }}</div>
            </div>
            <div class="tttWagerMath">
                <div class="tttMathRow">
                    <span class="tttMathLabel">You lock</span>
                    <span class="tttMathValue">{{ wagerTez.toFixed(3) }} ꜩ + {{ fee.toFixed(2) }} ꜩ fee</span>
                </div>
                <div class="tttMathRow">
                    <span class="tttMathLabel">Pot if matched</span>
                    <span class="tttMathValue">{{ sliderGrossPotTez.toFixed(3) }} ꜩ</span>
                </div>
                <div class="tttMathRow">
                    <span class="tttMathLabel">House keeps</span>
                    <span class="tttMathValue tttMathValue--house">
                        {{ sliderHouseCutTez.toFixed(4) }} ꜩ ({{ houseCutPercent }}%)
                    </span>
                </div>
                <div class="tttMathRow tttMathRow--strong">
                    <span class="tttMathLabel">Winner takes</span>
                    <span class="tttMathValue tttMathValue--win">
                        {{ sliderNetPotTez.toFixed(3) }} ꜩ
                    </span>
                </div>
            </div>
        </div>

        <div class="rowFlex">
            <div class="actionButton" @click="createGameBC(wagerTez)">
                New {{ wagerTez.toFixed(2) }}{{ tezosSymbol }} Game
            </div>
            <div class="actionButtonHelp" @click="wagerTez = 0">0</div>
            <div class="actionButtonHelp" @click="wagerTez = 0.5">0.5</div>
            <div class="actionButtonHelp" @click="wagerTez = 1">1</div>
            <div class="actionButtonHelp" @click="wagerTez = 5">5</div>
            <div class="actionButtonHelp" @click="wagerTez = 10">10</div>
        </div>

</template>

<style scoped>
.tttWagerCard {
    margin: 8px 4px 12px;
    padding: 12px 14px;
    border-radius: 12px;
    background: linear-gradient(135deg, rgba(245, 196, 81, 0.08) 0%, rgba(245, 196, 81, 0.02) 100%);
    border: 1px solid rgba(245, 196, 81, 0.30);
    box-shadow: inset 0 0 0 1px rgba(0, 0, 0, 0.18);
    color: #efeae2;
    font-family: 'EB Garamond', serif;
}
.tttWagerHead {
    display: flex; justify-content: space-between; align-items: baseline;
    margin-bottom: 10px; flex-wrap: wrap; gap: 4px;
}
.tttWagerTitle {
    font-size: 13px; letter-spacing: 2px; text-transform: uppercase;
    color: #f5c451; font-weight: 700;
}
.tttWagerHint { font-size: 11px; color: rgba(255, 255, 255, 0.55); }
.tttWagerRow { display: flex; align-items: center; gap: 12px; }
.tttWagerSlider {
    flex: 1; appearance: none; height: 5px;
    background: rgba(255, 255, 255, 0.15); border-radius: 4px; outline: none;
}
.tttWagerSlider::-webkit-slider-thumb {
    appearance: none; width: 18px; height: 18px; border-radius: 50%;
    background: #f5c451; cursor: pointer;
    box-shadow: 0 0 6px rgba(245, 196, 81, 0.7);
}
.tttWagerSlider::-moz-range-thumb {
    width: 18px; height: 18px; border-radius: 50%;
    background: #f5c451; cursor: pointer; border: none;
}
.tttWagerValue {
    min-width: 90px; text-align: right;
    font-size: 17px; font-weight: 700; color: #fff;
}
.tttWagerMath {
    margin-top: 12px; padding-top: 10px;
    border-top: 1px dashed rgba(245, 196, 81, 0.25);
}
.tttMathRow {
    display: flex; justify-content: space-between;
    padding: 2px 0; font-size: 12px;
    color: rgba(255, 255, 255, 0.78);
}
.tttMathRow--strong {
    font-size: 13px; padding-top: 6px; margin-top: 4px;
    border-top: 1px solid rgba(255, 255, 255, 0.08);
}
.tttMathLabel {
    letter-spacing: 1px; text-transform: uppercase; font-size: 10px;
    color: rgba(255, 255, 255, 0.55);
}
.tttMathValue { font-weight: 600; }
.tttMathValue--house { color: rgba(229, 121, 121, 0.95); }
.tttMathValue--win { color: #b9e6a3; font-size: 14px; }

.tttPotLine {
    margin: 6px 4px;
    padding: 6px 10px;
    border-radius: 8px;
    background: rgba(255, 255, 255, 0.04);
    border: 1px solid rgba(255, 255, 255, 0.08);
    color: rgba(255, 255, 255, 0.78);
    font-family: 'EB Garamond', serif;
    font-size: 12px;
}
.tttPotLine strong { color: #f5c451; }

/* ── Game lobby ──────────────────────────────────────────────────── */
.tttLobby {
    margin: 12px 4px;
    padding: 12px 14px;
    border-radius: 12px;
    background: rgba(255, 255, 255, 0.03);
    border: 1px solid rgba(255, 255, 255, 0.08);
    font-family: 'EB Garamond', serif;
    color: #efeae2;
}
.tttLobbyHead {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 10px;
}
.tttLobbyTitle {
    font-size: 13px;
    letter-spacing: 2px;
    text-transform: uppercase;
    color: #f5c451;
    font-weight: 700;
}
.tttLobbyCount {
    font-size: 11px;
    color: rgba(255, 255, 255, 0.5);
}
.tttLobbyRefresh {
    margin-left: auto;
    flex: 0 0 auto;
}
.tttLobbyEmpty {
    font-size: 12px;
    color: rgba(255, 255, 255, 0.55);
}
.tttLobbyList {
    display: flex;
    flex-direction: column;
    gap: 5px;
    max-height: 280px;
    overflow-y: auto;
}
.tttLobbyRow {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 7px 10px;
    border-radius: 8px;
    background: rgba(0, 0, 0, 0.3);
    border: 1px solid rgba(255, 255, 255, 0.07);
    font-size: 13px;
}
.tttLobbyRow--mine {
    border-color: rgba(245, 196, 81, 0.4);
    background: rgba(245, 196, 81, 0.06);
}
.tttLobbyRow--active {
    box-shadow: inset 0 0 0 1px rgba(245, 196, 81, 0.7);
}
.tttLobbyId {
    font-weight: 700;
    color: rgba(255, 255, 255, 0.6);
    min-width: 34px;
}
.tttLobbyStatus {
    font-size: 10px;
    letter-spacing: 1px;
    text-transform: uppercase;
    font-weight: 700;
    padding: 2px 7px;
    border-radius: 10px;
    white-space: nowrap;
}
.tttStatus--open  { background: rgba(118, 196, 138, 0.18); color: #8fe0a6; }
.tttStatus--live  { background: rgba(245, 196, 81, 0.18);  color: #f5c451; }
.tttStatus--flip  { background: rgba(79, 108, 196, 0.20);  color: #aebdf0; }
.tttStatus--done  { background: rgba(150, 150, 150, 0.18); color: #c8c8c8; }
.tttStatus--dead  { background: rgba(196, 82, 79, 0.18);   color: #ff908d; }
.tttStatus--other { background: rgba(255, 255, 255, 0.1);  color: #bbb; }

/* ── Current-game status bar + turn badge ────────────────────────── */
.tttStatusBar { align-items: center; }
.tttTurnBadge {
    margin-left: auto;
    flex: 0 0 auto;
    padding: 5px 14px;
    border-radius: 8px;
    font-size: 13px;
    font-weight: 700;
    letter-spacing: 1.5px;
    text-transform: uppercase;
    border: 1px solid transparent;
}
.turnYou {
    background: rgba(118, 196, 138, 0.20);
    color: #8fe0a6;
    border-color: rgba(118, 196, 138, 0.6);
    box-shadow: 0 0 10px rgba(118, 196, 138, 0.35);
}
.turnOpp {
    background: rgba(255, 255, 255, 0.05);
    color: rgba(255, 255, 255, 0.6);
    border-color: rgba(255, 255, 255, 0.15);
}
.turnFlip {
    background: rgba(79, 108, 196, 0.20);
    color: #aebdf0;
    border-color: rgba(79, 108, 196, 0.6);
    animation: tttFlipPulse 1.3s ease-in-out infinite;
}
.turnNone {
    background: rgba(255, 255, 255, 0.04);
    color: rgba(255, 255, 255, 0.45);
    border-color: rgba(255, 255, 255, 0.1);
}
@keyframes tttFlipPulse {
    0%, 100% { opacity: 0.55; }
    50% { opacity: 1; }
}

/* ── First-move oracle flip line ─────────────────────────────────── */
.tttFlipLine {
    margin: 0 4px 6px;
    padding: 6px 12px;
    border-radius: 8px;
    background: rgba(245, 196, 81, 0.07);
    border: 1px solid rgba(245, 196, 81, 0.30);
    color: #f5c451;
    font-size: 12px;
    font-family: 'EB Garamond', serif;
}
.tttFlipLine--pending {
    display: flex;
    align-items: center;
    gap: 8px;
    background: rgba(79, 108, 196, 0.10);
    border-color: rgba(79, 108, 196, 0.45);
    color: #aebdf0;
}
.tttFlipDot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: #5d80e4;
    box-shadow: 0 0 6px rgba(93, 128, 228, 0.9);
    animation: tttFlipPulse 1.3s ease-in-out infinite;
}
.tttLobbyPlayers {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: rgba(255, 255, 255, 0.85);
}
.tttLobbyVs {
    color: rgba(255, 255, 255, 0.4);
    font-size: 11px;
    margin: 0 2px;
}
.tttLobbyMine {
    margin-left: 6px;
    font-size: 9px;
    letter-spacing: 1px;
    text-transform: uppercase;
    color: #0e1116;
    background: #f5c451;
    border-radius: 8px;
    padding: 1px 6px;
    font-weight: 700;
}
.tttLobbyWager {
    flex: 0 0 auto;
    font-variant-numeric: tabular-nums;
    color: #f5c451;
    font-weight: 700;
}
.tttLobbyAction {
    flex: 0 0 auto;
    min-width: 64px;
    text-align: center;
}
.tttLobbyNoAction {
    flex: 0 0 auto;
    min-width: 64px;
    text-align: center;
    color: rgba(255, 255, 255, 0.3);
}
@media (max-width: 480px) {
    .tttLobbyRow { flex-wrap: wrap; }
    .tttLobbyPlayers { flex-basis: 100%; order: 5; }
}
</style>