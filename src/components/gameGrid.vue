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
      gamePlayable: true,
      playerColor: 'red',
      playerTurn: 1,
      walletTurn: 0,
      gameId: -1,
      walletPlayerTurn1: '',
      walletPlayerTurn2: '',
      gamePaused: false,
      halfTurn: false,
      player1Plays: {},
      player2Plays: {},
      tempHighlights: [],
      playersInGame: [],
      allPaths: {}
      
    }
  },
  props: ['socket', 'activeGameId', 'wallet', 'windowWidth', 'windowHeight'],

  created () {
    this.intvl = 0.5
    this.gameSize = this.windowWidth * 0.6
    if (this.gameSize > 1000) {
      this.gameSize = 1000
    }
    this.board = new Three.Group()
    // Geometry
    this.defaultGeometry = new Three.SphereGeometry(0.08, 32, 16)
    this.highlightGeometry = this.defaultGeometry
    this.playedGeometry = this.defaultGeometry
    // Materials
    this.defaultMaterial = new Three.MeshNormalMaterial()
    this.highlightMaterial = new Three.MeshMatcapMaterial( {color:'black', opacity: 0.75, transparent: true} )
    this.player1Material = new Three.MeshMatcapMaterial( {color: 'red',  opacity: 0.95, transparent: true} )
    this.player2Material = new Three.MeshMatcapMaterial( {color: 'blue',  opacity: 0.95, transparent: true} )

    this.player1HightlightMaterial = new Three.MeshMatcapMaterial({color: 'red', opacity: 0.6, transparent: true});
    this.player2HightlightMaterial = new Three.MeshMatcapMaterial({color: 'blue', opacity: 0.6, transparent: true});

    this.defaultLineMaterial = new Three.MeshMatcapMaterial({color: 'green', opacity:0.9, transparent:true});
    this.winningLineMaterial = new Three.MeshMatcapMaterial({color: 'green', opacity:0.9, transparent:true});
    this.playedLineMaterial = new Three.MeshMatcapMaterial({color: 'red', opacity: 0.9});   

    this.playedMaterial = this.playedLineMaterial
    this.tubeRadius = 0.005
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
    this.$refs.container.appendChild(this.renderer.domElement);
    this.renderer.render(this.scene, this.camera);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.animate()
    // Set up socket to receive from server
    this.socket.on('updateGameGrid', (gameGrid) => {
      this.gameGrid = gameGrid
      this.updateGridRender()
      this.connectMoves(false)
    });
    this.socket.on('resizeGame', (width) => {
      if (!this.user) {
        this.resizeGameRender(width)
      }
    });
    this.socket.on('updatePlayerTurn', (playerTurn) => {
        this.playerTurn = playerTurn 
    });
    this.socket.on('updateGamePlayable', (gamePlayable) => {
      this.gamePlayable = gamePlayable
      this.gamePaused = !gamePlayable
    });
    this.socket.on('updateGamePaused', (gamePaused) => {
      this.gamePaused = gamePaused
    });
    this.socket.on('updateGameId', (gameId) => {
      this.gameId = gameId   
    });
    this.socket.on('updatePlayersInGame', (playersInGame) => {
      this.playersInGame = playersInGame   
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
    checkClickUp: function(evt) {
      this.highlightMove(evt)
      this.rotate = false
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
      //this.addWinningLines()
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
          //tube.visible = false
          tube.start = [x1, y1, z1]
          tube.end = [x2, y2, z2]
          this.scene.add(tube)
          }
        }      
    },
    highlightMove: function(evt) {
      if (!this.gamePlayable) {
        return 
      }
      if (!this.gameGrid) {
        return
      }
      if (this.gamePaused) {
        return
      }
      this.updateGridRender()
      const intersects = this.findIntersects(evt)
      if (intersects.length > 0) {
        this.lastMousedVertex = intersects[0]
        this.lastMousedVertex.object.material = this.highlightMaterial
        this.lastMousedVertex.object.geometry = this.highlightGeometry  
      } 
      this.redoGrid()
    },
    redoGrid: function(){
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
          
    },
    makeMove: function(evt) {  
      if (!this.gamePlayable) {
        return 
      }
      const intersects = this.findIntersects(evt)
      if (intersects.length == 0) {
        return
      }
      if (intersects.length > 0) {
          this.clickedVertex = intersects[0]
          const i = this.clickedVertex.object.coords[0]
          const j = this.clickedVertex.object.coords[1]
          const k = this.clickedVertex.object.coords[2]
          if (!this.gamePaused) {
            if (this.gameGrid[i][j][k] == 0) { //Not owned
              this.socket.emit("updatePlayedPoint", this.clickedVertex.object.coords, "Move Selected", this.gameId)
              this.gameGrid[i][j][k] = -1 * this.playerTurn
              this.socket.emit("updateGamePaused", true, this.gameId)
              this.gamePaused = true
            } 
          } else {
              if (this.gameGrid[i][j][k] < 0) { //Already Temp owned
                //this.gameGrid[i][j][k] == 0
                this.gamePaused = false
                this.socket.emit("updateGamePaused", false, this.gameId)
                this.socket.emit("updatePlayedPoint", 'NO MOVE', 'Active', this.gameId)
                this.highlightMove(evt)
              } else if (this.gameGrid[i][j][k] == this.playerTurn) { //Already Owned owned
                this.gameGrid[i][j][k] == 0
                this.socket.emit("updatePlayedPoint", 'NO MOVE', 'Active', this.gameId)
                this.socket.emit("updateGamePaused", false, this.gameId)
                this.gamePaused = false
              } 
            }
      }
      this.lastClickedVertex = this.clickedVertex
      this.playedPoint = this.lastClickedVertex.object.coords
      this.socket.emit("updateGameGrid", this.gameGrid, this.gameId, true) 
      this.connectMoves(false)
      this.updateGridRender()
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
            } else if (gameGridOwner == 1) {
              thisVertex.material = this.player1Material
              thisVertex.geometry = this.playedGeometry
            } else if (gameGridOwner == 2 ) {
              thisVertex.material = this.player2Material
              thisVertex.geometry = this.playedGeometry
            } else if (gameGridOwner == -1 ) {
              thisVertex.material = this.player1HightlightMaterial
              thisVertex.geometry = this.playedGeometry
            }  else if (gameGridOwner == -2 ) {
              thisVertex.material = this.player2HightlightMaterial
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
          const tube = this.allPaths[lineId]
          let color = 'green'
          if (Math.abs(gameGridOwner1) == Math.abs(gameGridOwner2)) { // Either both played or one played and one temp so toggle the color
            if (gameGridOwner1 < 0 || gameGridOwner2 < 0) { // One or both is negative (a temp turn but should only be one in game play)
                tube.visible = true
                if (this.playerTurn == 1) {
                  color ='red'
                } else if (this.playerTurn == 2) {
                  color = 'blue'
                } else {
                  color = 'green'
                }
            } else if (gameGridOwner1 > 0 && gameGridOwner2 > 0) { // Both played
              tube.visible = true
              if (gameGridOwner1 == 1) {
                color ='red'
              } else if (gameGridOwner1 == 2) {
                color = 'blue'
              } else {
                color = 'green'
              }
            } 
          } 
          // Toggle color based on logic
          if (color == 'red') {
                tube.material.color.r = 1
                tube.material.color.g = 0
                tube.material.color.b = 0
              } else if (color == 'blue') {
                tube.material.color.r = 0
                tube.material.color.g = 0
                tube.material.color.b = 1
              } else if (color == 'green') {
                tube.material.color.r = 0
                tube.material.color.g = 0.25
                tube.material.color.b = 0
              }  
        } 
      }
    },
    makeConnectingTube: function(tubeGeometry) {
      const material = new Three.MeshMatcapMaterial({color: 'green', opacity:0.6, transparent:true}); // Must crate a new material instance for each tube
      const tube = new Three.Mesh(tubeGeometry, material)
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