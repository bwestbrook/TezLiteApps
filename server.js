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
let gameRoom = {};
let gameRooms = {}
let connectedUsers = {}
let usersInGame = []
let addressesInGame = []

// Socket.io
const messages = []
io.on('connection', (socket) => {

    //console.log("user " + socket.id + " connected");
    io.emit("socketId", socket.id)
    socket.join(socket.id) // for self stuff like resize events
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

  socket.on("updatePlayedPoint", function(playedPoint, bcStatus) {
    console.log('server sees UPP', playedPoint, bcStatus)
    io.emit("playedPoint", playedPoint, bcStatus)
  });

  socket.on("updateBCStatus", function(bcStatus) {
    io.emit("updateBCStatus", bcStatus)
  });
  
  socket.on("newGameGrid", function(gameGrid, gameId) {
    io.to(gameId).emit("gameGrid", gameGrid, gameId)
  });

  socket.on("playerTurn", function(playerTurn) {
    console.log('playerTurn', playerTurn)
    io.emit("playerTurn", playerTurn)
  });

  socket.on("resizeGame", function(width, socketId) {
    io.to(socket.id).emit("resizeGame", width, socketId)
  });
  socket.on("gamePlayable", function(gamePlayabe) {
    console.log('gamePlayable', gamePlayabe)
    io.emit('gamePlayable', gamePlayabe)
    
  });
  // Contract
  socket.on("updateGames", function(address) {
    console.log('updateGames')
    io.emit('updateGames', address)
    
  });
  socket.on("addUserToGameRoom", function(gameId, address) {
    console.log(connectedUsers)
    console.log('adding user to Game Room', gameId, address, socket.id)
    for (let wallet in connectedUsers) {
      if (connectedUsers[wallet].includes(socket.id)) {
        console.log('wallet/user is connect with socket emitting to', gameId, socket.id)
        socket.join(gameId)
        //io.to(gameId).emit("updateGames", gameId)
        //io.to(socket.id).emit("updatePlayerControl")
      }
    }
   
  });
  socket.on("newContractData", function(address) {
    console.log('newContractData')
    //io.emit('updateGames', address)
  });
  socket.on("walletConnection", function(address) {
    // Determine all the sockets a single user/wallet is connected to
    if (connectedUsers.hasOwnProperty(address)) {
      connectedUsers[address].push(socket.id)
    } else {
      connectedUsers[address] = [socket.id]
    }
  });

  socket.on("disconnect", function() {
    for (let wallet in connectedUsers) {
      if (connectedUsers[wallet].includes(socket.id)) {
        const index = connectedUsers[wallet].indexOf(socket.id);
        connectedUsers[wallet].splice(index, 1)
      }
    }
  });
});
  