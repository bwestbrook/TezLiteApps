

<script>

import * as Three from 'three'
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls";
import { RemoteSigner } from '@taquito/remote-signer';
import { GAME_WIDTH_FRACTION, MAX_GAME_SIZE, ORACLE_ADDRESS, NODE_URL, AD_CONTRACT_ADDRESS, AD_GAME_INFO} from '../constants'

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
      tezosSymbol: 'ꜩ',
      potBalance: 0,
      ante: 0.5, 
      betIncrement: 0.25, 
      thisBet: 0.5,
      thisBets: []

    }
  },

  created () {
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
    this.aceSpadeTexture = this.loader.load(require('../assets/Spade-Ace.png')); 
    this.kingSpadeTexture = this.loader.load(require('../assets/Spade-King.png')); 

    this.cardGeometry = new Three.BoxGeometry(50, 100, 0.1, 1)
    //Socket 
    this.socket.on('resizeGame', (width) => {
      this.resizeGameRender(width)
    }); 
    this.socket.on('newRandomNumber', (randomNumber) => {
      console.log("RN", randomNumber)
    }); 
    
    try {
        const sub = this.tezos.stream.subscribeEvent({
            tag: 'betMade',
            address: AD_CONTRACT_ADDRESS,
            //excludeFailedOperations: true
        });
        sub.on('data', (data) => {
            //const transactionBlockLevel = data.level
            console.log('numberRequested: ', data)
            console.log(this.socket)
            this.socket.emit("getRandomNumber", 100)
        })
        } catch (e) {
        console.log(e);
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
    this.getPotBalance()
    this.getGamesFromContractBC()
  },
  methods: {
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
      requestAnimationFrame(this.flipCards);  
      //let time = Date.now() * 0.001;
      const targetRotation = 180
      let currentRotation = 0
      let rotationIncrement = 0.001; // Adjust based on desired animation speed
      this.renderer.render(this.scene, this.camera);
      currentRotation += rotationIncrement;     
      if (currentRotation >= targetRotation) {
        console.log('a.', currentRotation)
        currentRotation = targetRotation;
      }
      this.card1.rotation.y = -currentRotation;
      this.card2.rotation.y = currentRotation;
     
      this.loader.load(require('../assets/Spade-Ace.png'), (texture) => {
        this.card1Texture.dispose(); // Dispose old texture
        this.card1Texture = texture;
        this.card1.material.map = texture;
        this.card1.material.needsUpdate = true;
      });
      this.loader.load(require('../assets/Spade-King.png'), (texture) => {
        this.card2Texture.dispose(); // Dispose old texture
        this.card2Texture = texture;
        this.card2.material.map = texture;
        this.card2.material.needsUpdate = true;
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
    async continueBet() {
      //const startTime = Date.now() * 0.0001;
      this.flipCards(0)
      const games = await this.getGamesFromContractBC()
      const allGames = await games.valueMap
      const myObject = Object.fromEntries(allGames);
      const allGamesObj =  Object.values(myObject)
      let gameId = 2
      console.log(allGamesObj[gameId])
      for (let game of allGamesObj) {

        //let aceHigh = allGames[game]['aceHigh'].toNumber()
        console.log(game, allGames[game])
      }
      
      // SET GAME ID DYANMICALLy

      //this.continueBetBC()

    },
    // Interact with the contract
    async continueBetBC() {      
      const activeAccount = await this.wallet.client.getActiveAccount()   
      if (!activeAccount) {
          return
      }    
      this.getSigner(activeAccount)
      await this.tezos.wallet
          .at(AD_CONTRACT_ADDRESS)
          .then((contract) => {
              return contract.methodsObject.bet({
                extraBet: 750000,
                halfBet: 250000,
                aceHigh: 1
                }).send({amount: 0.5})
          })
          .then((op) => {
              console.log(`Waiting for ${op.opHash} to be confirmed...`);
              return op.confirmation().then(() => op.opHash)
          })
          .then((hash) => {
              console.log(`Operation injected: https://ghost.tzstats.com/${hash}`)
              this.getPotBalance()})
          .catch((error) => console.log(`Error3: ${JSON.stringify(error, null, 2)}`));
    }, 
    async betBC() {      
      const activeAccount = await this.wallet.client.getActiveAccount()   
      if (!activeAccount) {
          return
      }    

      /// 
      let aceHigh = 0
      if (this.highLow == 'Ace High') {
        aceHigh = 1
      } else {
        aceHigh = 0
      }
      this.getSigner(activeAccount)
      await this.tezos.wallet
          .at(AD_CONTRACT_ADDRESS)
          .then((contract) => {
              return contract.methodsObject.bet({
                extraBet: 750000,
                halfBet: 250000,
                aceHigh: aceHigh
                }).send({amount: 0.5})
          })
          .then((op) => {
              console.log(`Waiting for ${op.opHash} to be confirmed...`);
              return op.confirmation().then(() => op.opHash)
          })
          .then((hash) => {
              console.log(`Operation injected: https://ghost.tzstats.com/${hash}`)
              this.getPotBalance()
              this.flipCards()
              this.card3.visible = true
          })
          .catch((error) => console.log(`Error3: ${JSON.stringify(error, null, 2)}`));
    }, 
    async getRandomNumberBC() {      
      const activeAccount = await this.wallet.client.getActiveAccount()   
      if (!activeAccount) {
          return
      }    
      this.getSigner(activeAccount)
      await this.tezos.wallet
        .at(ORACLE_ADDRESS)
        .then((contract) => {
            return contract.methodsObject.default().send()
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
    // Read the contract
    async getPotBalance() {
    const contract = await this.tezos.wallet.at(AD_CONTRACT_ADDRESS)
    const storage = await contract.storage()
    this.potBalance = storage.pot.toNumber() * 1e-6
    this.thisBets = []
    let bet = this.ante
    while (bet < this.potBalance + this.betIncrement) {
      this.thisBets.push(bet)
      bet += this.betIncrement
    }
    },
    // Read the contract
    async getGamesFromContractBC() {
      const contract = await this.tezos.wallet.at(AD_CONTRACT_ADDRESS)
      const storage = await contract.storage()        
      const games = await storage.games
      for (let game in games) {
        console.log('a')
        console.log(games[game].value)
      }
      return games
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
            <li v-for="(key, value) in gameInfo" :key="key" :value="value">{{ key }}</li>
          </ul>
        </div>
      </div>
    </div>  
    <div class="rowFlex">
        <div class="selectBox">MY GAME HUB </div>
    </div>    
    <div class="rowFlex"> 
      <div class="selectBox">Pot Balance: {{ potBalance }} {{this.tezosSymbol}} </div>
      <div class="selectBox">Your Bet: {{ thisBet }} {{this.tezosSymbol}} </div>
    </div> 
    <div 
      @click="flipCard"
      class="mainBody"
      ref="container"
    >
    </div>

    <div class="rowFlex">
      <select class="selectBox" v-model="highLow"> PICK: 
        <option v-for="key in ['Ace Low', 'Ace High']" :key="key" > {{ key }} </option>
      </select>
      <div class="actionButton" @click="betBC">Ante up and play!</div>     
      <div class="actionButton" @click="continueBet">Bet On Acey Deucey</div>
      <select class="selectBox" v-model="thisBet"> PICK: 
        <option v-for="key in thisBets" :key="key" > {{ key }} </option>
      </select>
      <div class="actionButton" @click="getRandomNumberBC"> Ask the Oracle </div>
    </div> 
  </div>
</template>


<!-- Add "scoped" attribute to limit CSS to this component only -->
<style >

</style>
