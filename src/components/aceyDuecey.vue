

<script>

import * as Three from 'three'
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls";
import { RemoteSigner } from '@taquito/remote-signer';
import { GAME_WIDTH_FRACTION, MAX_GAME_SIZE, NODE_URL, AD_CONTRACT_ADDRESS, AD_GAME_INFO} from '../constants'



export default {
    name: 'aceyDuecy',
    props: ["socket", "wallet", "tezos"],
    components: { 
  },
  data () {
    return {
      gameInfo: AD_GAME_INFO,
      showInfo: false, 
      highLow: 'Ace High',
      aceHigh: 1,
      blockChainStatus: '',
      tezosSymbol: 'ꜩ',
      gameId: 'NA', 
      firstCard: -1,
      secondCard: -1,
      lastCard: 0,
      potBalance: 0,
      ante: 0.1, 
      fee: 0.1,
      thisBet: 0.1,
      myOldGames: {},
      myGames: {},
      gameCount: -1,
      thisBets: [],
      loadGame: true,
      hideOldGames: true,
      hideOldGamesStatus: 'Hide Old Games'
    }
  },
  created () {
    this.apiUrl = 'https://api.ghostnet.tzkt.io/v1/contracts/' + AD_CONTRACT_ADDRESS + '/storage'
    //Three 
    this.gameSize = window.innerWidth * GAME_WIDTH_FRACTION
    this.maxGameSize = MAX_GAME_SIZE
    this.board = new Three.Group();
    this.scene = new Three.Scene();
    this.camera = new Three.PerspectiveCamera(45, 1, 1, 5000);
    this.camera.position.x = 0;
    this.camera.position.y = -50;
    this.camera.position.z = 250;
    this.camera.lookAt(this.scene.position)
    this.degrees = 0
    this.loader = new Three.TextureLoader();
    this.pokerCardLoader = require('../assets/pokerCard.png')
    this.card1Texture = this.loader.load(this.pokerCardLoader); 
    this.card2Texture = this.loader.load(this.pokerCardLoader); 
    this.card3Texture = this.loader.load(this.pokerCardLoader);
    this.card1Material = new Three.MeshBasicMaterial({ map: this.card1Texture });
    this.card2Material = new Three.MeshBasicMaterial({ map: this.card2Texture });
    this.card3Material = new Three.MeshBasicMaterial({ map: this.card2Texture });
    this.cardTextures = [this.card1Texture, this.card2Texture, this.card3Texture]
    this.defaultGeometry = new Three.BoxGeometry(130, 130, 1, 1)
    this.deck = [     
      require('../assets/02_of_clubs.png'),
      require('../assets/02_of_diamonds.png'),
      require('../assets/02_of_hearts.png'),
      require('../assets/02_of_spades.png'),
      require('../assets/03_of_clubs.png'),
      require('../assets/03_of_diamonds.png'),
      require('../assets/03_of_hearts.png'),
      require('../assets/03_of_spades.png'),
      require('../assets/04_of_clubs.png'),
      require('../assets/04_of_diamonds.png'),
      require('../assets/04_of_hearts.png'),
      require('../assets/04_of_spades.png'),
      require('../assets/05_of_clubs.png'),
      require('../assets/05_of_diamonds.png'),
      require('../assets/05_of_hearts.png'),
      require('../assets/05_of_spades.png'),
      require('../assets/06_of_clubs.png'),
      require('../assets/06_of_diamonds.png'),
      require('../assets/06_of_hearts.png'),
      require('../assets/06_of_spades.png'),
      require('../assets/07_of_clubs.png'),
      require('../assets/07_of_diamonds.png'),
      require('../assets/07_of_hearts.png'),
      require('../assets/07_of_spades.png'),
      require('../assets/08_of_clubs.png'),
      require('../assets/08_of_diamonds.png'),
      require('../assets/08_of_hearts.png'),
      require('../assets/08_of_spades.png'),
      require('../assets/09_of_clubs.png'),
      require('../assets/09_of_diamonds.png'),
      require('../assets/09_of_hearts.png'),
      require('../assets/09_of_spades.png'),
      require('../assets/10_of_clubs.png'),
      require('../assets/10_of_diamonds.png'),
      require('../assets/10_of_hearts.png'),
      require('../assets/10_of_spades.png'),
      require('../assets/11_of_clubs.png'),
      require('../assets/11_of_diamonds.png'),
      require('../assets/11_of_hearts.png'),
      require('../assets/11_of_spades.png'),
      require('../assets/12_of_clubs.png'),
      require('../assets/12_of_diamonds.png'),
      require('../assets/12_of_hearts.png'),
      require('../assets/12_of_spades.png'),
      require('../assets/13_of_clubs.png'),
      require('../assets/13_of_diamonds.png'),
      require('../assets/13_of_hearts.png'),
      require('../assets/13_of_spades.png'),
      require('../assets/14_of_clubs.png'),
      require('../assets/14_of_diamonds.png'),
      require('../assets/14_of_hearts.png'),
      require('../assets/14_of_spades.png'),       
    ]
    this.cardGeometry = new Three.BoxGeometry(50, 100, 0.1, 1)
    //Socket 
    this.socket.on('resizeGame', (width) => {
      this.resizeGameRender(width)
    }); 
    try {
      const subFirstTwoCards = this.tezos.stream.subscribeEvent({
        tag: 'firstTwoCards',
        address: AD_CONTRACT_ADDRESS,
        //excludeFailedOperations: true
      });
      subFirstTwoCards.on('data', (data) => {   
        console.log('twoCardData', data) 
        this.gameId = Number(data.payload[0]['int'])
        
        this.blockChainStatus = 'Cards Dealt!'
        this.myGameHub()
        this.loadGameInfo()
        this.loadGame = true
      })
      const subLastCard = this.tezos.stream.subscribeEvent({
        tag: 'lastCard',
        address: AD_CONTRACT_ADDRESS,
        //excludeFailedOperations: true
      });
      subLastCard.on('data', (data) => { 
        console.log('lastCardData', data)     
        this.gameId = Number(data.payload[0]['int']) 
        this.blockChainStatus = 'Final Card Dealt!'
        this.myGameHub()
        this.loadGameInfo()
      })
      } catch (e) {
        console.log('Error', e);
    }
  },
  mounted () {
    this.blockChainStatus = 'Loading Games'
    this.intervalId = setInterval(() => {
      this.monitorContract();
    }, 2000);

    this.renderer = new Three.WebGLRenderer({antialias: true});
    this.renderer.setSize(this.gameSize, this.gameSize)   
    this.$refs.container.appendChild(this.renderer.domElement);
    //this.socket.emit("resizeGame", window.innerWidth)
    this.buildGame()
    this.renderer.render(this.scene, this.camera);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.showCards()
    this.socket.emit("resizeGame", window.innerWidth)    
    this.myGameHub()
  },
  methods: {
    // Game Rendering
    async showCards() {
      this.controls.update();
      requestAnimationFrame(this.showCards);  
      this.renderer.render(this.scene, this.camera);
    },
    async teaseCards() {
      requestAnimationFrame(this.teaseCards);  
      let time = Date.now() * 0.001;
      this.card1.rotation.y = -time;
      this.card2.rotation.y = -time;
      this.renderer.render(this.scene, this.camera);
    },
    async flipCards() {
      //requestAnimationFrame(this.flipCards);
      if (this.lastCard >= 0) {
        //this.lastCard = 0
        this.cards[2].visible = true
      } else if (this.lastCard == -1 ) {
        this.lastCard = 0
      }
      if (this.firstCard < 0) {
        return
      }
      const card1asset = this.deck[this.firstCard]
      const card2asset = this.deck[this.secondCard]
      const card3asset = this.deck[this.lastCard] 
      this.loadCardAsset(1, card1asset)
      this.loadCardAsset(2, card2asset)
      this.loadCardAsset(3, card3asset)
      
    },
    async loadCardAsset(card, cardasset) {
      this.loader.load((cardasset), (texture) => {
        this.cardTextures[card - 1].dispose(); // Dispose old texture
        this.cardTextures[card - 1] = texture;
        this.cards[card - 1].material.map = texture;
        this.cards[card - 1].material.needsUpdate = true;
      });
    },
    async buildGame() {      
      this.card1 = new Three.Mesh(this.cardGeometry, this.card1Material); 
      this.card1.position.set(-60, -30, 0);
      await this.board.add(this.card1)    
      this.card2 = new Three.Mesh(this.cardGeometry, this.card2Material); 
      this.card2.position.set(60, -30, 0);
      await this.board.add(this.card2)   
      this.card3 = new Three.Mesh(this.cardGeometry, this.card3Material); 
      this.card3.position.set(0, 50, 0);
      this.card3.visible = false
      await this.board.add(this.card3)   
      await this.scene.add(this.board)   
      this.cards = [this.card1, this.card2, this.card3]       
    },
    async resetGame() {    
      this.loadCardAsset(1, this.pokerCardLoader)  
      this.loadCardAsset(2, this.pokerCardLoader)  
      this.loadCardAsset(3, this.pokerCardLoader)  
      this.card3.visible = false            
    },
    async resizeGameRender(width) {
      this.gameSize = width * GAME_WIDTH_FRACTION
      if (this.gameSize > this.maxGameSize) {
        this.gameSize = this.maxGameSize
      }
      await this.renderer.setSize(this.gameSize, this.gameSize)
    },  
    // Interact with the contract    
    async betBC() {        
      const activeAccount = await this.wallet.client.getActiveAccount()   
      if (!activeAccount) {
          return
      }     

      this.loadGame = false
      this.blockChainStatus = 'Submitting Bet'
      this.resetGame()
      await this.getSigner(activeAccount)
      await this.tezos.wallet
          .at(AD_CONTRACT_ADDRESS)
          .then((contract) => {
            return contract.methods.bet(this.aceHigh).send({amount: this.ante + this.fee})
          })
          .then((op) => {
            console.log(`Waiting for ${op.opHash} to be confirmed...`);
            return op.confirmation().then(() => op.opHash)
          })
          .then((hash) => {
            console.log(`Operation injected: https://ghost.tzstats.com/${hash}`)
            this.blockChainStatus = 'Getting cards for game ' + this.gameId 
          })
          .catch((error) => console.log(`Error3: ${JSON.stringify(error, null, 2)}`));
    }, 
    async continueBetBC() {      
      const activeAccount = await this.wallet.client.getActiveAccount()   
      if (!activeAccount) {
          return
      }    
      this.blockChainStatus = 'Submitting Bet'
      let totalBet = Number(this.thisBet) + this.fee
      totalBet = Number(totalBet).toFixed(1)
      console.log(totalBet)
      await this.getSigner(activeAccount)
      await this.tezos.wallet
          .at(AD_CONTRACT_ADDRESS)
          .then((contract) => {
            return contract.methodsObject.continueBet(this.gameId).send({amount: totalBet})
          })
          .then((op) => {
            console.log(`Waiting for ${op.opHash} to be confirmed...`);
            return op.confirmation().then(() => op.opHash)
          })
          .then((hash) => {
            console.log(`Operation injected: https://ghost.tzstats.com/${hash}`)
            this.gameId = Number(this.gameId)
            this.blockChainStatus = 'Getting Final Card for Game ' + this.gameId 
          })
          .catch((error) => console.log(`Error3: ${JSON.stringify(error, null, 2)}`));
    }, 
    async getSigner(activeAccount) { 
      const signer = new RemoteSigner(activeAccount.address, NODE_URL )
      await this.tezos.setProvider({signer:signer})
      await this.tezos.setWalletProvider(this.wallet)  
      return signer
    },
    // Read the contract
    async getPotBalance() {
      const response = await fetch(this.apiUrl);
      const data = await response.json();
      this.potBalance = data['pot'] * 1e-6
      this.thisBets = []
      let bet = this.ante 
      while (bet < this.potBalance + this.ante) {
          const betEntry = Number(bet).toFixed(1)
          if (bet < this.potBalance) {
            this.thisBets.push(betEntry)
          }
          bet += this.ante
        }
      this.potBalance = Number(data['pot'] * 1e-6).toFixed(3)
    },
    async getGamesFromContractBC() {
      const activeAccount = await this.wallet.client.getActiveAccount()   
      if (!activeAccount) {
          return
      } 
      const response = await fetch(this.apiUrl);
      const data = await response.json();
      this.myGames = {}
      this.myOldGames = {}
      let i = 0
      for (let game in data['games']) {
        if (data['games'][game]['player'] == activeAccount.address) {
          let gameStatus = ''
          if (await data['games'][game]['gameStatus'] == '0') {
            gameStatus = 'Waiting for cards'
            this.blockChainStatus = 'Waiting for cards ' + this.gameId
          } else if (await data['games'][game]['gameStatus'] == '1') {
            gameStatus = 'is ready for Acey Duecey'
          } else if (await data['games'][game]['gameStatus'] == '2') {
            gameStatus = 'Waiting for final card'
            this.blockChainStatus = 'Waiting for final card for ' + game
          } else if (await data['games'][game]['gameStatus'] == '3') {
            gameStatus = 'Win'            
          } else if (await data['games'][game]['gameStatus'] == '4') {
            gameStatus = 'Loss'
          }else if (await data['games'][game]['gameStatus'] == '5') {
            gameStatus = 'Loss'
          }
          if (data['games'][game]['player'] == activeAccount.address) {
            this.gameCount = i
            if (Number(data['games'][game]['gameStatus']) > 2 ){
              this.myOldGames[i] = {
              gameId: game,
              gameStatus: gameStatus
            }
            } else {
              this.myGames[i] = {
                gameId: game,
                gameStatus: gameStatus
              }
            }
          }
        }
        i ++ 
        
      }
    },
    async loadGameInfo() {
      if (!this.loadGame) {
        return
      }
      if (this.gameId == 'NA') {
        return
      }
      const response = await fetch(this.apiUrl);
      const data = await response.json();
      if (!data['games'][this.gameId]) {
        return
      }
      this.firstCard = Number(data['games'][this.gameId]['hand'][1])
      this.secondCard = Number(data['games'][this.gameId]['hand'][2])
      this.lastCard = Number(data['games'][this.gameId]['hand'][3])
      if (this.lastCard >= 1) {
        this.card3.visible = true
      } else {
        this.card3.visible = false
      }
      let gameStatus = 'Loading'
      if (data['games'][this.gameId]['gameStatus'] == '1') {
            gameStatus = 'Play for Acey Duecey ' + this.gameId 
          } else if (data['games'][this.gameId]['gameStatus'] == '2') {
            gameStatus = 'Waiting For Card for Game ' + this.gameId 
          } else if (data['games'][this.gameId]['gameStatus'] == '3') {
            gameStatus = 'Game ' + this.gameId + ' Over - Win!'            
          } else if (data['games'][this.gameId]['gameStatus'] == '4') {
            gameStatus = 'Game ' + this.gameId + ' Over Loss'
          }else if (data['games'][this.gameId]['gameStatus'] == '5') {
            gameStatus = 'Game ' + this.gameId + ' Over Pair Loss'
          }
      this.blockChainStatus = gameStatus
      this.flipCards()
    },
    async monitorContract() {
      await this.getGamesFromContractBC()
      if (this.gameId == 'NA' && this.gameCount >= 0) {
        const gameIds = Object.keys(this.myGames)
        const mostRecentGameId = gameIds[gameIds.length - 1]
        this.gameId = mostRecentGameId
        this.blockChainStatus = 'Game ' + this.gameId + ' loaded'
        this.loadGameInfo()
        this.getPotBalance()
      } else if (this.gameCount < 0) {
        this.blockChainStatus = 'User has no games' 
      } else {
        this.loadGameInfo()
        this.getPotBalance()
      }
    },
    // Render Interface
    async setGameId(gameId) {      
      this.gameId = gameId
      this.loadGameInfo()
    },
    async toggleAceHigh() {
      if (this.highLow == 'Ace High') {
        this.aceHigh = 1
      } else {
        this.aceHigh = 0
      }
    },
    async myGameHub() {
      await this.getPotBalance()
      await this.loadGameInfo()
    },
    async showLearnMore() {
        if (this.showInfo)  {
            this.showInfo = false
        } else {
            this.showInfo = true
        }
    },
    async toggleOldGames() {
        if (this.hideOldGames)  {
            this.hideOldGames = false
            this.hideOldGamesStatus = 'Show Old Games'
        } else {
            this.hideOldGames = true
            this.hideOldGamesStatus = 'Hide Old Games'
        }
    }
  },
}
</script>

<template>
  <div class="canvasContainer" >        
    <div class="rowFlex">
      <div class="actionButtonHelp" @click="showLearnMore"> HOW TO PLAY </div>
        <div class="infoPopup" v-if="showInfo" @click="showLearnMore"> 
        <div>
          <ul>
            <li class="listItem" v-for="(key, value) in gameInfo" :key="key" :value="value">{{ key }}  </li>
          </ul>
        </div>
      </div>
    </div>  
    <div class="gameInfo" @click="myGameHub()">MY GAME HUB </div>
    
    <div class="rowFlex">
        
       
        <div class="gameInfo" v-if="gameCount < 0">No Active Games</div>
        <div class="gameInfo">
          <div class="actionButton" > Active Games </div>
          <div class="rowFlex">
            <div class="actionButton" @click="setGameId(value)" v-for="(key, value) in myGames" :key="key" :value="value"> Game ID: {{ value }} {{ key['gameStatus'] }}</div>  
          </div>
        </div>
        <div class="gameInfo">
          <div class="actionButton" v-if="gameCount >= 0" @click="toggleOldGames()"> {{hideOldGamesStatus}} </div>
          <div v-if="hideOldGames" class="rowFlex">
            <div class="actionButton" @click="setGameId(value)" v-for="(key, value) in myOldGames" :key="key" :value="value"> Game ID: {{ value }} {{ key['gameStatus'] }}</div>  
          </div>
        </div>
        
    </div>    
    <div class="rowFlex"> 
      <div class="gameInfo">Game Id: {{ gameId }}  </div>
      <div class="gameInfo">Pot Balance: {{ potBalance }} {{this.tezosSymbol}} </div>
      <div> 
        <div class="gameInfo"> Bet up to pot </div>
        <select class="selectBox" v-model="thisBet"> 
          <option v-for="key in thisBets" :key="key" > {{ key }}  </option> 
        </select>
      </div>
      <div class="gameInfo">Your Bet: {{ thisBet }} {{this.tezosSymbol}} </div>
      
    </div> 
    <div class="gameInfo">Blockchain Status: {{ blockChainStatus }}  </div>
    <div 
      ref="container"
    >
    </div>
    <div class="rowFlex">
      <div class="actionButton" @click="betBC">Ante up and play!</div>     
      <select @change="toggleAceHigh()" class="selectBox" v-model="highLow"> PICK: 
        <option   v-for="key in ['Ace Low', 'Ace High']" :key="key" > {{ key }} </option>
      </select>
      <div class="actionButton" @click="continueBetBC">Bet On Acey Deucey</div>
      
    </div> 
  </div>
</template>


<!-- Add "scoped" attribute to limit CSS to this component only -->
<style >

</style>
