<script>

import aceyDuecey from "./aceyDuecey.vue"
import tezTacToe from "./tezTacToe.vue"
import browseNFTs from "./browseNFTs.vue"

export default {
  props: ['wallet', 'socket', 'tezos'],
  components: { 
        aceyDuecey,
        tezTacToe,
        browseNFTs
  },
  data () {
    return {
      showTezTactoe: false,
      showAceyDuecy: false,
      showBrowseNFTs: true,
      walletAddress: 'SYNC WALLET'
    }
  },
  created () {
    this.socket.on("newWallet", (newWallet) => {
      this.walletAddress = newWallet
    })
  },
  methods: {
    async selectGame(game) {
      if (game == 'AceyDuecey') {
        this.showTezTactoe = false
        this.showAceyDuecy = true
        this.showBrowseNFTs = false
      } else if (game == 'TezTacToe') {
        this.showTezTactoe = true
        this.showAceyDuecy = false
        this.showBrowseNFTs = false
        this.socket.emit('updatePlayerControl')
      } else if (game == 'browseNFTs') {
        this.showTezTactoe = false
        this.showAceyDuecy = false
        this.showBrowseNFTs = true
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
            <div class="label"> ALL GAMES IN BETA GHOSTNET ONLY!!! NFTS ON MAINNET AT OBJKT.COM</div>
          </div>
          <div class="actionButton" @click="toggleWallet">
              {{walletAddress}} 
          </div>  
        </div>   
        <div class="rowFlex" >     
          <div @click="selectGame('browseNFTs')" :class="{ 'actionButtonSelected': showBrowseNFTs, 'actionButton': !showBrowseNFTs }" >
              Browse 2.725K
          </div>     
          <div @click="selectGame('TezTacToe')" :class="{ 'actionButtonSelected': showTezTactoe, 'actionButton': !showTezTactoe }">
              Play TezTacToe!
          </div>   
          <div @click="selectGame('AceyDuecey')" :class="{ 'actionButtonSelected': showAceyDuecy, 'actionButton': !showAceyDuecy }">
              Coming Soon...
          </div>
        </div>    
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
  display: flex;
  flex-direction: column;
  margin: auto;
  border-width: 2px;
  border-color: #fff;
  color: rgb(255, 255, 255);
}
.centerBody{
  display: flex;
  margin:auto;
  flex-direction: column;
  border-width: 2px;
  border-color: #fff;
  border-style: inset;
}
.gameManagement {
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-content: center;
  vertical-align: center;
  align-items: center;
  width: 100%;
  color: #fff;
  padding: auto;
  border-style: ridge;
  border-width: 0px;
  border-color: #504e4e;
  flex: 1;
}
.rowFlex {
  justify-content: center;
  align-content: center;
  display: flex;
  flex-wrap: wrap;
  width: 100%;
  color: #fff;
  padding: auto;
  border-style: inset;
  border-width: 0px;
  border-color: #ffffff;
  vertical-align: top;
}
.rowFlexBox {
  justify-content: center;
  align-content: center;
  width: 100%;
  color: #fff;
  padding: auto;
  border-style: inset;
  border-width: 0px;
  border-color: #ffffff;
  vertical-align: top;
}
.actionButton {
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
  border-color: #3f3737;
  flex: 1;
  font-size: small;
}
.gameCenter {
  align-content: center;
  vertical-align: center;
  margin: auto;
  padding: auto;
  margin: auto;
  flex: 1;
}
.gameSelect {
  align-content: center;
  vertical-align: center;
  padding: 4px;
  margin: 4x;
  border-style: ridge;
  border-radius: 2px;
  border-width: 2px;
  color: #fff;
  border-color: #ffffff;
  flex: 1;
  font-size: small;
}
.label {
  align-content: center;
  vertical-align: center;
  padding: 4px;
  margin: 4x;
  border-style: ridge;
  border-radius: 2px;
  border-width: 0px;
  color: #fff;
  border-color: #ffffff;
  flex: 1;
  font-size: larger;
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
}
.canvas-container {
  border-style: ridge;
  border-radius: 2px;
  border-width: 0px;
  border-color: #080606;
}
.selectBox {
  align-content: center;
  vertical-align: center;
  padding: 5px;
  margin: 2px;
  width: fit-content;
  height: 30px;
  border-style: inset;
  border-radius: 2px;
  border-width: 0px;
  border-color: #080606;
  background-color: black;
  color:white;
  border-radius: 4px;
  border-width: 2px;
  border-color: #ffffff;

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
}
</style>
