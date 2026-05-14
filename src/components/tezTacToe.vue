<script>
import { PollingSubscribeProvider } from '@taquito/taquito'
import { RpcClient } from '@taquito/rpc'
import tttGameGrid from './tttGameGrid.vue'
import { NODE_URL, TTT_CONTRACT_ADDRESS, GAME_INFO, BLOCKCHAIN_ENABLED } from '../constants'
import { reduceAddress } from '../utilities'

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
            leaveGameId: 'NA',
            leavableGames: false,
            playGameId: 'NA',
            joinGameId: 'NA',
            joinableGames: false,
            viewGameId: 'NA',
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
    },
    beforeUnmount() {
        // Unsubscribe from any contract event streams set up in created()
        for (const sub of this.streamSubs || []) {
            try { sub.removeAllListeners?.() } catch { /* noop */ }
        }
        this.streamSubs = []
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
            this.useWalletProvider()
            this.tezos.wallet
                .at(TTT_CONTRACT_ADDRESS)
                .then((contract) => {
                    return contract.methodsObject.startGame().send({amount: sendAmount});
                })
                .then((op) => op.confirmation().then(() => op.opHash))
                .catch((error) => console.error('Tezos contract call failed:', error))
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
            this.useWalletProvider()
            this.tezos.wallet
                .at(TTT_CONTRACT_ADDRESS)
                .then((contract) => {
                    return contract.methodsObject.joinGame({ gameId })
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
            this.useWalletProvider()
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
            this.socket.emit("updateGamePlayable", false, gameId)   
            this.blockchainStatus = 'Submitting Move to Smart Contract'     
            const x = pointToPlay[0] + 2 // shift to BC coords
            const y = pointToPlay[1] + 2 // shift to BC coords
            const z = pointToPlay[2] + 2 // shift to BC coords
            let bcPoint = x.toString() +  y.toString() + z.toString()
            this.bcNum = parseInt(bcPoint);
            const activeAccount = await this.wallet.client.getActiveAccount()   
            if (!activeAccount) {
                return
            }    
            this.useWalletProvider()
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
                .catch((error) => console.error('Tezos contract call failed:', error))
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
            this.useWalletProvider()
            await this.tezos.wallet
                .at(TTT_CONTRACT_ADDRESS)
                .then((contract) => {
                    return contract.methodsObject
                        .surrenderGame({ gameId: this.gameId })
                        .send()
                })
                .then((op) => op.confirmation().then(() => op.opHash))
                .then(() => { this.blockchainStatus = `Surrendered game ${this.gameId}` })
                .catch((error) => console.error('Tezos contract call failed:', error))
        },
        // The connected Beacon wallet IS the signer — Beacon proxies signing
        // requests to the user's wallet (Temple, Kukai, etc.). RemoteSigner
        // is for remote signing servers and was the wrong primitive here.
        useWalletProvider() {
            this.tezos.setWalletProvider(this.wallet)
        },
        // Reading Smart Contract
        async getGamesFromContractBC() {
            // Returns the bigmap of games, or null if the contract isn't reachable
            // (e.g. wrong network, contract not yet redeployed, RPC down).
            // Side effect: refreshes contract-wide config (houseCutBps, fee,
            // wager bounds) into reactive data.
            if (!BLOCKCHAIN_ENABLED) return null
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
            const activeAccount = await this.wallet.client.getActiveAccount()
            if (!activeAccount) {
                this.loadedGames = false
                this.updatePlayerControl({})
                return
            }
            const gamesObject = await this.getGamesFromContract()
            this.updatePlayerControl(gamesObject)
        },
        async getGamesFromContract() {
            const games = await this.getGamesFromContractBC()
            if (!games) return {}
            const allGames = await games.values()
            let gamesObject = {}
            let j = 0;
            for (let game of allGames) {
                const players = await game.players.values()
                const metaData = await game.metaData.values()
                let i = 0;
                let gameData = {}
                gameData['gameId'] = j
                for (let data of metaData) {
                    if (i == 0) {
                        gameData['gameStatus'] = data.toNumber()
                    } else if (i == 1) {
                        gameData['player1Paid'] = data.toNumber()
                    } else if (i == 2) {
                        gameData['player2Paid'] = data.toNumber()
                    } else if (i == 3) {
                        gameData['playerTurn'] = data.toNumber()
                    }
                    i++;
                }    
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
        async updateGame(gameId, type) {
            this.gameId = gameId
            if (type == 'play') {
                this.playGameId = gameId
            } else if (type == 'join') {
                this.joinGameId = gameId
            } else if (type == 'leave') {
                this.leaveGameId = gameId
            } else if (type == 'view') {
                this.viewGameId = gameId
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
                this.playerTurn = await game.playerTurn
                this.socket.emit('updatePlayerTurn', this.playerTurn, this.gameId)
                this.socket.emit('updateConnectedUsersInGame', activeAccount.address, this.gameId)
                this.blockchainStatus = 'Active'
                if (game.players[this.playerTurn - 1] == activeAccount.address) {
                    this.playerTurnStr = 'YOUR TURN'
                    this.socket.emit('updateGamePlayable', true, this.gameId)
                } else {
                    this.playerTurnStr = 'OPP TURN'
                    this.socket.emit('updateGamePlayable', false, this.gameId)
                }
            } else if (game.gameStatus > 2) {
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
        <div class="rowFlex">
            <div class="actionButtonHelp" @click="showLearnMore"> HOW TO PLAY </div>
            <div class="infoPopup" v-if="showInfo" @click="showLearnMore" >
            <div>
            <ul>
              <li class="listItem" v-for="(key, value) in gameInfo" :key="key" :value="value">{{ key }}</li>
            </ul>
            </div>
            </div>
        </div>

        <!-- ── Wager card (gambling + house cut) ─────────────────────── -->
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
        <div class="rowFlex">
            <div class="gameInfo"> MY GAME HUB </div>
        </div>
        <div class="rowFlex" v-if="loadedGames" > 
            <div class="gameCenter" v-if="joinableGames" >   
                <div class="actionButton" @click="loadGameBC(playGameId)"> Play Game: {{ playGameId }} </div>                                       
                <div> 
                    <div class="rowFlex">                                                       
                        <div  v-for="(key, value) in allGamesStatus" :key="key" :value="value"> 
                            <div v-if="key==2" class="gameSelect" @click="updateGame(value, 'play')"> {{value}} </div>                  
                        </div>
                    </div>
                </div>   
            </div>
            <div class="gameCenter" v-if="joinableGames">  
                <div class="actionButton" @click="joinGameBC(gameId)">   Join Game: {{ joinGameId }}  </div>                                   
                <div> 
                    <div class="rowFlex">                                                     
                        <div v-for="(key, value) in allGamesStatus" :key="key" :value="value"> 
                            <div v-if="key==4" class="gameSelect" @click="updateGame(value, 'join')"> {{value}} </div>                  
                        </div>
                    </div>                       
                </div>
            </div>
            <div class="gameCenter" v-if="leavableGames"> 
                <div class="actionButton" @click="leaveGameBC(gameId)">  Leave Game: {{ leaveGameId }} </div>                             
                <div> 
                    <div class="rowFlex">                                
                        <div  v-for="(key, value) in allGamesStatus" :key="key" :value="value"> 
                            <div v-if="key==1" class="gameSelect" @click="updateGame(value, 'leave')"> {{value}} </div>                  
                        </div>
                    </div>
                </div>                   
            </div>
            <div class="gameCenter" v-if="viewableGames"> 
                <div class="actionButton" @click="loadGameBC(gameId)">   View Game: {{ viewGameId }} </div>                              
                <div> 
                    <div class="rowFlex">                                
                        <div v-for="(key, value) in allGamesStatus" :key="key" :value="value"> 
                            <div v-if="key==3" class="gameSelect" @click="updateGame(value, 'view')"> {{value}} </div>                  
                        </div>
                    </div>
                </div>                   
            </div>    
        </div>

        <tttGameGrid 
            :wallet="wallet"
            :socket="socket"
            :tezos="tezos"
        />
        <div class="rowFlex" >     
            <div class="actionButton" @click="submitMoveBC(pointToPlay, gameId)" > Submit Move </div>
            <div class="actionButton" @click="surrenderGameBC" > Surrender </div>                
        </div>

        <div class="rowFlex" >
            <div class="gameInfo" > Game ID: {{ gameId }}</div>
            <div class="gameInfo" > {{ playersInGame[0] }} {{player1Connected}} vs. {{ playersInGame[1]}} {{player2Connected}} </div>
            <div class="gameInfo" > {{ playerTurnStr }}</div>
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
</style>