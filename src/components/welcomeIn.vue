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
    <div class ="rowFlex gameManagement">         
      <div class="imageViewer"> 
        <div class="gameInfo"> Welcome to TXL!!! </div>
          TXL is a lite gaming platform on the Tezos Blockchain. The dApps were built with love for Tezos by @jamin_b.
          Each game is revenue generating for TXL holders! Click on each to Learn More!        
      </div>
      <div class="imageViewer" >
        <div class="gameInfo"> Browse TXL earn ꜩ!  </div>
        <img class="imageViewerBox" @click="selectGame('browseNFTs')" src="../assets/nftExample.jpeg">
      </div>
      <div class="imageViewer" >
        <div class="gameInfo"> H2H 3D-4-in-a-row for ꜩ!  </div>
        <img class="imageViewerBox" @click="selectGame('TezTacToe')" src="../assets/tezTacToe.png">
      </div>
      <div class="imageViewer" >
        <div class="gameInfo"> Win big ꜩ in Acey Duecey! </div>
        <img class="imageViewerBox" @click="selectGame('AceyDuecey')" src="../assets/aceyDuecey.png">
      </div>
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
.canvas-container {
  border-style: ridge;
  border-radius: 2px;
  border-width: 0px;
  border-color: #080606;
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
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  justify-content: left;
  align-items: left;
  cursor: not-allowed;
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
