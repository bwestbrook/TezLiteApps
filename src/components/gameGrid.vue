<script>
import * as Three from 'three'
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls";

export default {
  name: 'gameGrid',
  data() {
    return {
      width: 10,
      rotate: false,
      playX: 0,
      playY: 0,
      clickX: 0,
      clickY: 0,
      cameraX: 0,
      cameraY: 0,
      moveMade: false,
      playerColor: 'red',
      playerTurn: 1, 
      gamePaused: false,
      halfTurn: false,
      player1Plays: {},
      player2Plays: {}
    }
  },
  props: ['socket', 'activeGameId', 'windowWidth', 'windowHeight'],

  created () {
    this.intvl = 0.3
    this.gameSize = this.windowWidth * 0.6
    this.board = new Three.Group(),
    // Materials
    this.defaultGeometry = new Three.SphereGeometry(0.05, 32, 16)
    this.defaultMaterial = new Three.MeshNormalMaterial()
    this.highlightGeometry = new Three.BoxGeometry(0.1, 0.1, 0.1)
    this.highlightMaterial = new Three.MeshMatcapMaterial( {color:'green'} )
    this.player1Geometry = new Three.BoxGeometry(0.1, 0.1, 0.1)
    this.player1Material = new Three.MeshMatcapMaterial( {color: 'red',  opacity: 0.5} )
    this.player2Geometry = new Three.BoxGeometry(0.1, 0.1, 0.1)
    this.player2Material = new Three.MeshMatcapMaterial( {color: 'blue',  opacity: 0.5} )
    // General 
    this.scene = new Three.Scene();
    this.renderer = new Three.WebGLRenderer({antialias: true});
    this.renderer.setSize(this.gameSize, this.gameSize)
    //Camera
    this.camera = new Three.PerspectiveCamera(45, 1, 0.5, 5000);
    this.camera.position.x = 2;
    this.camera.position.y = 0.5;
    this.camera.position.z = 2;
    this.camera.lookAt(this.scene.position)
  },
  mounted() {
    this.buildBoard()
    this.socket.emit("initGameGrid", 0)
    this.$refs.container.appendChild(this.renderer.domElement);
    this.renderer.render(this.scene, this.camera);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.animate()
    // Set up socket to receive from server
    this.socket.on('gameGrid', (gameGrid) => {
      //
      this.gameGrid = gameGrid
    });
    this.socket.on('resizeGame', (width) => {
      //
      console.log(width)
      this.resizeGameRender(width)
    });
  },
  methods: {
    // Three
    animate: function() {
      this.controls.update();
      requestAnimationFrame(this.animate);  
      this.renderer.render(this.scene, this.camera);
    },
    // event handling
    checkClickDown: function(evt) {
      this.rotate = true
      this.clickX = evt.x
      this.clickY = evt.y 
      this.playX = evt.x
      this.playY = evt.y   
    },
    checkClickUp: function() {
      this.rotate = false
    },
    submitMove: function() {
      if (this.playerColor === 'red') {
        this.playerColor = 'blue'
      } else {
        this.playerColor = 'red'
      }
    },
    // Game Grid Rendering
    buildBoard: function() {
        let i = -1
        for (i; i < 3; i++) {
            let j = -1
            for (j; j < 3; j++) {
                let k = -1
                for (k; k < 3; k++) {
                    let vertex;
                    vertex = new Three.Mesh(this.defaultGeometry, this.defaultMaterial);  
                    vertex.position.set(i * this.intvl - 0.5 * this.intvl, j * this.intvl - 0.5 * this.intvl, k * this.intvl - 0.5 * this.intvl);
                    vertex.coords = [i, j, k]
                    this.board.add(vertex)
                }
            }
        }
      this.scene.add(this.board)
    },
    highlightMove: function(evt) {
      if (this.gamePaused) {
        return
      }
      const intersects = this.findIntersects(evt)
      this.updateGridRender()
      if (intersects.length > 0) {
        const mousedVertex = intersects[0]
        mousedVertex.object.material = this.highlightMaterial
        mousedVertex.object.geometry = this.highlightGeometry
      } 
    },
    makeMove: function(evt) {  
      const intersects = this.findIntersects(evt)
      if (intersects.length > 0) {
          let clickedVertex = intersects[0]
          const i = clickedVertex.object.coords[0]
          const j = clickedVertex.object.coords[1]
          const k = clickedVertex.object.coords[2]
          if (this.gameGrid[i][j][k] < 0) {
              if (this.gamePaused) {
                this.gameGrid[i][j][k] = 0
              }
              this.gamePaused = false
          } else if (this.gameGrid[i][j][k] == 0 && !this.gamePaused) {
            this.gameGrid[i][j][k] = -1 * this.playerTurn
            this.gamePaused = true
          } else {
            this.gamePaused = true
          }
      }
      this.updateGridRender()
      this.socket.emit("updateGameGrid",this.gameGrid)
    },
    resizeGameRender: function(width) {
        this.gameSize = width * 0.65
        this.renderer.setSize(this.gameSize, this.gameSize)
    },
    // Game Play Utilities
    updateGridRender: function() {
      if (!this.gameGrid) {
        return
      }
      let verticies;
      verticies = this.board.children
      let i = 0;
      for (i; i < verticies.length; i++) {
          let thisVertex;
          thisVertex = verticies[i]
          const x = thisVertex.coords[0]
          const y = thisVertex.coords[1]
          const z = thisVertex.coords[2]
          const gameGridOwner = this.gameGrid[x][y][z]
          if (gameGridOwner == 0) {
            thisVertex.material = this.defaultMaterial
            thisVertex.geometry = this.defaultGeometry
          } else if (gameGridOwner == 1 || gameGridOwner == -1) {
            thisVertex.material = this.player1Material
            thisVertex.geometry = this.player1Geometry
          }
          else if (gameGridOwner == 2) {
            thisVertex.material = this.player2Material
            thisVertex.geometry = this.player2Geometry
          }
      }
    },
    findIntersects: function(evt) {     
      if (this.mouseDown) {
          return [];
      }
      let intersects = []
      const raycaster = new Three.Raycaster();
      const pointer = new Three.Vector2();
      const offset_x = this.renderer.domElement.getBoundingClientRect().x
      const offset_y = this.renderer.domElement.getBoundingClientRect().y
      pointer.x = 2 * (evt.clientX - offset_x) / this.gameSize - 1
      pointer.y = -2 * (evt.clientY - offset_y) / this.gameSize + 1
      raycaster.setFromCamera( pointer, this.camera );     
      intersects = raycaster.intersectObjects(this.scene.children)
      return intersects
    },
    // Socket
    updateGameGrid: function(gameGrid) {
      this.gameGrid = gameGrid
    },
    resizeGame: function(width) {
      this.gameSize = width
      this.resizeGameRender()
    },
  }
}
</script>


<template>
  <div class="canvas-container" >     
      <div class="gameBox"
          @mousedown="checkClickDown"
          @mouseup="checkClickUp"   
          @mousemove="highlightMove"
          @click="makeMove"
          ref="container"
      >
      </div>
  </div>
</template>


<style scoped>
.gameContainer {
  display: flex;
  flex-direction: column;
  align-content: center;
  justify-content: center;
  border-style: inset;
  border: 5px;
  color: aliceblue;
  background-color: #000000;
  font-size: 20px;
}
.canvas-container {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  border-style: inset;
  border-radius: 2px;
  border-width: 5px;
  border-color: #fff;
}
.actionButton {
    justify-content: center;
    padding: 5px;
    margin: auto;
    border-style: inset;
    border-radius: 2px;
    border-width: 5px;
    color: #fff;
    border-color: #fff;
}
.gameBox {
    justify-content: center;
    padding: 5px;
    margin: 5px;
    border-style: solid;
    border-radius: 2px;
    border-width: 0px;
    color: #fff;
    border-color: #fff;
}
</style>