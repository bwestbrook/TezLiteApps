

<script>

import * as Three from 'three'
import { toRaw } from 'vue';
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls";
import { RemoteSigner } from '@taquito/remote-signer';
import { GAME_WIDTH_FRACTION, MAX_GAME_SIZE, NODE_URL, AD_CONTRACT_ADDRESS, AD_GAME_INFO} from '../constants'
//import { time } from 'node:console';



export default {
    name: 'aceyDuecy',
    props: ["socket", "wallet", "tezos"],
    components: { 
  },
  data () {
    return {
      pollInterval: null,
      gameInfo: AD_GAME_INFO,
      showInfo: false, 
      needsLastCard: false,
      highLow: 'Ace High',
      aceHigh: 1,
      blockChainStatus: '',
      tezosSymbol: 'ꜩ',
      gameId: 'NA', 
      lastGameId: -1,
      firstCard: -1,
      secondCard: -1,
      lastCard: 0,
      potBalance: 0,
      ante: 0.2, 
      fee: 0.0,
      thisBet: 0.1,
      myPendingGames: {},
      myOldGames: {},
      myGames: {},
      gameCount: -1,
      thisBets: [0.1, 0.5, 1, 5, 10],
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
    this.camera.position.y = -200;
    this.camera.position.z = 175;
    this.camera.lookAt(this.scene.position)
    this.degrees = 0
    this.loader = new Three.TextureLoader();
    this.tableGeometry = new Three.BoxGeometry(300, 600, 100, 1)
    this.tableMaterialLoader = require('../assets/table2.jpg')
    
    this.tableTexture = this.loader.load(this.tableMaterialLoader)
    this.tableMaterial = new Three.MeshBasicMaterial({ map: this.tableTexture });
    this.pokerCardLoader = require('../assets/pokerCard.png')
    this.pokerCardTexture = this.loader.load(this.pokerCardLoader); 
    this.card1Texture = this.loader.load(this.pokerCardLoader); 
    this.card2Texture = this.loader.load(this.pokerCardLoader); 
    this.card3Texture = this.loader.load(this.pokerCardLoader);
    this.card1Material = new Three.MeshBasicMaterial({ map: this.card1Texture });
    this.card2Material = new Three.MeshBasicMaterial({ map: this.card2Texture });
    this.card3Material = new Three.MeshBasicMaterial({ map: this.card2Texture });
    this.pokerCardMaterial = new Three.MeshBasicMaterial({ map: this.pokerCardTexture });
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
    this.cardGeometry = new Three.BoxGeometry(50, 100, 0.5, 1)
    //Socket 
    this.socket.on('resizeGame', (width) => {
      this.resizeGameRender(width)
    }); 
  },
  mounted () {
    this.blockChainStatus = 'None'   
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
    this.monitorContract()
    const n_games = Object.keys(toRaw(this.myGames)).length + 1
    this.lastGameId = n_games
    // Then every N seconds
    this.pollInterval = setInterval(() => {
      //await fetch(this.apiUrl);     
      this.monitorContract();
    }, 6000); // 5 seconds
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
      //this.blockChainStatus = 'Flipping'
      if (this.firstCard < 0 || this.secondCard < 0) {
        const card1asset = this.pokerCardLoader
        const card2asset = this.pokerCardLoader
        const card3asset = this.pokerCardLoader
        this.loadCardAsset(1, card1asset)
        this.loadCardAsset(2, card2asset)
        this.loadCardAsset(3, card3asset)
      } else if (this.lastCard <= 0) {
        const card1asset = this.deck[this.firstCard]
        const card2asset = this.deck[this.secondCard]
        const card3asset = this.pokerCardLoader
        this.loadCardAsset(1, card1asset)
        this.loadCardAsset(2, card2asset)
        this.loadCardAsset(3, card3asset)
      } else {
        const card1asset = this.deck[this.firstCard]
        const card2asset = this.deck[this.secondCard]
        const card3asset = this.deck[this.lastCard] 
        this.loadCardAsset(1, card1asset)
        this.loadCardAsset(2, card2asset)
        this.loadCardAsset(3, card3asset)
      }
    },
    flipCard(frontCard, backCard) {
      const duration = 1200 // ms
      const start = performance.now()
      const startRotation = 0
      const targetRotation = Math.PI 
      const liftAmount = 64
      //const maxOffset = 5 
      //const startZFront = frontCard.position.z
      //const startZBack = backCard.position.z
      //const startX = frontCard.position.x
      //const startY = frontCard.position.y
      //const offsetX = (Math.random() - 0.5) * maxOffset
      //const offsetY = (Math.random() - 0.5) * maxOffset
      const offsetRot = (Math.random() - 0.5) * 0.15 // subtle twist

      const animate = (time) => {
        const elapsed = time - start
        const t = Math.min(elapsed / duration, 1)
        // ease-in-out
        const eased = t < 0.5
          ? 2 * t * t
          : 1 - Math.pow(-2 * t + 2, 2) / 2    
        const rot = startRotation + (targetRotation - startRotation) * eased
        const rot2 = startRotation + (offsetRot - startRotation) * eased
        const lift = Math.sin(Math.PI * t) * liftAmount
        frontCard.rotation.y = rot
        backCard.rotation.y = rot
        frontCard.rotation.z = rot2
        backCard.rotation.z = rot2
        frontCard.rotation.y = rot
        backCard.rotation.y = rot
        frontCard.position.z = lift
        backCard.position.z = lift - 0.2
         if (frontCard.rotation.y % (2 * Math.PI) > Math.PI / 2) {
          backCard.visible = false;
          frontCard.visible = true;
        } else {
          backCard.visible = true;
          frontCard.visible = false;
        }
        if (t < 1) {
          requestAnimationFrame(animate)
        } 
        
      }

      requestAnimationFrame(animate)
    },
    async loadCardAsset(card, cardasset) {
      this.loader.load(cardasset, (texture) => {
        this.cardTextures[card - 1].dispose(); // Dispose old texture
        this.cardTextures[card - 1] = texture;
        this.cards[card - 1].material.map = texture;
        this.cards[card - 1].material.needsUpdate = true;
        console.log('CHEEECCKING')
        console.log(this.myGames[this.gameId].gameStatus)
        this.flipCard(this.cards[0], this.backCards[0]);
        this.flipCard(this.cards[1], this.backCards[1]);
        this.flipCard(this.cards[2], this.backCards[2]); 
      });
    },
    async buildGame() {      
      this.table = new Three.Mesh(this.tableGeometry, this.tableMaterial); 
      this.table.position.set(0, 0, -50);     
      this.card1 = new Three.Mesh(this.cardGeometry, this.card1Material);      
      this.card1.position.set(-60, -30, 0);
      this.backCard1 =  new Three.Mesh(this.cardGeometry, this.pokerCardMaterial); 
      this.backCard1.position.set(-60, -30, -0.2)
      this.card2 = new Three.Mesh(this.cardGeometry, this.card2Material); 
      this.card2.position.set(60, -30, 0);
      this.backCard2 =  new Three.Mesh(this.cardGeometry, this.pokerCardMaterial); 
      this.backCard2.position.set(60, -30, -0.2)     
      this.card3 = new Three.Mesh(this.cardGeometry, this.card3Material); 
      this.card3.position.set(0, 50, 0);
      this.backCard3 =  new Three.Mesh(this.cardGeometry, this.pokerCardMaterial); 
      this.backCard3.position.set(0, 50, -0.2)      
      this.card3.visible = true
      this.backCard3.visible = true
      await this.board.add(this.table)
      await this.board.add(this.card1)    
      await this.board.add(this.backCard1)
      await this.board.add(this.card2)    
      await this.board.add(this.backCard2)  
      await this.board.add(this.card3)   
      await this.board.add(this.backCard3) 
      await this.scene.add(this.board)   
      this.cards = [this.card1, this.card2, this.card3]       
      this.backCards = [this.backCard1, this.backCard2, this.backCard3]      
    },
    async resetGame() {    
      this.loadCardAsset(1, this.pokerCardLoader)  
      this.loadCardAsset(2, this.pokerCardLoader)  
      this.loadCardAsset(3, this.pokerCardLoader)  
    },
    async resizeGameRender(width) {
      this.gameSize = width * GAME_WIDTH_FRACTION
      if (this.gameSize > this.maxGameSize) {
        this.gameSize = this.maxGameSize
      }
      await this.renderer.setSize(this.gameSize, this.gameSize)
    },  
    // Interact with the contract    
    async startGameBC() {        
      const activeAccount = await this.wallet.client.getActiveAccount()   
      if (!activeAccount) {
          return
      }     
      let totalBet = Number(this.ante) + this.fee
      totalBet = Number(totalBet).toFixed(1)
      let ts = this.timestamp()
      let gameBcId = activeAccount['address'] + '-' + ts + '-R1'
      this.loadGame = false
      this.blockChainStatus = 'Submitting Bet'
      this.resetGame()
      const n_games = Object.keys(toRaw(this.myGames)).length + 1
      this.gameId = n_games
      await this.getSigner(activeAccount)
      await this.tezos.wallet
          .at(AD_CONTRACT_ADDRESS)
          .then((contract) => {
            return contract.methods.startGame(gameBcId).send({amount: totalBet})
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
      let gameBcId = this.myGames[this.gameId].gameId
      this.blockChainStatus = 'Submitting Bet'
      this.needsLastCard = true
      let totalBet = Number(this.thisBet) 
      totalBet = Number(totalBet).toFixed(1)
      await this.getSigner(activeAccount)
      await this.tezos.wallet
          .at(AD_CONTRACT_ADDRESS)
          .then((contract) => {
            return contract.methodsObject.makeBet(gameBcId).send({amount: totalBet})
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
      //console.log('getting pot balance')
      const response = await fetch(this.apiUrl);
      //console.log('api response')
      const data = await response.json();
      //console.log(data)
      this.potBalance = data['pot'] * 1e-6
      this.potBalance = Number(data['pot'] * 1e-6).toFixed(3)
    },
    async getGamesFromContractBC() {
      const activeAccount = await this.wallet.client.getActiveAccount()   
      if (!activeAccount) {
          return
      } 
      const response = await fetch(this.apiUrl);     
      const data = await response.json();
       // minimal diffing
      this.myGames = {}
      this.myOldGames = {}
      this.myPendingGames = {}
      let i = 0
      for (let game in data['games']) {
        if (data['games'][game]['player'] == activeAccount.address) {
          if (data['games'][game]['player'] == activeAccount.address) {
            i ++
            this.gameCount = i
            this.myGames[this.gameCount] = {
                gameId: game,
                gameStatus: data['games'][game]['status'],
                flipped: false
            }
            if (Number(data['games'][game]['status']) == 1){
              this.myPendingGames[this.gameCount] = {
                gameId: game,
                gameStatus: data['games'][game]['status'],
                flipped: false
              }
            } else if (Number(data['games'][game]['status']) >= 2) {
              this.myOldGames[this.gameCount] = {
                gameId: game,
                gameStatus: data['games'][game]['status'],
                flipped: false
              }
            }           
          }
        }         
      }
    },
    async loadGameInfo() {
      const response = await fetch(this.apiUrl);
      const data = await response.json();
      console.log(this.myGames[this.gameId]['gameId'])
      let gameBcId = this.myGames[this.gameId]['gameId']
      console.log('loading loading', data['games'][gameBcId] )
      this.firstCard = Number(data['games'][gameBcId]['card1'])
      this.secondCard = Number(data['games'][gameBcId]['card2'])
      this.lastCard = Number(data['games'][gameBcId]['card3'])
      console.log(this.firstCard, this.secondCard, this.lastCard)
      if (this.lastCard >= 0) {
        this.card3.visible = true
        this.backCard3.visible = true
      } 
      let gameStatus = ''
      if (data['games'][gameBcId]['status'] == '0') {
        gameStatus = 'Waiting for first card32232342342s ' + this.gameId 
      } else if (data['games'][gameBcId]['status'] == '1') {
        gameStatus = 'Play for Acey Duecey in Game ' + this.gameId 
      } else if (data['games'][gameBcId]['status'] == '2') {
        gameStatus = 'Waiting for final card ' + this.gameId 
      } else if (data['games'][gameBcId]['status'] == '3') {
        gameStatus = 'Game Over: ' + this.gameId + ' Win!'            
      } else if (data['games'][gameBcId]['status'] == '4') {
        gameStatus = 'Game Over: ' + this.gameId + ' Pair Loss'
      } else if (data['games'][gameBcId]['status'] == '5') {
        gameStatus = 'Game Over: ' + this.gameId + ' Loss'
      } else {
        gameStatus = 'None'
      }
      this.blockChainStatus = gameStatus
      this.resetGame()
      await this.flipCards()
    },
    async monitorContract() {
      await this.getGamesFromContractBC()
      await this.getPotBalance() 
      const n_games = Object.keys(toRaw(this.myGames)).length
      //console.log('GAME COUNT', n_games)
      if (Number.isNaN(this.gameId)) {
        return
      }
      if (! this.gameId) {
        return
      }

      if (this.gameId == 'NA') {
        return
      } else if (Number(this.gameId) > n_games) {
        return
      }

      
      
      if (! this.lastGameId == this.gameId || this.needsLastCard) {
        console.log('FLIPP ', this.gameId, this.lastGameId)
        console.log(! this.lastGameId == this.gameId)
        this.loadGameInfo()
      }
      this.lastGameId = this.gameId 
  
      if (this.gameCount < 0) {
        this.blockChainStatus = 'User has no games' 
      } 
    },
    // Render Interface
    async setGameId(gameId) {      
      this.gameId = gameId
      console.log('changing to', this.gameId)
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
      await this.getGamesFromContractBC()
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
    },
    timestamp() {
    const d = new Date();
    const p = n => n.toString().padStart(2, '0');
    return `${d.getFullYear()}_${p(d.getMonth()+1)}_${p(d.getDate())}_${p(d.getHours())}_${p(d.getMinutes())}`;
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
    <div class="gameInfo">{{ blockChainStatus }}  </div>
    <div 
      ref="container"
    >
    <div class="rowFlex">
      <div class="actionButton" @click="startGameBC">Ante up and play!</div>     
      <select @change="toggleAceHigh()" class="selectBox" v-model="highLow"> PICK: 
        <option   v-for="key in ['Ace Low', 'Ace High']" :key="key" > {{ key }} </option>
      </select>
      <div class="actionButton" @click="continueBetBC">Bet On Acey Deucey</div>
    </div> 
    </div>
    <div class="gameInfo" @click="myGameHub()">MY GAME HUB </div>
    <div class="rowFlex">
        <div class="gameInfo" v-if="gameCount < 0">No Active Games</div>
        <div class="gameInfo">
          <div class="actionButton" > Active Games </div>
          <div class="rowFlex">
            <div class="actionButton" @click="setGameId(value)" v-for="(key, value) in myPendingGames" :key="key" :value="value"> Game ID: {{ value }} </div>  
          </div>
        </div>
        <div class="gameInfo">
          <div class="actionButton" v-if="gameCount >= 0" @click="toggleOldGames()"> {{hideOldGamesStatus}} </div>
          <div v-if="hideOldGames" class="rowFlex">
            <div class="actionButton" @click="setGameId(value)" v-for="(key, value) in myOldGames" :key="key" :value="value"> Game ID: {{ value }} </div>  
          </div>
        </div>
    </div>  

  </div>
</template>


<!-- Add "scoped" attribute to limit CSS to this component only -->
<style >

</style>
