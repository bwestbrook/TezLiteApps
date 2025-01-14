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
    io.emit("gameGrid", gameGrid)
});
socket.on("resizeGame", function(width) {
  io.emit("resizeGame", width)


});
socket.on("test", function(test) {
  console.log(test)
   
});
});
  