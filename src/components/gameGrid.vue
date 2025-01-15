<script>
import * as Three from 'three'
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls";


let gameWinners = [
 [[-1, -1, -1], [0, 0, 0], [1, 1, 1], [2, 2, 2]],
 [[-1, -1, 2], [0, 0, 1], [1, 1, 0], [2, 2, -1]],
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
      moveMade: false,
      playerColor: 'red',
      playerTurn: 2, 
      gamePaused: false,
      halfTurn: false,
      player1Plays: {},
      player2Plays: {},
      tempHighlights: []
      
    }
  },
  props: ['socket', 'activeGameId', 'windowWidth', 'windowHeight'],

  created () {
    this.intvl = 0.5
    this.gameSize = this.windowWidth * 0.6
    this.board = new Three.Group()
    // Materials
    this.defaultGeometry = new Three.SphereGeometry(0.06, 32, 16)
    //this.playedGeometry = new Three.BoxGeometry(0.1, 0.1, 0.1)
    this.defaultMaterial = new Three.MeshNormalMaterial()
    this.highlightGeometry = this.defaultGeometry
    this.playedGeometry = this.defaultGeometry
    this.highlightMaterial = new Three.MeshMatcapMaterial( {color:'black', opacity: 0.75, transparent: true} )
    this.player1Material = new Three.MeshMatcapMaterial( {color: 'red',  opacity: 0.95, transparent: true} )
    this.player2Material = new Three.MeshMatcapMaterial( {color: 'blue',  opacity: 0.95, transparent: true} )
    //this.lineMaterial = new Three.LineBasicMaterial( { color: 0x0000ff } );
    this.defaultLineMaterial = new Three.MeshMatcapMaterial({color: 'green', opacity:0.3, transparent:true});
    this.hightlightMaterial = new Three.MeshMatcapMaterial({color: 'red', opacity: 0.5, transparent: true});
    this.playedLineMaterial = new Three.MeshMatcapMaterial({color: 'red', opacity: 0.8, transparent: true});   
    this.playedMaterial = this.playedLineMaterial
    this.tubeRadius = 0.012
      //this.player2Material = new Three.MeshMatcapMaterial( {color: 'blue',  opacity: 0.5} )
    // General 
    this.scene = new Three.Scene();
    this.renderer = new Three.WebGLRenderer({antialias: true});
    this.renderer.setSize(this.gameSize, this.gameSize)
    
    //Camera
    this.camera = new Three.PerspectiveCamera(45, 1, 1, 5000);
    this.camera.position.x = 3;
    this.camera.position.y = 1;
    this.camera.position.z = 3;
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
      this.connectMoves()
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
      this.scene.add(this.board)
    },
    addWinningLines: function() {    
      for (let i in gameWinners) {
          const start =  new Three.Vector3(
                  gameWinners[i][0][0] * this.intvl - 0.5 * this.intvl,
                  gameWinners[i][0][1] * this.intvl - 0.5 * this.intvl,
                  gameWinners[i][0][2] * this.intvl - 0.5 * this.intvl
              )
                const end = new Three.Vector3(
                  gameWinners[i][3][0] * this.intvl - 0.5 * this.intvl,
                  gameWinners[i][3][1] * this.intvl - 0.5 * this.intvl,
                  gameWinners[i][3][2]* this.intvl - 0.5 * this.intvl
              )
          const path = new Three.LineCurve3(start, end);
          const tubeGeometry = new Three.TubeGeometry(path, 20, this.tubeRadius, 10, false);
          const line = new Three.Mesh(tubeGeometry, this.defaultLineMaterial)
          this.scene.add(line)
        }
    },
    highlightMove: function(evt) {
      if (this.gamePaused) {
        return
      }
      const intersects = this.findIntersects(evt)
      this.updateGridRender()
      if (intersects.length > 0) {
        const mousedVertex = intersects[0]
        if (mousedVertex.object.owner == 0) {
          mousedVertex.object.material = this.highlightMaterial
          mousedVertex.object.geometry = this.highlightGeometry
        }
      } 
    },
    makeMove: function(evt) {  
      const intersects = this.findIntersects(evt)
      if (intersects.length > 0) {
          let clickedVertex = intersects[0]
          if (clickedVertex.object.owner == 0 || clickedVertex.object.owner < 0) {
              const i = clickedVertex.object.coords[0]
              const j = clickedVertex.object.coords[1]
              const k = clickedVertex.object.coords[2]
              if (this.gameGrid[i][j][k] < 0) {
                  if (this.gamePaused) {
                    this.gameGrid[i][j][k] = 0
                  }
                  this.gamePaused = false
                  clickedVertex.object.opacity = 0.95
              } else if (this.gameGrid[i][j][k] == 0 && !this.gamePaused) {
                this.gameGrid[i][j][k] = -1 * this.playerTurn
                this.gamePaused = true
                clickedVertex.object.opacity = 0.3
              } else {
                this.gamePaused = true
              }
            }
      }
      this.updateGridRender()
      this.connectMoves()
      this.socket.emit("updateGameGrid",this.gameGrid)
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
            } else if (gameGridOwner == -1) {
              thisVertex.material = this.hightlightMaterial
              thisVertex.geometry = this.playedGeometry
            } else if (gameGridOwner == -2 ) {
              console.log('ad')
              thisVertex.material = this.hightlightMaterial
              thisVertex.geometry = this.playedGeometry
            }
          }
      }    
    },
    connectMoves: function() {
      let prevGridOwner = 0
      let gameGridOwner = 0
      let prevGridPoint = [0,0,0]
      let istemp = false
      for (let i in gameWinners) {
        for (let j in gameWinners[i]) {
          const x = gameWinners[i][j][0]
          const y = gameWinners[i][j][1]
          const z = gameWinners[i][j][2]
          gameGridOwner = this.gameGrid[x][y][z]
          if (gameGridOwner < 0) {
            gameGridOwner = -1 * gameGridOwner
            istemp = true
          } else {
            istemp = false
          }
          if (prevGridOwner == gameGridOwner && gameGridOwner > 0) {
                const start =  new Three.Vector3(
                  prevGridPoint[0] * this.intvl - 0.5 * this.intvl,
                  prevGridPoint[1] * this.intvl - 0.5 * this.intvl,
                  prevGridPoint[2] * this.intvl - 0.5 * this.intvl
              )
                const end = new Three.Vector3(
                  x * this.intvl - 0.5 * this.intvl,
                  y * this.intvl - 0.5 * this.intvl,
                  z * this.intvl - 0.5 * this.intvl
              )
              const path = new Three.LineCurve3(start, end);
              this.highlightTubeGeometry = new Three.TubeGeometry(path, 20, this.tubeRadius * 1.2, 10, false);
              let material = {}
              if (istemp) {
                material = this.hightlightMaterial
                if (gameGridOwner == 1 ) {
                  material.color.r = 1
                  material.color.b = 0
                } else {
                  material.color.r = 0
                  material.color.b = 1
                }
              } else {
                material = this.playedLineMaterial
                if (gameGridOwner == 1 ) {
                  material.color.r = 1
                  material.color.b = 0
                } else {
                  material.color.r = 0
                  material.color.b = 1
                }
                0.2158605001032441
              }
              console.log(material)
              
              
              const tempHighlight = new Three.Mesh(this.highlightTubeGeometry, material);
              if (istemp) {
                this.tempHighlights.push(tempHighlight)
              }
              
              this.scene.add(tempHighlight)
          }
          prevGridOwner =  this.gameGrid[x][y][z]
          prevGridPoint = [x, y, z]
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