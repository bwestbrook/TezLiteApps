<script>
import { PollingSubscribeProvider } from '@taquito/taquito';
import { RemoteSigner } from '@taquito/remote-signer';
import tttGameGrid  from './tttGameGrid.vue'
//import sha256 from 'js-sha256'
import { RpcClient } from '@taquito/rpc';
import { NODE_URL, CONTRACT_ADDRESS} from '../constants'
import { reduceAddress } from "../utilities";


export default {
    name: "playerControl",
    emits: [
    ],
    components: { 
        tttGameGrid
    },
    props: ["socket", "wallet", "tezos"],
    data () {
        return {
            showTezTactoe: true,
            showAceyDuecey: false,
            allGamesStatus: {},
            gamesObject: {},
            gameId: -1,
            leaveGameId: 'NA',
            playGameId: 'NA',
            joinGameId: 'NA',
            viewGameId: 'NA', 
            blockWaits: '',
            gameStatus: 'No Players',
            playerTurnStr: 'No Game',
            playerTurn: -1, 
            playersInGame: '',
            player1Connected: '',
            player2Connected: '',
            addressesInGame: [],
            blockchainStatus: 'No Activity',
            pointToPlay: 'XXX',
            playerGames: [],
            pendingGamesOthers: []

        }
    },
    created() {
        this.rpcclient = new RpcClient(NODE_URL, 'NetXnHfVqm9iesp');
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

        // Listen to contracts for changes
        this.tezos.setStreamProvider(
            this.tezos.getFactory(PollingSubscribeProvider)({
                shouldObservableSubscriptionRetry: true,
                pollingIntervalMilliseconds: 1000
            })
        );
        try {
            const sub = this.tezos.stream.subscribeEvent({
                tag: 'notPlayerTurnError',
                address: CONTRACT_ADDRESS,
                //excludeFailedOperations: true
            });
            sub.on('data', (data) => {
                //const transactionBlockLevel = data.level
                console.log('notPlayerTurnError: ', data)
            })
            } catch (e) {
            console.log(e);
        }
        try {
            const sub = this.tezos.stream.subscribeEvent({
                tag: 'gameNotActiveError',
                address: CONTRACT_ADDRESS,
                //excludeFailedOperations: true
            });
            sub.on('data', (data) => {
                //const transactionBlockLevel = data.level
                console.log('gameNotActiveError: ', data)
            })
            } catch (e) {
            console.log(e);
        }
        try {
            const sub = this.tezos.stream.subscribeEvent({
              tag: 'contractUpdated',
              address: CONTRACT_ADDRESS,
              //excludeFailedOperations: true
            });
            sub.on('data', (data) => {
                const transactionBlockLevel = data.level
                this.delayGetGamesFromContract(transactionBlockLevel)                
            })
          } catch (e) {
            console.log(e);
          }
    },
    mounted() {
    },
    methods: {
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
                return
            }  
            let i = 0
            this.allGamesStatus = {}            
            for (i; i < this.gameCount; i++) {
                if (gamesObject[i].players.includes(activeAccount.address)) {
                    this.allGamesStatus[i] = gamesObject[i].gameStatus
                } else if (gamesObject[i].gameStatus == 1 ) {
                    this.allGamesStatus[i] = 4
                } else {
                    this.allGamesStatus[i] = 6
                }                    
                
            }      
            this.pendingGamesOthers = this.allGamesStatus[6]
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
            const feeAmount = tezAmount * 0.95 
            const tzSurrenderAmount = Math.floor(0.25 * feeAmount * 1e6)
            const tzSurrenderOtherAmount =  Math.ceil(0.75 * feeAmount * 1e6)
            this.getSigner(activeAccount)
            this.tezos.wallet
                .at(CONTRACT_ADDRESS)
                .then((contract) => {
                    return contract.methodsObject.startGame({
                            tzSurrenderAmount: tzSurrenderAmount,
                            tzSurrenderOtherAmount: tzSurrenderOtherAmount
                        }).send({amount: tezAmount});
                })
                .then((op) => {
                    console.log(`Waiting for ${op.opHash} to be confirmed...`);
                    return op.confirmation().then(() => op.opHash);
                })
                .then((hash) => console.log(`Operation injected: https://ghost.tzstats.com/${hash}`))
                .catch((error) => console.log(`Error3: ${JSON.stringify(error, null, 2)}`));
            
        },
        async joinGameBC(gameId) { 
            if (gameId < 0) {
                return
            }    
            const activeAccount = await this.wallet.client.getActiveAccount() 
            if (!activeAccount) {
                return
            }    
            this.blockchainStatus = 'Joining Game on Smart Contract'              
            this.getSigner(activeAccount)  
            this.tezos.wallet
                .at(CONTRACT_ADDRESS)
                .then((contract) => {
                    return contract.methods.joinGame(gameId)
                        .send({amount: 1})
                })
                .then((op) => {
                    console.log(`Waiting for ${op.opHash} to be confirmed...`);
                    return op.confirmation().then(() => op.opHash);
                })
                .then((op) => {
                    console.log(`Operation injected: https://ghost.tzstats.com/${op.hash}`)
                 })
                .then(() => this.blockchainStatus = `Joined Game on Smart Contract ${{gameId}}` )
                .catch((error) => console.log(`Error3: ${JSON.stringify(error, null, 2)}`));
        },
        async leaveGameBC(gameId) { 
            if (gameId < 0) {
                return
            }    
            const activeAccount = await this.wallet.client.getActiveAccount() 
            if (!activeAccount) {
                return
            }    
            this.blockchainStatus = 'Joining Game on Smart Contract'              
            this.getSigner(activeAccount)  
            this.tezos.wallet
                .at(CONTRACT_ADDRESS)
                .then((contract) => {
                    return contract.methods.leaveGame(gameId)
                        .send()
                })
                .then((op) => {
                    console.log(`Waiting for ${op.opHash} to be confirmed...`);
                    return op.confirmation().then(() => op.opHash);
                })
                .then((op) => {
                    console.log(`Operation injected: https://ghost.tzstats.com/${op.hash}`)
                 })
                .then(() => this.blockchainStatus = `Joined Game on Smart Contract ${{gameId}}` )
                .catch((error) => console.log(`Error3: ${JSON.stringify(error, null, 2)}`));
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
            this.getSigner(activeAccount)
            await this.tezos.wallet
                .at(CONTRACT_ADDRESS)
                .then((contract) => {
                    return contract.methodsObject.makeMove({
                            gameId: gameId,
                            player: activeAccount.address,
                            move: this.bcNum
                        })
                        .send()
                })
                .then((op) => {
                    console.log(`Waiting for ${op.opHash} to be confirmed...`);
                    return op.confirmation().then(() => op.opHash)
                })
                .then((hash) => {
                    console.log(`Operation injected: https://ghost.tzstats.com/${hash}`)})
                .catch((error) => console.log(`Error3: ${JSON.stringify(error, null, 2)}`));
        },
        async payAdminBC() {      
            const activeAccount = await this.wallet.client.getActiveAccount()   
            if (!activeAccount) {
                return
            }    
            this.getSigner(activeAccount)
            await this.tezos.wallet
                .at(CONTRACT_ADDRESS)
                .then((contract) => {
                    return contract.methodsObject.payAdmin().send()
                })
                .then((op) => {
                    console.log(`Waiting for ${op.opHash} to be confirmed...`);
                    return op.confirmation().then(() => op.opHash)
                })
                .then((hash) => {
                    console.log(`Operation injected: https://ghost.tzstats.com/${hash}`)})
                .catch((error) => console.log(`Error3: ${JSON.stringify(error, null, 2)}`));
        },
        async surrenderGameBC() {      
            const activeAccount = await this.wallet.client.getActiveAccount()   
            if (!activeAccount) {
                return
            }    
            this.getSigner(activeAccount)
            await this.tezos.wallet
                .at(CONTRACT_ADDRESS)
                .then((contract) => {
                    return contract.methodsObject.surrenderGame().send()
                })
                .then((op) => {
                    console.log(`Waiting for ${op.opHash} to be confirmed...`);
                    return op.confirmation().then(() => op.opHash)
                })
                .then((hash) => {
                    console.log(`Operation injected: https://ghost.tzstats.com/${hash}`)})
                .catch((error) => console.log(`Error3: ${JSON.stringify(error, null, 2)}`));
        },
        async getSigner(activeAccount) { 
            const signer = new RemoteSigner(activeAccount.address, NODE_URL )
            await this.tezos.setProvider({signer:signer})
            await this.tezos.setWalletProvider(this.wallet)  
            return signer
        },
        // Reading Smart Contract
        async getGamesFromContractBC() {
            const contract = await this.tezos.wallet.at(CONTRACT_ADDRESS)
            const storage = await contract.storage()
            const games = await storage.games
            return games
        },
        async getGamesFromContractAsync() {
            const activeAccount = await this.wallet.client.getActiveAccount()   
            if (!activeAccount) {
                return
            }  
            const gamesObject = await this.getGamesFromContract()   
            this.updatePlayerControl(gamesObject)        
        },
        async getGamesFromContract() {          
            const games = await this.getGamesFromContractBC() 
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
                loadedGridPoints[n] = gridPoint[1.].c[0]
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
        }
    }
}

</script>

<template>   
                        
        <div class="rowFlex" >            
            <div class="actionButton" @click="createGameBC(0)" > New 0 XTZ Game </div>  
            <div class="actionButton" @click="createGameBC(0.5)" > New 0.5 XTZ Game</div> 
            <div class="actionButton" @click="createGameBC(1)" > New 1 XTZ Game</div>  
            <div class="actionButton" @click="createGameBC(5)" > New 5 XTZ Game</div> 
            <div class="actionButton" @click="createGameBC(10)" > New 10 XTZ Game</div>   
        </div>    
        <div class="rowFlex"> 
            <div class="gameCenter" >   
                <div class="actionButton" @click="loadGameBC(playGameId)"> Play Game: {{ playGameId }} </div>                                       
                <div> 
                    <div class="rowFlex"> 
                                                      
                        <div  v-for="(key, value) in allGamesStatus" :key="key" :value="value"> 
                            <div v-if="key==2" class="gameSelect" @click="updateGame(value, 'play')"> {{value}} </div>                  
                        </div>
                    </div>
                </div>   
            </div>
            <div class="gameCenter"  >  
                <div class="actionButton" @click="joinGameBC(gameId)">   Join Game: {{ joinGameId }}  </div>                                   
                <div> 
                    <div class="rowFlex">     
                                                
                        <div v-for="(key, value) in allGamesStatus" :key="key" :value="value"> 
                            <div v-if="key==4" class="gameSelect" @click="updateGame(value, 'join')"> {{value}} </div>                  
                        </div>
                    </div>                       
                </div>
            </div>
            <div class="gameCenter" > 
                <div class="actionButton" @click="leaveGameBC(gameId)">  Leave Game: {{ leaveGameId }} </div>                             
                <div> 
                    <div class="rowFlex">                                
                        <div  v-for="(key, value) in allGamesStatus" :key="key" :value="value"> 
                            <div v-if="key==1" class="gameSelect" @click="updateGame(value, 'leave')"> {{value}} </div>                  
                        </div>
                    </div>
                </div>                   
            </div>
            <div class="gameCenter" > 
                <div class="actionButton" @click="loadGameBC(gameId)">   View Game: {{ viewGameId }} </div>                              
                <div> 
                    <div class="rowFlex">                                
                        <div  v-for="(key, value) in allGamesStatus" :key="key" :value="value"> 
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
            <div class="gameSelect" > Game ID: {{ gameId }}</div>
            <div class="gameSelect" > {{ playersInGame[0] }} {{player1Connected}} vs. {{ playersInGame[1]}} {{player2Connected}} </div>
            <div class="gameSelect" > {{ playerTurnStr }}</div>
        </div>
        <div class="rowFlex">
            <div class="gameSelect" > Status: {{ blockchainStatus }}</div>
        </div>

</template>

<style>
</style>