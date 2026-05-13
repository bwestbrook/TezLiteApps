<script>
export default {
  name: 'oracleInfo',
  props: ['wallet', 'socket', 'tezos'],
  data() {
    return {
      walletAddress: '',
    }
  },
  created() {
    this.socket.on('newWallet', (newWallet) => {
      this.walletAddress = newWallet
    })
  },
}
</script>

<template>
  <div class="gameManagement">
    <div class="gameInfo">Learn more about the Oracle that drives TXL</div>
    <div class="gameManagement">
      <img class="imageViewerBox" src="../assets/oracleLogo.jpg" alt="Oracle logo" />
    </div>
  </div>
</template>

<style></style>
