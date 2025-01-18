<script>
import { PollingSubscribeProvider } from '@taquito/taquito';
import { RemoteSigner } from '@taquito/remote-signer';
import { RpcClient } from '@taquito/rpc';
import { NODE_URL, CONTRACT_ADDRESS } from '../constants'
import { getGamesFromContract } from '../services/tezos-services.js'
import { reduceAddress } from "../utilities";

export default {
    name: "playerControl",
    emits: [
    ],
    props: ["socket", "wallet", "tezos", "walletAddress"],
    data () {
        return {
            gamesObject: {},
            gameId: -1,
            gameStatus: 'No Players',
            pendingGame: 'NO GAME',
            playerTurn: 'NA',
            playersInGame: '',
            blockchainStatus: 'No Activity',
            pointToPlay: 'XXX',
            activeGames: [],
            pendingGames: [],
            pendingGamesOthers: []

        }
    },
    created() {
        this.rpcclient = new RpcClient(NODE_URL, 'NetXnHfVqm9iesp');
        this.socket.emit("updateActiveGame", this.activeGameId)
        this.socket.on("updateGames", (gameId) => {
            this.getGamesFromContract()
            if (gameId > -1) {
                this.updateLoadedGameStatus(gameId)
            }
        })
        // Set up socket to receive from server
        this.socket.on('connectedUsers', (connectedUsers, socketId) => {
            console.log('CUs', connectedUsers, socketId)
        });
        this.socket.on('playedPoint', (playedPoint, bcStatus) => {
            this.pointToPlay = playedPoint
            this.blockchainStatus = bcStatus
        })
        // Listen to contracts for changes
        this.tezos.setStreamProvider(
            this.tezos.getFactory(PollingSubscribeProvider)({
                shouldObservableSubscriptionRetry: true,
                pollingIntervalMilliseconds: 1500
            })
            );
        try {
            const sub = this.tezos.stream.subscribeEvent({
              tag: 'contractUpdated',
              address: CONTRACT_ADDRESS,
              //excludeFailedOperations: true
            });
            sub.on('data', (data) => {
                console.log('transaction level', data.level)
                const transactionBlockLevel = data.level
                if (this.gameId > -1) {
                    this.delayGetGamesFromContract(transactionBlockLevel)
                }

            })
          } catch (e) {
            console.log(e);
          }
    },
    methods: {
        //Wallet Control
        async getNextBlockLevel(transactionBlockLevel){
            let currentBlock = await this.rpcclient.getBlock();
            let currentBlockLevel = currentBlock.header.level
            while (currentBlockLevel == transactionBlockLevel) {
                console.log('checking block level', currentBlockLevel)
                this.blockchainStatus = 'confirming move'
                let currentBlock = await this.rpcclient.getBlock();
                currentBlockLevel = currentBlock.header.level
            }
            console.log('block level is ', currentBlockLevel)
           
            
        },
        async delayGetGamesFromContract(transactionBlockLevel){
            await this.getNextBlockLevel(transactionBlockLevel)
            await this.getGamesFromContract()
            const game = this.gamesObject[this.gameId]
            this.getGameGridBC(game, this.gameId)
            this.socket.emit("updateGames", this.gameId)
        },
        async toggleWallet(){
            const activeAccount = await this.wallet.client.getActiveAccount()              
            if (activeAccount) {                  
                await this.wallet.clearActiveAccount()           
            } else {
                await this.wallet.client.requestPermissions()
                this.tezos.setWalletProvider(this.wallet)
            }
        },
        // Populating the page
        async updatePlayerControl() {
            const activeAccount = await this.wallet.client.getActiveAccount()   
            if (!activeAccount) {
                return
            }  
            let i = 0
            this.activeGames = []
            this.pendingGames = []
            this.pendingGamesOthers = []
            for (i; i < this.gameCount; i++) {
                if (this.gamesObject[i].players.includes(activeAccount.address)) {
                    if (this.gamesObject[i].gameStatus == 0) {
                        this.pendingGames.push(this.gamesObject[i].gameId)
                    } else if (this.gamesObject[i].gameStatus == 1) {
                        this.activeGames.push(this.gamesObject[i].gameId)
                    }
                } else if (this.gamesObject[i].gameStatus == 0) {
                    this.pendingGamesOthers.push(this.gamesObject[i].gameId)
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
            console.log(this.gamesObject[gameId])
            const game = this.gamesObject[gameId]
            console.log(game)
            this.gameId = game.gameId
            if (game.gameStatus == 0 ) {
                this.pendingGame = gameId
                this.gameStatus = 'Pending'
                this.playersInGame = [await reduceAddress(game.players[0]), 'None']
                this.playerTurn = 'NA'
            } else if (game.gameStatus == 1 ) {
                this.gameStatus = 'Active'
                this.gameId = gameId
                this.walletPlayerTurn1 = await reduceAddress(game.players[0])
                this.walletPlayerTurn2 = await reduceAddress(game.players[1])
                this.playersInGame = [this.walletPlayerTurn1, this.walletPlayerTurn2]
                this.playerTurn = game.playerTurn
                this.blockchainStatus = 'Active'
                if (game.players[this.playerTurn - 1] == activeAccount.address) {
                    this.socket.emit('gamePlayable', true, this.playerTurn)
                } else {
                    this.socket.emit('gamePlayable', false, this.playerTurn)
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
            const signer = new RemoteSigner(activeAccount.address, NODE_URL )
            await this.tezos.setProvider({signer:signer})
            await this.tezos.setWalletProvider(this.wallet)
            this.tezos.wallet
                .at(CONTRACT_ADDRESS)
                .then((contract) => {
                    return contract.methods.startGame(1000, activeAccount.address).send();
                })
                .then((op) => {
                    console.log
                    console.log(`Waiting for ${op.opHash} to be confirmed...`);
                    return op.confirmation().then(() => op.opHash);
                })
                .then((hash) => console.log(`Operation injected: https://ghost.tzstats.com/${hash}`))
                .then(() => this.blockchainStatus = 'Created Game on Smart Contract' )
                .catch((error) => console.log(`Error3: ${JSON.stringify(error, null, 2)}`));
        },
        async joinGameBC(gameId) {     
            this.blockchainStatus = 'Joining Game on Smart Contract'       
            const activeAccount = await this.wallet.client.getActiveAccount()   
            if (!activeAccount) {
                return
            }    
            const signer = new RemoteSigner(activeAccount.address, NODE_URL )
            await this.tezos.setProvider({signer:signer})
            await this.tezos.setWalletProvider(this.wallet)      
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
                    console.log(op)
                    console.log(`Operation injected: https://ghost.tzstats.com/${op.hash}`)
                 })
                .then(() => this.blockchainStatus = `Joined Game on Smart Contract ${{gameId}}` )
                .catch((error) => console.log(`Error3: ${JSON.stringify(error, null, 2)}`));
            //this.socket.emit("updateGames", gameId)
        },
        async submitMoveBC(pointToPlay, gameId) {          
            console.log(pointToPlay, gameId)  
            const x = pointToPlay[0] + 2 // shift to BC coords
            const y = pointToPlay[1] + 2 // shift to BC coords
            const z = pointToPlay[2] + 2 // shift to BC coords
            let bcPoint = x.toString() +  y.toString() + z.toString()
            this.bcNum = parseInt(bcPoint);
            const activeAccount = await this.wallet.client.getActiveAccount()   
            if (!activeAccount) {
                return
            }    
            const signer = new RemoteSigner(activeAccount.address, NODE_URL )
            await this.tezos.setProvider({signer:signer})
            await this.tezos.setWalletProvider(this.wallet)      
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
        // Reading Smart Contract
        async loadGameBC(gameId) {
            this.socket.emit("initGameGrid")
            const activeAccount = await this.wallet.client.getActiveAccount()   
            if (!activeAccount) {
                return
            }    
            const games = await getGamesFromContract(activeAccount.address)  
            const allGames = await games.values()
            let j = 0;
            //
            for (let game of allGames) {
                if (j == gameId) {
                    await this.getGameGridBC(game, j)
                    await this.updateLoadedGameStatus(j)
                    {break ;}
                }  
                j ++;
            }           
        },
        async getGameGridBC(game, gameId) {
            let loadedGridPoints = []
            const gridPoints = await game.grid.values()
            let n = 0;
            for (let gridPoint of gridPoints) {
                loadedGridPoints[n] = gridPoint.toNumber()
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
            this.socket.emit("newGameGrid", gameGrid, gameId)
        },
        async getGamesFromContract() {

            console.log(this.wallet)
            const activeAccount = await this.wallet.client.getActiveAccount()   
            if (!activeAccount) {
                return
            }   
            const games = await getGamesFromContract()         
            const allGames = await games.values()
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
                this.gamesObject[j] = gameData
                j ++;
            }           
            this.gameCount = j
            this.updatePlayerControl()          
        }
    }
}

</script>

<template>
    <div class="playerPanel" > 
        <div class="actionButton" @click="createGameBC" > 
            Create Game
        </div>
        <div class="actionButton" @click="joinGameBC(pendingGame)"> 
            Join Game {{ pendingGame }}
        </div>
        <div class="actionButton" @click="submitMoveBC(pointToPlay, gameId)"> 
            Submit Move {{ pointToPlay }}
        </div>
        <div class="actionButton" @click="toggleWallet">
                {{walletAddress}} 
        </div>
     </div>
     <div class="playerPanel" > My Active Games: 
        <div v-for="(item) in activeGames" :key="item"> 
            <div class="actionButton" @click="loadGameBC(item)"> {{ item }}</div>
        </div>
     </div>
     <div class="playerPanel" > My Games Looking for Challengers!:
        <div v-for="(item) in pendingGames" :key="item"> 
            <div class="actionButton" @click="loadGameBC(item)"> {{ item }}</div>
        </div>
     </div>
     <div class="playerPanel" > Games Looking for Challengers!
        <div v-for="(item) in pendingGamesOthers" :key="item"> 
            <div class="actionButton" @click="loadGameBC(item)"> {{ item }}</div>
        </div>
     </div>
     <div class="playerPanel" > Game INFO: 
        <div> 
            <div class="actionButton" > Game ID: {{ gameId }}</div>
        </div>
        <div> 
            <div class="actionButton" > Game Status {{ gameStatus }}</div>
        </div>
        <div> 
            <div class="actionButton" > Players: {{ playersInGame }}</div>
        </div>
        <div> 
            <div class="actionButton" > Player Turn: {{ playerTurn }}</div>
        </div>
        <div> 
            <div class="actionButton" > Status: {{ blockchainStatus }}</div>
        </div>
     </div>
</template>


<style scoped>
.playerPanel {

    display: flex;
    align-content: center;
    flex-direction: row;
    justify-content: center;
    vertical-align: center;
    background-color: #000000;
    color: #fff;
    padding: 5px;
    border-style: inset;
    border-width: 5px;
    border-color: #fff;
}
.actionButton {
    display: flex;
    align-content: center;
    justify-content: center;
    padding: 5px;
    margin: auto;
    border-style: ridge;
    border-radius: 2px;
    border-width: 3px;
    color: #fff;
    border-color: #fff;
}

</style>