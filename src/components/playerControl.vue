<script>
import { RemoteSigner } from '@taquito/remote-signer';
import { NODE_URL, CONTRACT_ADDRESS } from '../constants'
import { getGamesFromContract } from '../services/tezos-services.js'
import { reduceAddress } from "../utilities";

export default {
    name: "playerControl",
    emits: [
        "submitMove",
        "createGameService"
    ],
    props: ["socket", "wallet", "tezos", "walletAddress"],
    data () {
        return {
            gamesObject: {},
            gameId: 'No GAME',
            gameStatus: 'No Players',
            pendingGame: 'NO GAME',
            playerTurn: 'NA',
            playersInGame: '',
            activeGames: [],
            pendingGames: [],
            pendingGamesOthers: []

        }
    },
    created() {
        this.socket.emit("updateActiveGame", this.activeGameId)
        this.socket.on("updateGames", (address) => {
            this.getGamesFromContract(address)
        })
            // Set up socket to receive from server
        this.socket.on('connectedUsers', (connectedUsers, socketId) => {
            //
            console.log('CUs', connectedUsers, socketId)
        });
    },
    methods: {
        //Wallet Control
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
            const game = this.gamesObject[gameId]
            this.gameId = game.gameId
            if (game.gameStatus == 0 ) {
                this.pendingGame = gameId
                this.gameStatus = 'Pending'
                this.playersInGame = [await reduceAddress(game.players[0]), 'None']
                this.playerTurn = 'NA'
            } else if (game.gameStatus == 1 ) {
                this.gameStatus = 'Active'
                this.playersInGame = [await reduceAddress(game.players[0]), await reduceAddress(game.players[1])]
                this.playerTurn = game.playerTurn
            }
        },
        // Interact with Smart Contract
        async createGameBC() {            
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
                    console.log(`Waiting for ${op.hash} to be confirmed...`);
                    return op.confirmation(1).then(() => op.hash);
                })
                .then((hash) => console.log(`Operation injected: https://ghost.tzstats.com/${hash}`))
                .catch((error) => console.log(`Error3: ${JSON.stringify(error, null, 2)}`));
        },
        async joinGameBC(gameId) {            
            const activeAccount = await this.wallet.client.getActiveAccount()   
            if (!activeAccount) {
                return
            }    
            const signer = new RemoteSigner(activeAccount.address, NODE_URL )
            await this.tezos.setProvider({signer:signer})
            await this.tezos.setWalletProvider(this.wallet)      
            this.tezos.contract
                .at(CONTRACT_ADDRESS)
                .then((contract) => {
                    return contract.methods.joinGame(gameId, activeAccount.address);
                })
                .then((op) => {
                    console.log(`Estimating the smart contract call: `);
                    return this.tezos.estimate.contractCall(op);
                })
                .then((estimate) => {
                    console.log(`burnFeeMutez : ${estimate.burnFeeMutez},
                    gasLimit : ${estimate.gasLimit},
                    minimalFeeMutez : ${estimate.minimalFeeMutez},
                    storageLimit : ${estimate.storageLimit},
                    suggestedFeeMutez : ${estimate.suggestedFeeMutez},
                    totalCost : ${estimate.totalCost},
                    usingBaseFeeMutez : ${estimate.usingBaseFeeMutez}`);
                })
                .catch((error) => console.table(`Error: ${JSON.stringify(error, null, 2)}`));     
            this.tezos.wallet
                .at(CONTRACT_ADDRESS)
                .then((contract) => {
                    return contract.methods.joinGame(gameId, activeAccount.address).send();
                })
                .then((op) => {
                    console.log(`Waiting for ${op.hash} to be confirmed...`);
                    return op.confirmation(1).then(() => op.hash);
                })
                .then((hash) => console.log(`Operation injected: https://ghost.tzstats.com/${hash}`))
                .catch((error) => console.log(`Error3: ${JSON.stringify(error, null, 2)}`));
            this.socket.emit("updateGames")
        },
        // Reading Smart Contract
        async loadGameBC(gameId) {
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
        <div class="actionButton" @click="submitMoveBC"> 
            Submit Move
        </div>
        <div class="actionButton" @click="toggleWallet">
                {{walletAddress}} 
        </div>
     </div>
     <div class="playerPanel" > My Games: 
        <div v-for="(item) in activeGames" :key="item"> 
            <div class="actionButton" @click="loadGameBC(item)"> {{ item }}</div>
        </div>
     </div>
     <div class="playerPanel" > My Pending Games:
        <div v-for="(item) in pendingGames" :key="item"> 
            <div class="actionButton" @click="loadGameBC(item)"> {{ item }}</div>
        </div>
     </div>
     <div class="playerPanel" > Others Pending Games:
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