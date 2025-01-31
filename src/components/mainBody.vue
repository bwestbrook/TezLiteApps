<script>

import aceyDuecey from "./aceyDuecey.vue"
import tezTacToe from "./tezTacToe.vue"
import browseNFTs from "./browseNFTs.vue"
import welcomeIn from './welcomeIn.vue'

export default {
  props: ['wallet', 'socket', 'tezos'],
  components: { 
        aceyDuecey,
        tezTacToe,
        browseNFTs,
        welcomeIn
  },
  data () {
    return {
      showTezTactoe: false,
      showAceyDuecy: false,
      showBrowseNFTs: false,
      showWelcome: true,
      walletAddress: 'SYNC WALLET'
    }
  },
  created () {
    this.socket.on("newWallet", (newWallet) => {
      this.walletAddress = newWallet
    })
    this.socket.on("selectGame", (game) => {
      this.selectGame(game)
    })
  },
  methods: {
    async selectGame(game) {
      if (game == 'AceyDuecey') {
        this.showTezTactoe = false
        this.showAceyDuecy = true
        this.showBrowseNFTs = false
        this.showWelcome = false
      } else if (game == 'TezTacToe') {
        this.showTezTactoe = true
        this.showAceyDuecy = false
        this.showBrowseNFTs = false
        this.showWelcome = false
        this.socket.emit('updatePlayerControl')
      } else if (game == 'browseNFTs') {
        this.showTezTactoe = false
        this.showAceyDuecy = false
        this.showBrowseNFTs = true
        this.showWelcome = false
      } else if (game == 'welcome') {
        this.showTezTactoe = false
        this.showAceyDuecy = false
        this.showBrowseNFTs = false
        this.showWelcome = true
      }
    },
    async toggleWallet(){
        const activeAccount = await this.wallet.client.getActiveAccount()              
        if (activeAccount) {                  
            await this.wallet.clearActiveAccount()           
        } else {
            await this.wallet.client.requestPermissions()
            this.tezos.setWalletProvider(this.wallet)
        }
    },
  }
}
</script>

<template>
  <div class="mainBody">     
    <div class="centerBody">
      <div class="gameManagement">
        <div class="rowFlex" >     
          <div>
            <div class="label"> ALL GAMES GHOSTNET ONLY!!! NFTS LIVE ON MAINNET @ OBJKT.COM</div>
          </div>
          <div class="actionButton" @click="toggleWallet">
              {{walletAddress}} 
          </div>  
        </div>  
        <div @click="selectGame('welcome')" :class="{ 'actionButtonSelected': showWelcome, 'actionButton': !showWelcome }" >
          TXL Home
        </div>     
        <div class="rowFlex" >   
         
          <div @click="selectGame('browseNFTs')" :class="{ 'actionButtonSelected': showBrowseNFTs, 'actionButton': !showBrowseNFTs }" >
              Browse 2.725K
          </div>     
          <div @click="selectGame('TezTacToe')" :class="{ 'actionButtonSelected': showTezTactoe, 'actionButton': !showTezTactoe }">
              Play TezTacToe!
          </div>   
          <div @click="selectGame('AceyDuecey')" :class="{ 'actionButtonSelected': showAceyDuecy, 'actionButton': !showAceyDuecy }">
              Play Acey Duecey!
          </div>
        </div>    
        <welcomeIn v-if="showWelcome"
          :socket="socket"
          :wallet="wallet"
          :tezos="tezos"
        />
        <tezTacToe v-if="showTezTactoe"
          :socket="socket"
          :wallet="wallet"
          :tezos="tezos"
        />
        <aceyDuecey v-if="showAceyDuecy" 
          :socket="socket"
          :wallet="wallet"
          :tezos="tezos"
        />
        <browseNFTs v-if="showBrowseNFTs" 
          :socket="socket"
          :wallet="wallet"
          :tezos="tezos"
        />      
      </div>
    </div>
    <div class="label"> Made with love by @jamin_b on telegram/discord and @jaminb12 on X</div>
  </div>
</template>

<style>
.mainBody{
  margin:5px;
  padding:1px;
  max-width: 610px;
  font-family: 'EB Garamond';
  display: flex;
  flex-direction: column;
  margin: auto;
  border-style: ridge;
  border-radius: 5px;
  border-width: 2px;
  border-color: #fff;
  color: rgb(255, 255, 255);
}
.centerBody{
  display: flex;
  margin:auto;
  flex-direction: column;
}
.gameManagement {
  justify-content: center;
  vertical-align: center;
  width: 100%;
  padding: auto;
  flex: 1;
  cursor: default;
}
.rowFlex {
  display: flex;
  flex-wrap: wrap;
  width: 100%;
}
.gameCenter {
  align-content: center;
  vertical-align: center;
  margin: auto;
  padding: auto;
  margin: auto;
  flex: 1;
}
.gameInfo {
  margin: 2px;
  padding: 2px;
  border-style: ridge;
  border-radius: 3px;
  border-width: 2px;
  border-color: #ffffff;
  flex: 1;
  cursor: default;
  font-family: 'EB Garamond';
}
.gameSelect {
  margin: 2px;
  padding: 2px;
  border-style: ridge;
  border-radius: 3px;
  border-width: 2px;
  border-color: #ffffff;
  flex: 1;
  cursor: pointer;
}
.txlRank {
  align-content: center;
  vertical-align: center;
  padding: 5px;
  margin: 2px;
  width: fit-content;
  height: 90px;
  border-style: ridge;
  border-radius: 2px;
  border-width: 1px;
  border-color: #a7a5a5;
  flex: 1;
  cursor: default;
}
.canvasContainer {
  border-style: ridge;
  border-radius: 2px;
  border-width: 0px;
  border-color: #080606;
}
.imageViewer {
  width: 32.5%;
  border-style: ridge;
  border-radius: 2px;
  border-width: 2px;
  border-color: #5f5f5f;
  cursor: pointer;
}
.imageViewerBox {
  width: 100%;
  cursor: pointer;
}
.infoPopup {
  position: relative;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  background-color: rgba(31, 49, 66, 0.9);
  justify-content: left;
  align-items: left;
  cursor: not-allowed;
}
.listItem {
  position: relative;
  justify-content: left;
  text-align: left;
  list-style-type: none;
  width: 100%;
}
.actionButton {
  align-content: center;
  vertical-align: center;
  padding: 1px;
  margin: 3px;
  border-style: ridge;
  border-radius: 5px;
  border-width: 3px;
  cursor: pointer;
  color: #fff;
  border-color: #ffffff;
  flex: 1;
  font-size: small;
  font-family: 'EB Garamond';
}
.actionButtonSelected {
  align-content: center;
  vertical-align: center;
  padding: 1px;
  margin: 3px;
  border-style: ridge;
  border-radius: 5px;
  border-width: 8px;
  color: #fff;
  border-color: #190857;
  flex: 1;
  font-size: small;
  cursor: pointer;
}
.actionButtonHelp {
  align-content: center;
  vertical-align: center;
  padding: 1px;
  margin: 3px;
  border-style: ridge;
  border-radius: 5px;
  border-width: 3px;
  color: #fff;
  border-color: #ffffff;
  flex: 1;
  font-size: small;
  cursor: help;
}
.selectBox {
  align-content: center;
  vertical-align: center;
  padding: 5px;
  margin: 2px;
  width: fit-content;
  height: auto;
  border-style: inset;
  border-radius: 2px;
  border-width: 0px;
  border-color: #080606;
  background-color: black;
  color:white;
  border-radius: 4px;
  border-width: 2px;
  border-color: #ffffff;
  flex: 1;
  cursor: pointer;
}
</style>
