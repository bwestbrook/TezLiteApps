<script>

export default {
  name: 'oracleInfo',
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
  }
}
</script>

<template>      
    <div class="gameManagement"> 
      <div class="gameInfo"> Learn more about the Oracle that drives TXL  </div>       
      <div class="gameManagement">       
        <img class="imageViewerBox" src="../assets/oracleLogo.jpg">
      </div>
    </div>
</template>

<style>

</style>
