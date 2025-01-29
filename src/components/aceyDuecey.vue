

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
      highLow: 'Ace Low',
      blockChainStatus: 'No Activity',
      tezosSymbol: 'ꜩ',
      gameId: -1, 
      firstCard: -1,
      secondCard: -1,
      lastCard: 0,
      potBalance: 0,
      ante: 0.5, 
      betIncrement: 0.25, 
      thisBet: 0.5,
      myGames: {},
      thisBets: []
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
    this.card1Texture = this.loader.load(require('../assets/pokerCard.png')); 
    this.card2Texture = this.loader.load(require('../assets/pokerCard.png')); 
    this.card3Texture = this.loader.load(require('../assets/pokerCard.png'));
    this.card1Material = new Three.MeshBasicMaterial({ map: this.card1Texture });
    this.card2Material = new Three.MeshBasicMaterial({ map: this.card2Texture });
    this.card3Material = new Three.MeshBasicMaterial({ map: this.card2Texture });
    this.defaultGeometry = new Three.BoxGeometry(130, 130, 1, 1)
    ///
    this.cards = [
      require('../assets/pokerCard.png'),
      require('../assets/Spade-Two.jpeg'),
      require('../assets/Spade-Three.jpg'),
      require('../assets/Spade-Four.png'),
      require('../assets/Spade-Five.jpg'),
      require('../assets/Spade-Six.png'),
      require('../assets/Spade-Seven.jpg'),
      require('../assets/Spade-Eight.jpg'),
      require('../assets/Spade-Nine.jpg'),
      require('../assets/Spade-Ten.jpg'),  
      require('../assets/Spade-Jack.jpg'),
      require('../assets/Spade-Queen.png'), 
      require('../assets/Spade-King.png'),
      require('../assets/Spade-Ace.png')
         
    ]
    const path = require('path');
    const threeModulePath = require.resolve('three');
    console.log(path, threeModulePath)
    this.cardGeometry = new Three.BoxGeometry(50, 100, 0.1, 1)
    //Socket 
    this.socket.on('resizeGame', (width) => {
      this.resizeGameRender(width)
    }); 
    this.socket.on('newRandomNumber', (randomNumber) => {
      console.log("RN", randomNumber)
      this.randomNumber = randomNumber
    }); 
    try {
      const subFirstTwoCards = this.tezos.stream.subscribeEvent({
        tag: 'firstTwoCards',
        address: AD_CONTRACT_ADDRESS,
        //excludeFailedOperations: true
      });
      subFirstTwoCards.on('data', (data) => {   
        console.log('firstTwoCards')
        console.log(data.payload)
        this.gameId = data.payload[0]["int"]
        this.firstCard = data.payload[1]["int"]
        this.secondCard = data.payload[2]["int"]
        this.myGameHub()
        this.loadGame()
        this.blockChainStatus = 'Cards Dealt!'
      })
      const subLastCard = this.tezos.stream.subscribeEvent({
        tag: 'lastCard',
        address: AD_CONTRACT_ADDRESS,
        //excludeFailedOperations: true
      });
      subLastCard.on('data', (data) => {          
        console.log('lastCard')
        console.log(data.payload)
        this.gameId = data.payload[0]["int"]
        this.lastCard = data.payload[1]["int"]
        this.myGameHub()
        this.loadGame()
        this.blockChainStatus = 'Final Card Dealt!'
      })
      } catch (e) {
        console.log('Error', e);
    }
   
  },
  mounted () {
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
      if (this.lastCard == -1) {
        this.lastCard = 0
      }
      const card1asset = this.cards[this.firstCard]
      const card2asset = this.cards[this.secondCard]
      const card3asset = this.cards[this.lastCard]
      this.loader.load((card1asset), (texture) => {
        this.card1Texture.dispose(); // Dispose old texture
        this.card1Texture = texture;
        this.card1.material.map = texture;
        this.card1.material.needsUpdate = true;
      });
      this.loader.load((card2asset), (texture) => {
        this.card2Texture.dispose(); // Dispose old texture
        this.card2Texture = texture;
        this.card2.material.map = texture;
        this.card2.material.needsUpdate = true;
      });
      this.loader.load((card3asset), (texture) => {
        this.card3Texture.dispose(); // Dispose old texture
        this.card3Texture = texture;
        this.card3.material.map = texture;
        this.card3.material.needsUpdate = true;
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
      this.blockChainStatus = 'Submitting Bet'
      await this.getSigner(activeAccount)
      await this.tezos.wallet
          .at(AD_CONTRACT_ADDRESS)
          .then((contract) => {
            return contract.methodsObject.bet().send({amount: 0.5})
          })
          .then((op) => {
            console.log(`Waiting for ${op.opHash} to be confirmed...`);
            return op.confirmation().then(() => op.opHash)
          })
          .then((hash) => {
            console.log(`Operation injected: https://ghost.tzstats.com/${hash}`)
            this.blockChainStatus = 'Getting Cards'
          })
          .catch((error) => console.log(`Error3: ${JSON.stringify(error, null, 2)}`));
    }, 
    async continueBetBC() {      
      const activeAccount = await this.wallet.client.getActiveAccount()   
      if (!activeAccount) {
          return
      }    
      this.blockChainStatus = 'Submitting Bet'
      await this.getSigner(activeAccount)
      await this.tezos.wallet
          .at(AD_CONTRACT_ADDRESS)
          .then((contract) => {
            return contract.methodsObject.continueBet(this.gameId).send({amount: this.thisBet})
          })
          .then((op) => {
            console.log(`Waiting for ${op.opHash} to be confirmed...`);
            return op.confirmation().then(() => op.opHash)
          })
          .then((hash) => {
            console.log(`Operation injected: https://ghost.tzstats.com/${hash}`)
            this.blockChainStatus = 'Getting Final Card' 
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
      while (bet < this.potBalance + this.betIncrement) {
          this.thisBets.push(bet)
          bet += this.betIncrement
        }
    },
    async getGamesFromContractBC() {
      const activeAccount = await this.wallet.client.getActiveAccount()   
      if (!activeAccount) {
          return
      } 
      const response = await fetch(this.apiUrl);
      const data = await response.json();
      this.myGames = {}
      let i = 0
      for (let game in data['games']) {
        if (data['games'][game]['player'] == activeAccount.address) {
          let gameStatus = 'No Game'
          if (data['games'][game]['gameStatus'] == '1') {
            gameStatus = 'Play for Acey Duecey'
          } else if (data['games'][game]['gameStatus'] == '2') {
            gameStatus = 'Waiting For Card'
          } else if (data['games'][game]['gameStatus'] == '3') {
            gameStatus = 'Game Over Win'
          } else if (data['games'][game]['gameStatus'] == '4') {
            gameStatus = 'Game Over Loss'
          }else if (data['games'][game]['gameStatus'] == '5') {
            gameStatus = 'Game Over Pair Loss'
          }
          this.myGames[i] = {
            gameId: game,
            gameStatus: gameStatus
          }
        }
        i ++
      }
    },
    // Populate Interface
    async setGameId(gameId) {
      this.gameId = gameId
      this.loadGame()
    },
    async myGameHub() {
      this.getGamesFromContractBC()
      for (let game in this.myGames) {
        console.log(game, this.myGames[game])
      }
      this.getPotBalance()
    },
    async loadGame() {
      const response = await fetch(this.apiUrl);
      const data = await response.json();
      console.log(data['games'][this.gameId]['hand'])
      this.firstCard = Number(data['games'][this.gameId]['hand'][1])
      this.secondCard = Number(data['games'][this.gameId]['hand'][2])
      this.lastCard = Number(data['games'][this.gameId]['hand'][3])
      if (this.lastCard >= 1) {
        this.card3.visible = true
      } else {
        this.card3.visible = false
      }
      this.flipCards()
    },
    async showLearnMore() {
        if (this.showInfo)  {
            this.showInfo = false
        } else {
            this.showInfo = true
        }
    }
  },
}
</script>

<template>
  <div class="canvas-container" >        
    <div class="rowFlex">
      <div class="actionButtonHelp" @click="showLearnMore"> HOW TO PLAY </div>
        <div class="infoPopup" v-if="showInfo" @click="showLearnMore"> 
        <div>
          <ul>
            <li v-for="(key, value) in gameInfo" :key="key" :value="value">{{ key }}  </li>
          </ul>
        </div>
      </div>
    </div>  
    <div class="rowFlex">
        <div class="gameInfo">MY GAME HUB </div>
        <div class="actionButton" @click="setGameId(value)" v-for="(key, value) in myGames" :key="key" :value="value"> Game ID: {{ value }} {{ key['gameStatus'] }}</div>  
    </div>    
    <div class="rowFlex"> 
      <div class="gameInfo">Game Id: {{ gameId }}  </div>
      <div class="gameInfo">Pot Balance: {{ potBalance }} {{this.tezosSymbol}} </div>
      <div class="gameInfo">Your Bet: {{ thisBet }} {{this.tezosSymbol}} </div>
      <div class="gameInfo">Blockchain Status: {{ blockChainStatus }}  </div>
    </div> 
    <div 
      ref="container"
    >
    </div>
    <div class="rowFlex">
      <select class="selectBox" v-model="highLow"> PICK: 
        <option v-for="key in ['Ace Low', 'Ace High']" :key="key" > {{ key }} </option>
      </select>
      <div class="actionButton" @click="betBC">Ante up and play!</div>     
      <div class="actionButton" @click="continueBetBC">Bet On Acey Deucey</div>
      <div> 
        <div class="gameInfo"> Bet {{ thisBet }} {{ tezosSymbol }}</div>
        <select class="selectBox" v-model="thisBet"> 
          <option v-for="key in thisBets" :key="key" > {{ key }}  </option> 
        </select>
      </div>
    </div> 
  </div>
</template>


<!-- Add "scoped" attribute to limit CSS to this component only -->
<style >

</style>
