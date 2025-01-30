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

    io.emit("socketId", socket.id)
    socket.join(socket.id) // for self stuff like resize events
    //console.log(io.sockets.adapter.rooms)

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
    io.emit("gameGrid", gameGrid, gameId)
  });


  socket.on("updateBCStatus", function(bcStatus, gameId) {
    io.to(gameId).emit("updateBCStatus", bcStatus)
  });

  socket.on("updateGameId", function(gameId) {
    io.to(gameId).emit("updateGameId", gameId)
  });


  
  socket.on("updateGameGrid", function(gameGrid, gameId, updateGrid) {
    if (updateGrid) {
      io.to(gameId).emit("updateGameGrid", gameGrid)
    } else {
      io.to(socket.id).emit("updateGameGrid", gameGrid)
    }
  });

  socket.on("updatePlayerTurn", function(playerTurn, gameId) {
    io.to(gameId).emit("updatePlayerTurn", playerTurn, gameId)
  });

  socket.on("selectGame", function(game) {
    io.to(socket.id).emit("selectGame", game)
  });

  socket.on("setUserActiveGameRoom", function(address, gameCount, gameId) { // Each user can only be in one game at a time
    for (let i = 0; i < gameCount; i++ ) {
      if (i == gameId) {
        socket.join(i)
      } else {
        socket.leave(i)
      }
    }
  });

  socket.on("updateConnectedUsersInGame", function(address, gameId) {
    let socketsInRoom = io.sockets.adapter.rooms.get(gameId) 
    socketsInRoom = Array.from(socketsInRoom)
    let activeUsers = []
    let i = 0
    for (let connectedUser in connectedUsers) {
      for (let socketConnection in connectedUsers[connectedUser]) {
        if (socketsInRoom.includes(connectedUsers[connectedUser][socketConnection])) {
          activeUsers.push(connectedUser)
          i++;
        }
      }
    }
    io.to(gameId).emit("updateConnectedUsers", activeUsers)
    io.to(gameId).emit("updateGameId", gameId)
  });


  socket.on("resizeGame", function(width) {
    io.to(socket.id).emit("resizeGame", width)
  });

  socket.on("updatePlayedPoint", function(playedPoint, bcStatus, gameId) {
    io.to(socket.id).emit("playedPoint", playedPoint, bcStatus)
  });

  socket.on("updateGamePaused", function(gamePaused, gameId) {
    io.to(gameId).emit('updateGamePaused', gamePaused)
  });

  socket.on("updatePlayerControl", function() {
    io.emit('updatePlayerControl')
  });

  socket.on("updatePlayersInGame", function(playersInGame, gameId) {
    io.to(gameId).emit('updatePlayersInGame', playersInGame)
  });

  socket.on("updateGamePlayable", function(gamePlayabe, gameId) {
    io.to(socket.id).emit('updateGamePlayable', gamePlayabe, gameId)
  });

  socket.on("getRandomNumber", function(number) {
    min = Math.ceil(0);
    max = Math.floor(100);
    const randomNumber = Math.floor(Math.random() * (max - min + 1)) + min; //The maximum is inclusive and the minimum is inclusive 
    console.log('new Number req', number)
    io.to(socket.id).emit('newRandomNumber', randomNumber)
  });

  socket.on("updateGames", function() {
    io.to(socket.id).emit('updateGames')
  });

  socket.on("loadGame", function(gameId, updateGrid) {
    io.to(socket.id).emit('loadGame', gameId, updateGrid)
  });

  socket.on("newWallet", function(newWallet) {
    io.to(socket.id).emit('newWallet', newWallet)
  });

  socket.on("walletConnection", function(address) {
    // Determine all the sockets a single user/wallet is connected to
    if (connectedUsers.hasOwnProperty(address)) {
      connectedUsers[address].push(socket.id)
    } else {
      connectedUsers[address] = [socket.id]
    }
    io.to(socket.id).emit('newWallet', address)
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
  