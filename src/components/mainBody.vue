<script>

import aceyDuecey from "./aceyDuecey.vue"
import tezTacToe from "./tezTacToe.vue"

export default {
  props: ['wallet', 'socket', 'tezos'],
  components: { 
        aceyDuecey,
        tezTacToe
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
      } else if (game == 'TezTacToe') {
        this.showTezTactoe = true
        this.showAceyDuecy = false
        this.socket.emit('updatePlayerControl')
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
        <div @click="selectGame('TezTacToe')" class="actionButton">
            Play TezTacToe!
        </div>
        <div @click="selectGame('AceyDuecey')" class="actionButton">
            CLICK ME FOR SURPRISE
        </div>
        <div class="actionButton" @click="claimNFTEarningsBC"> 
            Claim NFT Earnings 
        </div>
        <div class="actionButton" @click="toggleWallet">
            {{walletAddress}} 
        </div>
     </div>  
    </div>  
      <tezTacToe v-if="showTezTactoe"
          :socket="socket"
          :wallet="wallet"
          :tezos="tezos"
      />
      <aceyDuecey v-if="showAceyDuecy" 
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
.rules {
  align-content: stretch;
  text-align: justify;
  justify-content: center;
  flex-direction: column;
  color: white;
  margin:auto;
  border-style: inset;
  border-width: 1px;
  border-color: #fff;
}
.rowFlex {
  display: flex;
  justify-content: center;
  align-items: center;
  color: #fff;
  padding: 5px;
  border-style: inset;
  border-width: 0px;
  border-color: #ffffff;
}
.gameHubRowFlex {
  display: flex;
  justify-content: center;
  align-items: center;
  color: #fff;
  padding: 5px;
  border-style: inset;
  border-width: 1px;
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
.gameManagement {
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
  color: #fff;
  padding: auto;
  border-style: inset;
  border-width: 1px;
  border-color: #ffffff;
}
.actionButton {
  display: flex;
  align-content: center;
  justify-content: center;
  padding: 5px;
  margin: 2px;
  border-style: ridge;
  border-radius: 2px;
  border-width: 1px;
  color: #fff;
  border-color: #a7a5a5;
}
.canvas-container {
  width: 50%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  border-style: inset;
  border-radius: 2px;
  border-width: 1px;
  border-color: #fff;
}
</style>
