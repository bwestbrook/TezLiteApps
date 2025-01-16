<template>
  <div class="body">
      <mainBody class="centerMiddle"
          :wallet="wallet"
          :walletAddress="walletAddress"
          :socket="socket"
          :tezos="tezos"
          :windowWidth="windowWidth"
          :windowHeight="windowHeight"
      />
  </div>
  
</template>


<script >

import { BeaconEvent } from "@airgap/beacon-sdk";
import { BeaconWallet } from '@taquito/beacon-wallet'
import { NetworkType } from "@airgap/beacon-types";
import io from 'socket.io-client'
//import { state } from "@/socket";
import mainBody from "./components/mainBody.vue"
import { reduceAddress } from "./utilities";
import { RemoteSigner } from '@taquito/remote-signer';
import { NODE_URL} from './constants'
import { TezosToolkit } from '@taquito/taquito'
const Tezos = new TezosToolkit(NODE_URL);


let globalWallet = undefined

export default {
  name: 'App',
  components: {
    mainBody
  },
  data () {
    return {
      windowHeight: window.innerHeight,
      windowWidth: window.innerWidth,
      wallet: this.wallet,
      tezos: this.tezos,
      walletAddress: this.walletAddress,
      socket: this.socket
    }
  },
  created() {   
     
      this.socket = io('localhost:3000')
      //this.socket = io('https://damp-spire-29654-cc0ffbb43258.herokuapp.com/')
      this.tezos = Tezos
      this.getWallet()
  },
  mounted() {
      window.addEventListener('resize', () =>{
        this.onResize()
      })
    },
  methods: {
    async getWallet() {
      if (!globalWallet) {
          // Create a new BeaconWallet instance. The options will be passed to the DAppClient constructor.
          const wallet = new BeaconWallet({ 
              name: 'TezTacToe', network: {
              type: NetworkType.GHOSTNET
            }
          })           
          wallet.client.subscribeToEvent(BeaconEvent.ACTIVE_ACCOUNT_SET, (account) => {
              this.brodcastWallet(account)
              console.log('broadcast', account.address, this.socket)   
              this.socket.emit("walletConnection", account.address)  
              this.socket.emit("updateGames", account)                
          })
          this.wallet = wallet
        } else {
          this.wallet = globalWallet
        }
      return globalWallet
    },
    async brodcastWallet (account) {
      if (account) {
        const reducedAddress = await reduceAddress(account.address)       
        Tezos.setWalletProvider(this.wallet)
        const signer = new RemoteSigner(account.address, NODE_URL )
        await this.tezos.setProvider({signer:signer})
        this.walletAddress = 'UNSYNC WALLET ' + reducedAddress
        
      } else {
        this.walletAddress = 'SYNC WALLET'
      }
    },
    async sendTezos(activeAccount, amount) {
        const signer = new RemoteSigner(activeAccount.address, NODE_URL )
        await this.tezos.setProvider({signer:signer})
        await this.tezos.setWalletProvider(this.wallet)
        await this.tezos.wallet.transfer({amount:amount, to:'tz1Vq5mYKXw1dD9js26An8dXdASuzo3bfE2w'}).send()
    },
    async onResize() {
        this.socket.emit("resizeGame", window.innerWidth)
    } 
  }        
}
</script>

<style>
#app {
  text-align: center;
  color: #000000;
  background-color: #000000;
  margin:0px;
  padding:0px
}
body{
  margin:0px;
  padding:0px
}
.centerMiddle{
  width: 65%;  
  padding:0px
}
</style>
