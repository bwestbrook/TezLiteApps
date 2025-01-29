const { connect } = require('http2');
const { connected } = require('process');
const cors = require('cors')();
const server = require('express')();
const http = require('http').createServer();
const io = require('socket.io')(http ,
        {
            cors: {
                origin: '*'
            }
        }
    )

let contractStorage = {};
let gameData = {};
let connectedUsers = []
let usersInGame = []
let addressesInGame = []

//const contractStorage = '../src/assets/contract-storage.json'

const PORT = process.env.PORT || 3001;
io.listen(PORT)
console.log('io up on ', PORT)
//console.log(process.env)

//setInterval(() => io.emit('setPort', new Date().toTimeString()), 1000);

//io.emit("setPort", PORT)

io.on("connection", function(socket) {

     // User Handling 
    //console.log(socket)
    console.log("user " + socket.id + " connected");
    idx = connectedUsers.length
    connectedUsers[idx] = (socket.id)
    io.emit("connectedUsers", connectedUsers)

    socket.on("disconnect", function() {
        let n = 0;
        for (n; n < connectedUsers.length; n++ ){
          const thisUser = connectedUsers[n]
          if (thisUser == socket.id) {
            connectedUsers.pop(n)
          }
        }
        console.log("user " + socket.id + " disconnected");
        io.emit("connectedUsers", connectedUsers)
    });
    socket.on("initGameGrid", function(gameId) {
      console.log('recieved', socket.id)
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
  socket.on("updateGameGrid", function(gameGrid, coords, owner, gameId) {
    console.log(coords, owner, gameId )
    if (!coords) {
      return;
    }
    if (coords.length == 3) {
        gameGrid[coords[0]][coords[1]][coords[2]] = owner  
    } 
    console.log('updateGG')
    io.emit("updateGameGrid", gameGrid, gameId)
});
socket.on("resizeGame", function(width) {
  io.emit("resizeGame", width)


});
socket.on("test", function(test) {
  console.log(test)
   
});
});
  

