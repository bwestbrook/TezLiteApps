<script>

import aceyDuecey from "./aceyDuecey.vue"
import gameGrid from "./gameGrid.vue"
import playerControl from "./playerControl.vue"

export default {
  name: 'HelloWorld',
  props: ['wallet', 'walletAddress', 'socket', 'tezos', 'windowWidth', 'windowHeight'],
  components: { 
        aceyDuecey,
        gameGrid,
        playerControl
  },
  data () {
    return {
      showTezTactoe: true,
      showAceyDuecy: false
    }
  },
  methods: {
    async selectGame(game) {
      console.log('toggleGame')
      if (game == 'AceyDuecey') {
        this.showTezTactoe = false
        this.showAceyDuecy = true
      } else if (game == 'TezTacToe') {
        this.showTezTactoe = true
        this.showAceyDuecy = false
        this.socket.emit('updatePlayerControl')
        console.log('update UPC')
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
  },
  created () {
  
  }
}
</script>

<template>
  <div class="mainBody">     
    <div class="centerBody">
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
      <playerControl v-if="showTezTactoe"
          :socket="socket"
          :wallet="wallet"
          :tezos="tezos"
          :walletAddress="walletAddress"
      />
      <aceyDuecey v-if="showAceyDuecy" />
      <gameGrid v-if="showTezTactoe"     
          :windowHeight="windowHeight"
          :windowWidth="windowWidth"
          :wallet="wallet"
          :socket="socket"
      />
      <div class="rules">
        Load a Game!  When you click on a move, click again to search for anther move, when you are ready with you move submit it to the blockchain!
      </div>
      
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
  color: rgb(255, 255, 255);
}
.centerBody{
  display: flex;
  margin:auto;
  flex-direction: column;
  border-width: 2px;
  border-color: #fff;

}
.rules {
  align-content: stretch;
  text-align: justify;
  justify-content: center;
  flex-direction: column;
  color: white;
  margin:auto;
  border-style: inset;
  border-width: 5px;
  border-color: #fff;
}
.rowFlex {
  display: flex;
  justify-content: center;
  grid-template-columns: 1fr 1fr;
  align-items: center;
  color: #fff;
  padding: 5px;
  border-style: inset;
  border-width: 5px;
  border-color: #ffffff;
}
.gridFlex2xN {
  display: grid;
  justify-content: center;
  grid-template-columns: 1fr 1fr;
  align-items: center;
  color: #fff;
  padding: 5px;

}
.gameManagement {
  width: 25%;
  justify-content: center;
  grid-template-columns: 1fr 1fr;
  align-items: center;
  color: #fff;
  padding: 5px;
  border-style: inset;
  border-width: 5px;
  border-color: #ffffff;
}
.actionButton {
  display: flex;
  align-content: center;
  justify-content: center;
  padding: 5px;
  margin: auto;
  border-style: ridge;
  border-radius: 2px;
  border-width: 3px;
  color: #fff;
  border-color: #9f2929;
}
.canvas-container {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  border-style: inset;
  border-radius: 2px;
  border-width: 5px;
  border-color: #fff;
}
</style>
