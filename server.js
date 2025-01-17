const port = process.env.PORT || 3000
//const isProd = process.env.NODE_ENV === 'production'
const express = require('express')
const path = require('path')
const cool = require('cool-ascii-faces')


const app = express()
const cors = require("cors");
const http = require('http')
app.use(cors());
app.use(express.static(path.join(__dirname, 'dist')))
//app.set('views', path.join(__dirname, 'views'))
//app.set('view engine', 'ejs')

app.get('/', (req, res) => {
  console.log(`Rendering 'pages/index' for route '/'`)
  res.render('pages/index')
})

app.get('/cool', (req, res) => {
  console.log(`Rendering a cool ascii face for route '/cool'`)
  res.send(cool())
})

const server = http.createServer(app)
const io = require('socket.io')(server, {
  cors: {
    origin: '*',
  }
});




// Listen the server
server.listen(port, '0.0.0.0')
console.log('Server listening on localhost:' + port) // eslint-disable-line no-console

// User
let gameData = {};
let connectedUsers = []
let usersInGame = []
let addressesInGame = []

// Socket.io
const messages = []
io.on('connection', (socket) => {

    console.log("user " + socket.id + " connected");
    io.emit("socketId", socket.id)

    // Game Play
    socket.on("initGameGrid", function(gameId) {
      gameData.gameBalance = 0
      usersInGame = []  
      addressesInGame = []
      gameGrid = {}
      let i = -1;
      for (i; i < 3; i++) {
          let j = -1
          if (!gameGrid[i]) {
            gameGrid[i] = {}
          }
          for (j; j < 3; j++) {
              if (!gameGrid[i][j]) {
                gameGrid[i][j] = {}
              }
              let k = -1
              for (k; k < 3; k++) {  
                  gameGrid[i][j][k] = 0
              }
          }
      }
    console.log('emitting GGG')
    io.emit("gameGrid", gameGrid, gameId)
  });

  socket.on("updatePlayedPoint", function(playedPoint) {
    console.log('server sees UPP', playedPoint)
    io.emit("playedPoint", playedPoint)
  });
  
  socket.on("newGameGrid", function(gameGrid, gameId) {
    io.emit("gameGrid", gameGrid, gameId)
  });

  socket.on("resizeGame", function(width, socketId) {
    console.log('resize request', socketId, socket.id)
    if (socketId == socket.id ) {
      io.emit("resizeGame", width, socketId)
    }
  });
  socket.on("updatePlayerTurn", function(playerTurn, walletPlayerTurn1, walletPlayerTurn2) {
    console.log('updatePlayerTurn')
    io.emit('updatePlayerTurn', playerTurn, walletPlayerTurn1, walletPlayerTurn2)
    
  });
  // Contract
  socket.on("updateGames", function(address) {
    console.log('updateGames')
    io.emit('updateGames', address)
    
  });
  // Wallet
  socket.on("walletConnection", function(address) {
    let userId ={}
    idx = connectedUsers.length
    userId[socket.id] = address
    //userId.socketId = socket.id
    connectedUsers[idx] = userId
    });

  socket.on("connect", function() {
    console.log("user " + socket.id + " connected");
    console.log('seding socketId')
    io.emit("socketId", socket.id)
  });

  socket.on("reconnect", function() {
    console.log("user " + socket.id + " connected");
    console.log('seding socketId')
    io.emit("socketId", socket.id)
  });
  socket.on("disconnect", function() {
    console.log("user333 " + socket.id + " disconnected");
  });
});
  