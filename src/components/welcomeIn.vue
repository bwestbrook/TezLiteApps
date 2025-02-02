<script>

export default {
  name: 'welcomeIn',
  props: ['wallet', 'socket', 'tezos'],
  components: {  },
  data () {
    return {
    }
  },
  created () {
    this.socket.on("newWallet", (newWallet) => {
      this.walletAddress = newWallet
    })
  },
  methods: {
    async selectGame(game){
      this.socket.emit("selectGame", game)
    },
  }
}
</script>

<template>      
    <div class="gameManagement"> 
      <div class="gameInfo"> Welcome to TXL!!! </div>       
      <div class="gameManagement">         
        <div class ="rowFlex gameManagement">       
          <div class="imageViewer" >
            <div class="actionButton" @click="selectGame('oracleInfo')"> Oracle </div>
            <img class="imageViewerBox" @click="selectGame('oracleInfo')" src="../assets/oracleLogo.jpg">
          </div>
          <div class="imageViewer" >
            <div class="actionButton" @click="selectGame('browseNFTs')"> Browse TXL earn ꜩ!  </div>
            <img class="imageViewerBox" @click="selectGame('browseNFTs')" src="../assets/nftExample.jpeg">
          </div>      
          <div class="imageViewer" >
            <div class="actionButton" @click="selectGame('aceyDuecey')"> Win big ꜩ in Acey Duecey! </div>
            <img class="imageViewerBox" @click="selectGame('aceyDuecey')" src="../assets/aceyDuecey.png">
          </div>
          <div class="imageViewer" >
            <div class="actionButton" @click="selectGame('tezTacToe')"> H2H 3D-4-in-a-row for ꜩ!  </div>
            <img class="imageViewerBox" @click="selectGame('tezTacToe')" src="../assets/tezTacToe.png">
          </div>
      
        </div> 
      </div>
    </div>
</template>

<style>
</style>
