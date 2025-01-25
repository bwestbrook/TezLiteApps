

<script>

import * as Three from 'three'
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls";
import { RemoteSigner } from '@taquito/remote-signer';
import { GAME_WIDTH_FRACTION, MAX_GAME_SIZE, ORACLE_ADDRESS, NODE_URL, AD_CONTRACT_ADDRESS} from '../constants'

export default {
    name: 'aceyDuecy',
    props: ["socket", "wallet", "tezos"],
    components: { 
  },
  data () {
    return {
      highLow: 'Ace Low',
      tezosSymbol: 'ꜩ'

    }
  },

  created () {
    //Three 
    this.gameSize = window.innerWidth * GAME_WIDTH_FRACTION
    this.maxGameSize = MAX_GAME_SIZE
    this.board = new Three.Group()
    this.scene = new Three.Scene();
    this.camera = new Three.PerspectiveCamera(45, 1, 1, 5000);
    this.camera.position.x = 0;
    this.camera.position.y = 0;
    this.camera.position.z = 200;
    this.camera.lookAt(this.scene.position)
    const loader = new Three.TextureLoader();    
    this.backCardTexture = loader.load(require('../assets/pokerCard.png')); 
    this.cardMaterial = new Three.MeshBasicMaterial({ map: this.backCardTexture });
    this.defaultGeometry = new Three.BoxGeometry(50, 100, 0.1, 1)
    //Socket 
    this.socket.on('resizeGame', (width) => {
      console.log("AD", width)
      this.resizeGameRender(width)
    }); 
    this.socket.on('newRandomNumber', (randomNumber) => {
      console.log("RN", randomNumber)
    }); 
    try {
        const sub = this.tezos.stream.subscribeEvent({
            tag: 'railLoss',
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
    

  },
  methods: {
    async showCards() {
      this.controls.update();
      requestAnimationFrame(this.showCards);  
      this.renderer.render(this.scene, this.camera);
    },
    async flipCard() {
      requestAnimationFrame(this.flipCard);  
      let time = Date.now() * 0.001;
      this.card1.rotation.y = time;
      this.card2.rotation.y = -time;
      this.renderer.render(this.scene, this.camera);
    },
    async buildGame() {
      const card1 = new Three.Mesh(this.defaultGeometry, this.cardMaterial); 
      const card2 = new Three.Mesh(this.defaultGeometry, this.cardMaterial); 
      this.card1 = card1
      this.card2 = card2
      card1.position.set(-40, 0, 0);
      await this.board.add(card1)    
      card2.position.set(40, 0, 0);
      await this.board.add(card2)   
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
      const games = await this.getGamesFromContractBC()
      console.log(games.valueMap)
      const allGames = await games.valueMap
      const myObject = Object.fromEntries(allGames);
      const allGamesObj =  Object.values(myObject)
      let gameId = 2
      let aceHigh = 0
      console.log(allGamesObj[gameId], gameId)
      for (let game of allGamesObj) {
        aceHigh = game['aceHigh'].toNumber()
        console.log(game, aceHigh)
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
              console.log(`Operation injected: https://ghost.tzstats.com/${hash}`)})
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
              console.log(`Operation injected: https://ghost.tzstats.com/${hash}`)})
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
    async getGamesFromContractBC() {
        const contract = await this.tezos.wallet.at(AD_CONTRACT_ADDRESS)
        const storage = await contract.storage()
        const games = await storage.games
        return games
      },
  },
}
</script>

<template>
  <div class="canvas-container" >        
      !!! NEW GAME ALERT !!!
      <div 
        @click="flipCard"
        class="mainBody"
        ref="container"
      >
      </div>
      <div class="rowFlex">
        <div class="actionButton" @click="betBC">Ante up and play!</div>
          <select class="txlRank" v-model="highLow">
                <option v-for="key in ['Ace Low', 'Ace High']" :key="key" > {{ key }} </option>
          </select>
        <div class="actionButton" @click="continueBet">Continue Hand</div>
        <div class="actionButton" @click="getRandomNumberBC"> Ask the Oracle </div>
      </div>
      


      
      !!! NEW GAME ALERT !!!
  </div>
</template>


<!-- Add "scoped" attribute to limit CSS to this component only -->
<style >

</style>
