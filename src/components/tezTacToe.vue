<script>
import { PollingSubscribeProvider } from '@taquito/taquito';
import { RemoteSigner } from '@taquito/remote-signer';
import tttGameGrid  from './tttGameGrid.vue'
import { RpcClient } from '@taquito/rpc';
import { NODE_URL, CONTRACT_ADDRESS, ID_LOOKUP, TZKT_API_BASE_URL, OBJECT_CONTRACT, ADMIN_ADDRESS} from '../constants'
import { reduceAddress } from "../utilities";

//import { transferToContract } from "../services/tezos-services"

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
            gamesObject: {},
            gameId: '',
            gameStatus: 'No Players',
            pendingGame: 'NO GAME',
            playerTurnStr: '',
            playerTurn: -1, 
            playersInGame: '',
            player1Connected: '',
            player2Connected: '',
            addressesInGame: [],
            blockchainStatus: 'No Activity',
            pointToPlay: 'XXX',
            activeGames: [],
            pendingGames: [],
            pastGames: [],
            pendingGamesOthers: []

        }
    },
    created() {
        this.rpcclient = new RpcClient(NODE_URL, 'NetXnHfVqm9iesp');
        this.socket.on("updateGames", () => {
            this.getGamesFromContractAsync()
        })
        this.socket.on("updatePlayerControl", (gamesObject) => {
            console.log('pcd', gamesObject)
            this.updatePlayerControl(gamesObject)
        })
        this.socket.on("updateConnectedUsers", (address) => {
            this.updateConnectedUsers(address)
        })
        this.socket.on("loadGame", (gameId, updateGrid) => {
            this.getGameGrid(gameId, updateGrid)
            this.updatePlayerControl()
        })
        // Set up socket to receive from server
        this.socket.on('connectedUsers', (connectedUsers, socketId) => {
            console.log('CUs', connectedUsers, socketId)
        });
        this.socket.on('playedPoint', (playedPoint, bcStatus) => {
            this.pointToPlay = playedPoint
            this.blockchainStatus = bcStatus
        })
        this.socket.on('updateBCStatus', (bcStatus) => {
            this.blockchainStatus = bcStatus
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
            while (currentBlockLevel > transactionBlockLevel + 4) {
                this.blockchainStatus = 'Confirming ...'
                let currentBlock = await this.rpcclient.getBlock();
                
                currentBlockLevel = await currentBlock.header.level        
                console.log(currentBlockLevel)        
            }
            this.blockchainStatus = 'Confirmed!'
            this.togglePlayer()
            this.updatePlayerControl()
            
        },
        async delayGetGamesFromContract(transactionBlockLevel){
            await this.getNextBlockLevel(transactionBlockLevel)
            //console.log(this.gameId, this.gameCount)
            if (this.gameId == -1 && this.gameCount > 0) {
                this.gameId = this.gameCount - 1
            } else if (this.gameId == -1 && this.gameCount == 0) {
                this.gameId = 0
            }
            console.log(this.gameId == -1)
            await this.getGameGrid(this.gameId)
        },
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
        // Populating the page
        async updatePlayerControl(gamesObject) {
            if (!gamesObject) {
                gamesObject = await this.getGamesFromContract()
            }
            const activeAccount = await this.wallet.client.getActiveAccount()   
            if (!activeAccount) {
                return
            }  
            let i = 0
            this.activeGames = []
            this.pendingGames = []
            this.pastGames = []
            this.pendingGamesOthers = []
            for (i; i < this.gameCount; i++) {
                if (gamesObject[i].players.includes(activeAccount.address)) {
                    if (gamesObject[i].gameStatus == 0) {
                        this.pendingGames.push(gamesObject[i].gameId)      
                    } else if (gamesObject[i].gameStatus == 1) {
                        this.activeGames.push(gamesObject[i].gameId)     
                    } else if (gamesObject[i].gameStatus == 4) {
                        this.pastGames.push(gamesObject[i].gameId)     
                    }
                } else if (gamesObject[i].gameStatus == 0) {
                    this.pendingGamesOthers.push(gamesObject[i].gameId)
                }
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
            if (game.gameStatus == 0 ) {
                this.pendingGame = gameId
                this.gameStatus = 'Pending'
                this.playersInGame = [await reduceAddress(game.players[0]), 'None']
                this.playerTurnStr = 'NA'
            } else if (game.gameStatus == 1 ) {
                this.gameStatus = 'Active'
                this.gameId = await game.gameId
                this.walletPlayerTurn1 = await reduceAddress(game.players[0])
                this.walletPlayerTurn2 = await reduceAddress(game.players[1])
                this.playersInGame = [this.walletPlayerTurn1, this.walletPlayerTurn2]
                this.playerTurn = await game.playerTurn
                this.socket.emit('updatePlayerTurn', this.playerTurn, game.players, activeAccount.address, this.gameId)
                this.socket.emit('updateConnectedUsersInGame', activeAccount.address, this.gameId)
                this.blockchainStatus = 'Active'
                if (game.players[this.playerTurn - 1] == activeAccount.address) {
                    this.playerTurnStr = 'YOUR TURN'
                    this.socket.emit('updateGamePlayable', true, this.gameId)
                } else {
                    this.playerTurnStr = 'OPP TURN'
                }
            } else if (game.gameStatus == 2) {
                console.log('locking game')
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
        async createGameBC() {            
            this.blockchainStatus = 'Creating Game on Smart Contract'
            const activeAccount = await this.wallet.client.getActiveAccount()   
            if (!activeAccount) {
                return
            }    
            this.getSigner(activeAccount)
            this.tezos.wallet
                .at(CONTRACT_ADDRESS)
                .then((contract) => {
                    return contract.methods.startGame(1000, activeAccount.address).send();
                })
                .then((op) => {
                    console.log(`Waiting for ${op.opHash} to be confirmed...`);
                    return op.confirmation().then(() => op.opHash);
                })
                .then((hash) => console.log(`Operation injected: https://ghost.tzstats.com/${hash}`))
                .catch((error) => console.log(`Error3: ${JSON.stringify(error, null, 2)}`));
            
        },
        async joinGameBC(gameId) {     
            this.blockchainStatus = 'Joining Game on Smart Contract'       
            const activeAccount = await this.wallet.client.getActiveAccount()   
            if (!activeAccount) {
                return
            }    
            this.getSigner(activeAccount)  
            this.tezos.wallet
                .at(CONTRACT_ADDRESS)
                .then((contract) => {
                    return contract.methodsObject.joinGame({
                            gameId: gameId,
                            player: activeAccount.address,
                        })
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
                        .send({ amount: 1 })
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
        async claimWinningsBC() {      
            const activeAccount = await this.wallet.client.getActiveAccount()   
            if (!activeAccount) {
                return
            }    
            this.getSigner(activeAccount)
            await this.tezos.wallet
                .at(CONTRACT_ADDRESS)
                .then((contract) => {
                    return contract.methodsObject.claimWinnings().send()
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
        async claimNFTEarningsBC() {  
            let ownersToPay = {}  
            let i = 0
            for (let Id in ID_LOOKUP) {
                const apiUrl = TZKT_API_BASE_URL+ ID_LOOKUP[Id]
                const response = await fetch(apiUrl);
                const addressJson = await response.json();
                let ownerAddress = addressJson[0]['address']
                //console.log(ownerAddress, 'v', OBJECT_CONTRACT)
                if (ownerAddress.toString() == OBJECT_CONTRACT) {
                    ownerAddress = ADMIN_ADDRESS
                }
                this.blockchainStatus = 'checking Id ' + (i + 1).toString() + ' of 273'
                if (ownerAddress in ownersToPay) {
                    console.log('onwer found')
                    ownersToPay[ownerAddress] += 1
                } else {
                    ownersToPay[ownerAddress] = 1

                }
                i ++;
            }
            console.log(ownersToPay)
            i = 0
            let uniqueOwners  = []
            for (let uniqueOwner in uniqueOwners) {
                console.log([ownersToPay].filter(x => x==uniqueOwner).length)
                console.log(i, uniqueOwner, uniqueOwners[i])
                i ++;
            }
            const activeAccount = await this.wallet.client.getActiveAccount()   
            if (!activeAccount) {
                return
            }            
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
                const metadata = await game.metadata.values()
                let i = 0;
                let gameData = {}
                gameData['gameId'] = j
                for (let data of metadata) {
                    if (i == 0) {
                        gameData['gameBalance'] = data.toNumber()
                    } else  if (i == 1) {
                        gameData['gameStatus'] = data.toNumber()
                    } else if (i == 2) {
                        gameData['mutezPerMove'] = data.toNumber()
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
            this.blockchainStatus = 'Loading Game from Smart Contract'       
            const activeAccount = await this.wallet.client.getActiveAccount()   
            if (!activeAccount) {
                return
            }           
            this.socket.emit("setUserActiveGameRoom", activeAccount.address, this.gameCount, gameId)
            await this.updateLoadedGameStatus(gameId)   
            const game = await this.gamesObject[gameId]
            const playerTurn = game.playerTurn
            const players = game.players
            const updateGrid = players[playerTurn - 1] == activeAccount.address
            this.socket.emit("updatePlayedPoint", 'NO MOVE', 'Active', this.gameId)
            this.socket.emit('loadGame', gameId, updateGrid)   
            this.socket.emit('updateGamePlayable', updateGrid)
            this.socket.emit('resizeGameGrid', window.innerWidth)
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
        }
    }
}

</script>

<template>   
     <div class="gameManagement" >
        <div class="rowFlex"> Game Center 
            <div class="rowFlex" >     
                <div> 
                    <div class="actionButton" > Game ID: {{ gameId }}</div>
                </div>
                <div> 
                    <div class="actionButton" > {{ playersInGame[0] }} {{player1Connected}} vs. {{ playersInGame[1]}} {{player2Connected}} </div>
                </div>
                <div> 
                    <div class="actionButton" > {{ playerTurnStr }}</div>
                </div>
            </div>
        </div>
    <div class="gameManagement"> 
        <div class="rowFlex"> Game Hub 
            <div> 
                <div class="actionButton" @click="createGameBC" > Create New Game  </div>
            </div>
            Load 
            <div class="rowFlex" > 
                <div v-for="(item) in activeGames" :key="item"> 
                    <div class="actionButton" @click="loadGameBC(item)">  {{ item }}</div>
                </div>
            </div>
            Leave  
            <div class="rowFlex" > 
                <div v-for="(item) in pendingGames" :key="item"> 
                    <div class="actionButton" @click="loadGameBC(item)"> {{ item }}</div>
                </div>
            </div>
            Join  
            <div class="rowFlex" > 
                <div v-for="(item) in pendingGamesOthers" :key="item"> 
                    <div class="actionButton" @click="joinGameBC(item)"> {{ item }}</div>
                </div>
            </div>
            View 
            <div class="gridFlex4x2" > 
                <div v-for="(item) in pastGames" :key="item"> 
                    <div class="actionButton" @click="joinGameBC(item)"> {{ item }}</div>
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
    
     <div> 
        <div class="actionButton" @click="submitMoveBC(pointToPlay, gameId)"> Submit Move </div>
     </div>  
     <div> 
        <div class="actionButton" @click="surrenderBC"> Surrender  </div>
    </div>  
    <div> 
         <div class="actionButton" > BC Status: {{ blockchainStatus }}</div>
    </div> 
</template>

<style>
</style>