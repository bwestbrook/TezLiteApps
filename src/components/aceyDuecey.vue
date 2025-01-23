

<script>

import * as Three from 'three'
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls";

export default {
  name: 'aceyDuecy',
  props: [],
  components: { 
  },
  data () {
    return {

    }
  },
  created () {
    this.gameSize = 1000 * 0.6
    if (this.gameSize > 1000) {
      this.gameSize = 1000
    }
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
    
  },
  mounted () {
    this.renderer = new Three.WebGLRenderer({antialias: true});
    this.renderer.setSize(this.gameSize, this.gameSize)
   
    this.$refs.container.appendChild(this.renderer.domElement);
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
        }
       
  },
}
</script>

<template>
  <div class="mainBody" >        
      NEW GAME COMING SOON!!!!
      <div 
        @click="flipCard"
        class="mainBody"
        ref="container"
      >
      </div>
  </div>
</template>


<!-- Add "scoped" attribute to limit CSS to this component only -->
<style scoped>
.mainBody{
  margin:0px;
  padding:0px;
  display: flex;
  flex-direction: column;
  margin: auto;
}
.centerBody{
  display: flex;
  margin:auto;
  flex-direction: column;
  border-width: 2px;
  border-color: #fff;

}
.rules {
  align-content: stretch;
  text-align: justify;
  justify-content: center;
  flex-direction: column;
  color: white;
  margin:auto;
  border-style: inset;
  border-width: 5px;
  border-color: #fff;
}
</style>
