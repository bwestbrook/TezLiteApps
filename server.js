// Express + Socket.IO server for TezLiteApps. Serves the built `dist/` folder
// and brokers game state between connected clients. No game logic lives here —
// the source of truth is the Tezos smart contracts. The server only relays
// messages and tracks which sockets are in which game room.

const path = require('path')
const http = require('http')
const express = require('express')
const cors = require('cors')
const { Server } = require('socket.io')

const PORT = process.env.PORT || 3000

const app = express()
app.use(cors())

// Heroku terminates TLS at the router and forwards the original scheme in
// X-Forwarded-Proto. Force https in production so http://thextz.life
// transparently upgrades. Only runs on Heroku (DYNO env is set there).
app.set('trust proxy', true)
if (process.env.NODE_ENV === 'production' || process.env.DYNO) {
  app.use((req, res, next) => {
    if (req.header('x-forwarded-proto') !== 'https') {
      return res.redirect(301, `https://${req.header('host')}${req.url}`)
    }
    next()
  })
}

app.use(express.static(path.join(__dirname, 'dist')))

const server = http.createServer(app)
const io = new Server(server, {
  cors: { origin: '*' },
})

// ─── Server state ────────────────────────────────────────────────────────────
// Map of wallet address -> array of socket ids it's connected from.
// One wallet can have multiple tabs open, and one socket disconnect should not
// drop the wallet from the others.
const connectedUsers = {}

// Build an empty 4x4x4 cube initialized to 0 — the game grid for Connect4D.
function buildEmptyGameGrid() {
  const grid = {}
  for (let i = -1; i < 3; i++) {
    grid[i] = {}
    for (let j = -1; j < 3; j++) {
      grid[i][j] = {}
      for (let k = -1; k < 3; k++) {
        grid[i][j][k] = 0
      }
    }
  }
  return grid
}

server.listen(PORT, '0.0.0.0', () => {
  console.log(`Server listening on 0.0.0.0:${PORT}`) // eslint-disable-line no-console
})

// ─── Socket.IO ───────────────────────────────────────────────────────────────
io.on('connection', (socket) => {
  io.emit('socketId', socket.id)
  socket.join(socket.id) // self-room — used for unicast events like resize

  // Game lifecycle
  socket.on('initGameGrid', (gameId) => {
    io.emit('gameGrid', buildEmptyGameGrid(), gameId)
  })

  socket.on('updateBCStatus', (bcStatus, gameId) => {
    io.to(gameId).emit('updateBCStatus', bcStatus)
  })

  socket.on('updateGameId', (gameId) => {
    io.to(gameId).emit('updateGameId', gameId)
  })

  socket.on('updateGameGrid', (gameGrid, gameId, broadcastToRoom) => {
    if (broadcastToRoom) {
      io.to(gameId).emit('updateGameGrid', gameGrid)
    } else {
      io.to(socket.id).emit('updateGameGrid', gameGrid)
    }
  })

  socket.on('updatePlayerTurn', (playerTurn, gameId) => {
    io.to(gameId).emit('updatePlayerTurn', playerTurn, gameId)
  })

  socket.on('selectGame', (game) => {
    io.to(socket.id).emit('selectGame', game)
  })

  // Each user can only be in one game room at a time. Join the active one,
  // leave all others.
  socket.on('setUserActiveGameRoom', (_address, gameCount, gameId) => {
    for (let i = 0; i < gameCount; i++) {
      if (i === gameId) {
        socket.join(i)
      } else {
        socket.leave(i)
      }
    }
  })

  socket.on('updateConnectedUsersInGame', (_address, gameId) => {
    const socketsSet = io.sockets.adapter.rooms.get(gameId)
    if (!socketsSet) return
    const socketsInRoom = Array.from(socketsSet)

    const activeUsers = []
    for (const wallet of Object.keys(connectedUsers)) {
      const socketIds = connectedUsers[wallet]
      if (socketIds.some((id) => socketsInRoom.includes(id))) {
        activeUsers.push(wallet)
      }
    }

    io.to(gameId).emit('updateConnectedUsers', activeUsers)
    io.to(gameId).emit('updateGameId', gameId)
  })

  socket.on('resizeGame', (width) => {
    io.to(socket.id).emit('resizeGame', width)
  })

  socket.on('updatePlayedPoint', (playedPoint, bcStatus) => {
    io.to(socket.id).emit('playedPoint', playedPoint, bcStatus)
  })

  socket.on('updateGamePaused', (gamePaused, gameId) => {
    io.to(gameId).emit('updateGamePaused', gamePaused)
  })

  socket.on('updatePlayerControl', () => {
    io.emit('updatePlayerControl')
  })

  socket.on('updatePlayersInGame', (playersInGame, gameId) => {
    io.to(gameId).emit('updatePlayersInGame', playersInGame)
  })

  socket.on('updateGamePlayable', (gamePlayable, gameId) => {
    io.to(socket.id).emit('updateGamePlayable', gamePlayable, gameId)
  })

  // Random number 0-100 inclusive — used as a fallback before the on-chain
  // oracle responds.
  socket.on('getRandomNumber', () => {
    const randomNumber = Math.floor(Math.random() * 101)
    io.to(socket.id).emit('newRandomNumber', randomNumber)
  })

  socket.on('updateGames', () => {
    io.to(socket.id).emit('updateGames')
  })

  socket.on('loadGame', (gameId, updateGrid) => {
    io.to(socket.id).emit('loadGame', gameId, updateGrid)
  })

  socket.on('newWallet', (newWallet) => {
    io.to(socket.id).emit('newWallet', newWallet)
  })

  socket.on('walletConnection', (address) => {
    if (!connectedUsers[address]) {
      connectedUsers[address] = []
    }
    connectedUsers[address].push(socket.id)
    io.to(socket.id).emit('newWallet', address)
  })

  socket.on('disconnect', () => {
    for (const wallet of Object.keys(connectedUsers)) {
      const idx = connectedUsers[wallet].indexOf(socket.id)
      if (idx !== -1) {
        connectedUsers[wallet].splice(idx, 1)
      }
      if (connectedUsers[wallet].length === 0) {
        delete connectedUsers[wallet]
      }
    }
  })
})
