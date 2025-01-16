<script>
import * as Three from 'three'
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls";


let gameWinners = [[[-1, -1, -1], [0, 0, 0], [1, 1, 1], [2, 2, 2]],
 [[-1, -1, 2], [0, 0, 1], [1, 1, 0], [2, 2, -1]],
 [[2, -1, -1], [1, 0, 0], [0, 1, 1], [-1, 2, 2]],
 [[2, -1, 2], [1, 0, 1], [0, 1, 0], [-1, 2, -1]],
 [[-1, -1, -1], [-1, 0, 0], [-1, 1, 1], [-1, 2, 2]],
 [[0, -1, -1], [0, 0, 0], [0, 1, 1], [0, 2, 2]],
 [[1, -1, -1], [1, 0, 0], [1, 1, 1], [1, 2, 2]],
 [[2, -1, -1], [2, 0, 0], [2, 1, 1], [2, 2, 2]],
 [[-1, -1, 2], [-1, 0, 1], [-1, 1, 0], [-1, 2, -1]],
 [[0, -1, 2], [0, 0, 1], [0, 1, 0], [0, 2, -1]],
 [[1, -1, 2], [1, 0, 1], [1, 1, 0], [1, 2, -1]],
 [[2, -1, 2], [2, 0, 1], [2, 1, 0], [2, 2, -1]],
 [[-1, -1, -1], [0, -1, 0], [1, -1, 1], [2, -1, 2]],
 [[-1, 0, -1], [0, 0, 0], [1, 0, 1], [2, 0, 2]],
 [[-1, 1, -1], [0, 1, 0], [1, 1, 1], [2, 1, 2]],
 [[-1, 2, -1], [0, 2, 0], [1, 2, 1], [2, 2, 2]],
 [[-1, -1, 2], [0, -1, 1], [1, -1, 0], [2, -1, -1]],
 [[-1, 0, 2], [0, 0, 1], [1, 0, 0], [2, 0, -1]],
 [[-1, 1, 2], [0, 1, 1], [1, 1, 0], [2, 1, -1]],
 [[-1, 2, 2], [0, 2, 1], [1, 2, 0], [2, 2, -1]],
 [[-1, -1, -1], [0, 0, -1], [1, 1, -1], [2, 2, -1]],
 [[-1, -1, 0], [0, 0, 0], [1, 1, 0], [2, 2, 0]],
 [[-1, -1, 1], [0, 0, 1], [1, 1, 1], [2, 2, 1]],
 [[-1, -1, 2], [0, 0, 2], [1, 1, 2], [2, 2, 2]],
 [[2, -1, -1], [1, 0, -1], [0, 1, -1], [-1, 2, -1]],
 [[2, -1, 0], [1, 0, 0], [0, 1, 0], [-1, 2, 0]],
 [[2, -1, 1], [1, 0, 1], [0, 1, 1], [-1, 2, 1]],
 [[2, -1, 2], [1, 0, 2], [0, 1, 2], [-1, 2, 2]],
 [[-1, -1, -1], [0, -1, -1], [1, -1, -1], [2, -1, -1]],
 [[-1, -1, 0], [0, -1, 0], [1, -1, 0], [2, -1, 0]],
 [[-1, -1, 1], [0, -1, 1], [1, -1, 1], [2, -1, 1]],
 [[-1, -1, 2], [0, -1, 2], [1, -1, 2], [2, -1, 2]],
 [[-1, 0, -1], [0, 0, -1], [1, 0, -1], [2, 0, -1]],
 [[-1, 0, 0], [0, 0, 0], [1, 0, 0], [2, 0, 0]],
 [[-1, 0, 1], [0, 0, 1], [1, 0, 1], [2, 0, 1]],
 [[-1, 0, 2], [0, 0, 2], [1, 0, 2], [2, 0, 2]],
 [[-1, 1, -1], [0, 1, -1], [1, 1, -1], [2, 1, -1]],
 [[-1, 1, 0], [0, 1, 0], [1, 1, 0], [2, 1, 0]],
 [[-1, 1, 1], [0, 1, 1], [1, 1, 1], [2, 1, 1]],
 [[-1, 1, 2], [0, 1, 2], [1, 1, 2], [2, 1, 2]],
 [[-1, 2, -1], [0, 2, -1], [1, 2, -1], [2, 2, -1]],
 [[-1, 2, 0], [0, 2, 0], [1, 2, 0], [2, 2, 0]],
 [[-1, 2, 1], [0, 2, 1], [1, 2, 1], [2, 2, 1]],
 [[-1, 2, 2], [0, 2, 2], [1, 2, 2], [2, 2, 2]],
 [[-1, -1, -1], [-1, 0, -1], [-1, 1, -1], [-1, 2, -1]],
 [[0, -1, -1], [0, 0, -1], [0, 1, -1], [0, 2, -1]],
 [[1, -1, -1], [1, 0, -1], [1, 1, -1], [1, 2, -1]],
 [[2, -1, -1], [2, 0, -1], [2, 1, -1], [2, 2, -1]],
 [[-1, -1, 0], [-1, 0, 0], [-1, 1, 0], [-1, 2, 0]],
 [[0, -1, 0], [0, 0, 0], [0, 1, 0], [0, 2, 0]],
 [[1, -1, 0], [1, 0, 0], [1, 1, 0], [1, 2, 0]],
 [[2, -1, 0], [2, 0, 0], [2, 1, 0], [2, 2, 0]],
 [[-1, -1, 1], [-1, 0, 1], [-1, 1, 1], [-1, 2, 1]],
 [[0, -1, 1], [0, 0, 1], [0, 1, 1], [0, 2, 1]],
 [[1, -1, 1], [1, 0, 1], [1, 1, 1], [1, 2, 1]],
 [[2, -1, 1], [2, 0, 1], [2, 1, 1], [2, 2, 1]],
 [[-1, -1, 2], [-1, 0, 2], [-1, 1, 2], [-1, 2, 2]],
 [[0, -1, 2], [0, 0, 2], [0, 1, 2], [0, 2, 2]],
 [[1, -1, 2], [1, 0, 2], [1, 1, 2], [1, 2, 2]],
 [[2, -1, 2], [2, 0, 2], [2, 1, 2], [2, 2, 2]],
 [[-1, -1, -1], [-1, -1, 0], [-1, -1, 1], [-1, -1, 2]],
 [[-1, 0, -1], [-1, 0, 0], [-1, 0, 1], [-1, 0, 2]],
 [[-1, 1, -1], [-1, 1, 0], [-1, 1, 1], [-1, 1, 2]],
 [[-1, 2, -1], [-1, 2, 0], [-1, 2, 1], [-1, 2, 2]],
 [[0, -1, -1], [0, -1, 0], [0, -1, 1], [0, -1, 2]],
 [[0, 0, -1], [0, 0, 0], [0, 0, 1], [0, 0, 2]],
 [[0, 1, -1], [0, 1, 0], [0, 1, 1], [0, 1, 2]],
 [[0, 2, -1], [0, 2, 0], [0, 2, 1], [0, 2, 2]],
 [[1, -1, -1], [1, -1, 0], [1, -1, 1], [1, -1, 2]],
 [[1, 0, -1], [1, 0, 0], [1, 0, 1], [1, 0, 2]],
 [[1, 1, -1], [1, 1, 0], [1, 1, 1], [1, 1, 2]],
 [[1, 2, -1], [1, 2, 0], [1, 2, 1], [1, 2, 2]],
 [[2, -1, -1], [2, -1, 0], [2, -1, 1], [2, -1, 2]],
 [[2, 0, -1], [2, 0, 0], [2, 0, 1], [2, 0, 2]],
 [[2, 1, -1], [2, 1, 0], [2, 1, 1], [2, 1, 2]],
 [[2, 2, -1], [2, 2, 0], [2, 2, 1], [2, 2, 2]]]


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
      playedPoint: [0, 0, 0],
      moveMade: false,
      playerColor: 'red',
      playerTurn: 2, 
      gamePaused: false,
      halfTurn: false,
      player1Plays: {},
      player2Plays: {},
      tempHighlights: [],
      allPaths: {}
      
    }
  },
  props: ['socket', 'activeGameId', 'windowWidth', 'windowHeight'],

  created () {
    this.intvl = 0.5
    this.gameSize = this.windowWidth * 0.9
    this.board = new Three.Group()
    // Geometry
    this.defaultGeometry = new Three.SphereGeometry(0.06, 32, 16)

    this.highlightGeometry = this.defaultGeometry
    this.playedGeometry = this.defaultGeometry
    // Materials
    this.defaultMaterial = new Three.MeshNormalMaterial()
    this.highlightMaterial = new Three.MeshMatcapMaterial( {color:'black', opacity: 0.75, transparent: true} )
    this.player1Material = new Three.MeshMatcapMaterial( {color: 'red',  opacity: 0.95, transparent: true} )
    this.player2Material = new Three.MeshMatcapMaterial( {color: 'blue',  opacity: 0.95, transparent: true} )
    this.defaultLineMaterial = new Three.MeshMatcapMaterial({color: 'green', opacity:0.3, transparent:true});
    //this.hightlightMaterial = new Three.MeshMatcapMaterial({color: 'red', opacity: 0.5, transparent: true});
    this.player1HightlightMaterial = new Three.MeshMatcapMaterial({color: 'red', opacity: 0.5, transparent: true});
    this.player2HightlightMaterial = new Three.MeshMatcapMaterial({color: 'blue', opacity: 0.5, transparent: true});
    //this.player2HightlightMaterial
    this.playedLineMaterial = new Three.MeshMatcapMaterial({color: 'red', opacity: 0.8, transparent: true});   
    this.playedMaterial = this.playedLineMaterial
    this.tubeRadius = 0.012
    // General 
    this.scene = new Three.Scene();
    this.renderer = new Three.WebGLRenderer({antialias: true});
    this.renderer.setSize(this.gameSize, this.gameSize)
    //Camera
    this.camera = new Three.PerspectiveCamera(45, 1, 1, 5000);
    this.camera.position.x = 2.5;
    this.camera.position.y = 0;
    this.camera.position.z = 2.5;
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
      this.gamePaused = false
      this.gameGrid = gameGrid
      this.updateGridRender()
      this.connectMoves(false)
    });
    this.socket.on('resizeGame', (width) => {
      //
      //
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
                    vertex.owner = 0
                    this.board.add(vertex)                  
                }
            }
        }
      this.addWinningLines()
      this.createConnectionLinks()
      this.scene.add(this.board)
    },
    addWinningLines: function() {    
      for (let i in gameWinners) {
          const start = this.makeThreeVector(gameWinners[i][0][0], gameWinners[i][0][1], gameWinners[i][0][2])
          const end = this.makeThreeVector(gameWinners[i][3][0], gameWinners[i][3][1], gameWinners[i][3][2])
          const path = new Three.LineCurve3(start, end);
          const tubeGeometry = new Three.TubeGeometry(path, 20, this.tubeRadius, 10, false);
          const line = new Three.Mesh(tubeGeometry, this.defaultLineMaterial)
          this.scene.add(line)
        }
    },
    createConnectionLinks: function() {
      for (let i in gameWinners) {
        let j = 0
        for (j; j < 3; j++) {
          const x1 = gameWinners[i][j][0]
          const y1 = gameWinners[i][j][1]
          const z1 = gameWinners[i][j][2]
          const x2 = gameWinners[i][j + 1][0]
          const y2 = gameWinners[i][j + 1][1]
          const z2 = gameWinners[i][j + 1][2]
          const start = this.makeThreeVector(x1, y1, z1)
          const end = this.makeThreeVector(x2, y2, z2)
          const lineId = 's'+ x1.toString()+  y1.toString() + z1.toString()+'e'+ x2.toString()+  y2.toString() + z2.toString()
          const path = new Three.LineCurve3(start, end);
          const tubeGeometry = new Three.TubeGeometry(path, 20, this.tubeRadius * 1.2, 10, false)
          const tube = this.makeConnectingTube(tubeGeometry)
          this.allPaths[lineId] = tube
          tube.visible = false
          tube.start = [x1, y1, z1]
          tube.end = [x2, y2, z2]
          this.scene.add(tube)
          }
        }
      
    },
    highlightMove: function(evt) {
      if (!this.gameGrid) {
        return
      }
      if (this.gamePaused) {
        return
      }
      const intersects = this.findIntersects(evt)
      this.updateGridRender()
      this.connectMoves()
      if (intersects.length > 0) {
        this.lastMousedVertex = intersects[0]
        if (this.lastMousedVertex.object.owner == 0) {
          this.lastMousedVertex.object.material = this.highlightMaterial
          this.lastMousedVertex.object.geometry = this.highlightGeometry
          const i = this.lastMousedVertex.object.coords[0]
          const j = this.lastMousedVertex.object.coords[1]
          const k = this.lastMousedVertex.object.coords[2]
          this.gameGrid[i][j][k] = -1 * this.playerTurn         
        } 
      } else {
        if (!this.gamePaused){
          let i = -1
          for (i; i < 3; i++) {
              let j = -1
              for (j; j < 3; j++) {
                  let k = -1
                  for (k; k < 3; k++) {
                    if (this.gameGrid[i][j][k] < 0) {
                          this.gameGrid[i][j][k] = 0
                      }
                    }
              }
            }
          }
        }
    },
    makeMove: function(evt) {  
      const intersects = this.findIntersects(evt)
      if (intersects.length > 0) {
          this.clickedVertex = intersects[0]
          const i = this.clickedVertex.object.coords[0]
          const j = this.clickedVertex.object.coords[1]
          const k = this.clickedVertex.object.coords[2]
          if (!this.gamePaused) {
            if (this.gameGrid[i][j][k] < 0) { //Already Highlighted by licked
              this.socket.emit("updatePlayedPoint", this.clickedVertex.object.coords)
              this.gamePaused = true
              
            } 
          } else {
            if (this.gameGrid[i][j][k] < 0) { //Already owned
              this.gameGrid[i][j][k] == 0
              this.gamePaused = false
            } else if (this.gameGrid[i][j][k] == this.playerTurn) { //Already owned
              this.gameGrid[i][j][k] == 0
              this.gamePaused = false
            } 
          }
      }
      this.lastClickedVertex = this.clickedVertex
      this.playedPoint = this.lastClickedVertex.object.coords
      this.updateGridRender()
      this.connectMoves(false)
      this.socket.emit("updateGameGrid",this.gameGrid)
      console.log('emit', this.playedPoint)
      
      
    },
    updateGridRender: function() {
      if (!this.gameGrid) {
        return
      }
      let verticies;
      verticies = this.board.children 
      for (let thl of this.tempHighlights) {
        thl.visible = false
      }
      for (let thisVertex of verticies) {
          if (thisVertex.material != this.defaultLineMaterial) {
            const x = thisVertex.coords[0]
            const y = thisVertex.coords[1]
            const z = thisVertex.coords[2]
            const gameGridOwner = this.gameGrid[x][y][z]
            thisVertex.owner = gameGridOwner
            if (gameGridOwner == 0) {
              thisVertex.material = this.defaultMaterial
              thisVertex.geometry = this.defaultGeometry
            } else if (Math.abs(gameGridOwner) == 1) {
              thisVertex.material = this.player1Material
              thisVertex.geometry = this.playedGeometry
            } else if (Math.abs(gameGridOwner) == 2 ) {
              thisVertex.material = this.player2Material
              thisVertex.geometry = this.playedGeometry
            } 
          }
        }    
    },
    connectMoves: function() {
      for (let i in gameWinners) {
        let j = 0
        //let istemp = false
        for (j; j < 3; j++) {
          const x1 = gameWinners[i][j][0]
          const y1 = gameWinners[i][j][1]
          const z1 = gameWinners[i][j][2]
          const x2 = gameWinners[i][j + 1][0]
          const y2 = gameWinners[i][j + 1][1]
          const z2 = gameWinners[i][j + 1][2]
          let gameGridOwner1 = this.gameGrid[x1][y1][z1]
          let gameGridOwner2 = this.gameGrid[x2][y2][z2]
          const lineId = 's'+ x1.toString()+  y1.toString() + z1.toString()+'e'+ x2.toString()+  y2.toString() + z2.toString()
          if (Math.abs(gameGridOwner1) == Math.abs(gameGridOwner2)) {
            if (gameGridOwner1 < 0 || gameGridOwner2 < 0) {
                this.allPaths[lineId].visible = true
            } else if (gameGridOwner1 > 0 || gameGridOwner2 > 0) {
                this.allPaths[lineId].visible = true
            }  
          } else {
                this.allPaths[lineId].visible = false
            }
        } 
    }
    },
    makeConnectingTube: function(tubeGeometry) {  
      let tube = {}
      if (this.playerTurn == 1) {
        tube = new Three.Mesh(tubeGeometry, this.player1HightlightMaterial)
      } else if (this.playerTurn == 2) {
        tube = new Three.Mesh(tubeGeometry, this.player2HightlightMaterial)
      } 
      return tube
    },
    makeThreeVector: function(x, y, z) {  
      //let vector = {}
      const vector = new Three.Vector3(
          x * this.intvl - 0.5 * this.intvl,
          y * this.intvl - 0.5 * this.intvl,
          z * this.intvl - 0.5 * this.intvl
      )
      return vector
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
      intersects = raycaster.intersectObjects(this.board.children)
      return intersects
    },
    getTempRange: function(position) {
      let range = []
      if (position == -1 ) {
        range = [-1, 0]
      } else if (position == 0 ) {
        range = [-1, 1]
      } else if (position == 1 ) {
        range = [0, 2]
      } else if (position == 2 ) {
        range = [1, 2]
      }
      return range
    },
    // Game Play Utilities
    // Socket
    resizeGameRender: function(width) {
        this.gameSize = width * 0.65
        this.renderer.setSize(this.gameSize, this.gameSize)
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