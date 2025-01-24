

<script>

import * as Three from 'three'
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls";

export default {
    name: 'aceyDuecy',
    props: ["socket", "wallet", "tezos"],
    components: { 
  },
  data () {
    return {

    }
  },

  created () {
    this.gameSize = window.innerWidth * 0.90
    console.log(this.gameSize)
    this.maxGameSize = 800
    this.board = new Three.Group()
        // General 
    this.scene = new Three.Scene();
    
    //Camera
    this.camera = new Three.PerspectiveCamera(45, 1, 1, 5000);
    this.camera.position.x = 0;
    this.camera.position.y = 0;
    this.camera.position.z = 200;
    this.camera.lookAt(this.scene.position)

    const loader = new Three.TextureLoader(); 
   
    this.backCardTexture = loader.load(require('../assets/pokerCard.png')); // Replace with the path to your image
    this.cardMaterial = new Three.MeshBasicMaterial({ map: this.backCardTexture });
    this.defaultGeometry = new Three.BoxGeometry(50, 100, 0.1, 1)
    // Materials
    //this.defaultMaterial = new Three.MeshMatcapMaterial({color: 'green', opacity:0.9, transparent:true});
    this.defaultMaterial = new Three.MeshNormalMaterial()

    this.socket.on('resizeGame', (width) => {
      this.resizeGameRender(width)
    }); 
  },
  mounted () {
    this.renderer = new Three.WebGLRenderer({antialias: true});
    this.renderer.setSize(this.gameSize, this.gameSize)
   
    this.$refs.container.appendChild(this.renderer.domElement);
    this.socket.emit("resizeGame", window.innerWidth)
    this.buildGame()
    this.renderer.render(this.scene, this.camera);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.flipCard()
    

  },
  methods: {
    animate: function() {
      this.controls.update();
      requestAnimationFrame(this.animate);  
      this.renderer.render(this.scene, this.camera);
    },
    flipCard: function() {
      //this.controls.update();
      requestAnimationFrame(this.flipCard);  
      let time = Date.now() * 0.001;
      this.card1.rotation.y = time;
      this.card2.rotation.y = -time;
      //this.card1.rotation.z = 0.5* ( 1 +  Math.sin( time ) );
      this.renderer.render(this.scene, this.camera);
    },
    buildGame: function() {
      const card1 = new Three.Mesh(this.defaultGeometry, this.cardMaterial); 
      const card2 = new Three.Mesh(this.defaultGeometry, this.cardMaterial); 
      this.card1 = card1
      this.card2 = card2
      card1.position.set(-40, 0, 0);
      this.board.add(card1)    
      card2.position.set(40, 0, 0);
      this.board.add(card2)   
      this.scene.add(this.board)                
    },
    resizeGameRender: function(width) {
      this.gameSize = width * 0.95
      if (this.gameSize > this.maxGameSize) {
        this.gameSize = this.maxGameSize
      }
      console.log(this.gameSize)
      this.renderer.setSize(this.gameSize, this.gameSize)
    }       
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
