<template>
  <div class="mainBody">     
    <div class="centerBody">
      <playerControl 
          :socket="socket"
          :wallet="wallet"
          :tezos="tezos"
          :walletAddress="walletAddress"
      />
      <gameGrid       
          :windowHeight="windowHeight"
          :windowWidth="windowWidth"
          :socket="socket"
      />
      <div class="rules">
      </div>
      <div>aaaaaaaaa</div>
    </div>
  </div>
</template>

<script>

import gameGrid from "./gameGrid.vue"
import playerControl from "./playerControl.vue"

export default {
  name: 'HelloWorld',
  props: ['wallet', 'walletAddress', 'socket', 'tezos', 'windowWidth', 'windowHeight'],
  components: { 
        gameGrid,
        playerControl
  },
  data () {
    return {
    }
  },
  methods: {

  },
  created () {
  
  }
}
</script>

<!-- Add "scoped" attribute to limit CSS to this component only -->
<style scoped>
.mainBody{
  margin:0px;
  padding:0px;
  display: flex;
  flex-direction: column;
  margin: auto;
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
</style>
