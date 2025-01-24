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
      showTezTactoe: true,
      showAceyDuecy: false,
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
          <div class="actionButton" @click="claimNFTEarningsBC"> 
            Claim 2.725K Earnings 
          </div>    
          <div class="actionButton" @click="toggleWallet">
              {{walletAddress}} 
          </div>  
           
        </div>   
        <div class="rowFlex" >          
          <div @click="selectGame('TezTacToe')" class="actionButton">
              Play TezTacToe!
          </div>   
          <div @click="selectGame('AceyDuecey')" class="actionButton">
              Play ???!
          </div>
          <div @click="selectGame('browseNFTs')" class="actionButton">
              Browse 2.725K
          </div>
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
</template>

<style>
.mainBody{
  margin:0px;
  padding:2px;
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
  width: 100%;
  flex-direction: column;
  justify-content: center;
  align-content: center;
  vertical-align: center;
  align-items: center;
  color: #fff;
  padding: auto;
  border-style: inset;
  border-width: 0px;
  border-color: #231b1b;
}
.label {
  justify-content: center;
  align-content: center;
  vertical-align: center;
}
.rowFlex {
  display: flex;
  color: #fff;
  padding: 5px;
  border-style: inset;
  border-width: 0px;
  border-color: #ffffff;
}
.gridFlex4x2 {
  display: grid;
  flex-direction: column;
  grid-template-columns: 1fr 1fr;
  justify-content: center;
  align-items: center;
  color: #fff;
  padding: 5px;

}
.actionButton {
  display: flex;
  align-content: center;
  padding: 5px;
  margin: 2px;
  border-style: ridge;
  border-radius: 2px;
  border-width: 1px;
  color: #fff;
  border-color: #a7a5a5;
}
.canvas-container {
  border-style: ridge;
  border-radius: 2px;
  border-width: 2px;
  border-color: #231b1b;
}
</style>
