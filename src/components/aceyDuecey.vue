

<script>

import * as Three from 'three'
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls";
import { GAME_WIDTH_FRACTION, MAX_GAME_SIZE} from '../constants'

export default {
    name: 'aceyDuecy',
    props: ["socket", "wallet", "tezos"],
    components: { 
  },
  data () {
    return {

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
  },
  mounted () {
    this.renderer = new Three.WebGLRenderer({antialias: true});
    this.renderer.setSize(this.gameSize, this.gameSize)   
    this.$refs.container.appendChild(this.renderer.domElement);
    //this.socket.emit("resizeGame", window.innerWidth)
    this.buildGame()
    this.renderer.render(this.scene, this.camera);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.flipCard()
    this.socket.emit("resizeGame", window.innerWidth)
    

  },
  methods: {
    async animate() {
      this.controls.update();
      requestAnimationFrame(this.animate);  
      this.renderer.render(this.scene, this.camera);
    },
    async flipCard() {
      //this.controls.update();
      requestAnimationFrame(this.flipCard);  
      let time = Date.now() * 0.001;
      this.card1.rotation.y = time;
      this.card2.rotation.y = -time;
      //this.card1.rotation.z = 0.5* ( 1 +  Math.sin( time ) );
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
      !!! NEW GAME ALERT !!!
  </div>
</template>


<!-- Add "scoped" attribute to limit CSS to this component only -->
<style >

</style>
