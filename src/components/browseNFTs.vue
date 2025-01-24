

<script>

import * as Three from 'three'
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls";

export default {
  name: 'browseNFTs',
  props: ["socket", "wallet", "tezos"],
  components: { 
  },
  data () {
    return {
      txlId: 1,
    }
  },
 
  created () {
    this.idLookUp = {
      1: '60199',
      2: '60200',
      3: '60201',
      4: '60202',
      5: '60203',
      6: '60204',
      7: '60206',
      8: '60207',
      9: '60208',
      10: '60209',
      11: '60210',
      12: '60211',
      13: '60212',
      14: '60213',
      15: '60215',
      16: '60216',
      17: '60218',
      18: '60219',
      19: '60220',
      20: '60221',
      21: '60224',
      22: '60225',
      23: '60226',
      24: '60227',
      25: '60228',
      26: '60230',
      27: '60231',
      28: '60233',
      29: '60234',
      30: '60235',
      31: '60236',
      32: '60237',
      33: '60238',
      34: '60239',
      35: '60240',
      36: '60241',
      37: '60242',
      38: '60243',
      39: '60244',
      40: '60245',
      41: '60246',
      42: '60247',
      43: '60248',
      44: '60249',
      45: '60250',
      46: '60251',
      47: '60252',
      48: '60253',
      49: '60254',
      50: '60255',
      51: '60256',
      52: '60257',
      53: '60258',
      54: '60259',
      55: '60260',
      56: '60338',
      57: '60339',
      58: '60340',
      59: '60344',
      60: '60346',
      61: '60348',
      62: '60349',
      63: '60350',
      64: '60354',
      65: '60355',
      66: '60356',
      67: '60357',
      68: '60358',
      69: '60359',
      70: '60361',
      71: '60362',
      72: '60363',
      73: '60366',
      74: '60367',
      75: '60368',
      76: '60369',
      77: '60370',
      78: '60371',
      79: '60372',
      80: '60373',
      81: '60374',
      82: '60375',
      83: '60377',
      84: '60379',
      85: '60380',
      86: '60381',
      87: '60382',
      88: '60383',
      89: '60384',
      90: '60386',
      91: '60387',
      92: '60388',
      93: '60389',
      94: '60391',
      95: '60392',
      96: '60393',
      97: '60394',
      98: '60395',
      99: '60396',
      100: '60397',
      101: '60399',
      102: '60401',
      103: '60403',
      104: '60404',
      105: '60406',
      106: '60407',
      107: '60413',
      108: '60414',
      109: '60416',
      110: '60418',
      111: '60429',
      112: '60432',
      113: '60433',
      114: '60434',
      115: '60436',
      116: '60437',
      117: '60438',
      118: '60439',
      119: '60440',
      120: '60441',
      121: '60442',
      122: '60443',
      123: '60444',
      124: '60445',
      125: '60446',
      126: '60447',
      127: '60448',
      128: '60449',
      129: '60450',
      130: '60451',
      131: '60452',
      132: '60453',
      133: '60454',
      134: '60455',
      135: '60456',
      136: '60457',
      137: '60458',
      138: '60459',
      139: '60460',
      140: '60461',
      141: '60462',
      142: '60463',
      143: '60464',
      144: '60465',
      145: '60466',
      146: '60467',
      147: '60468',
      148: '60469',
      149: '60470',
      150: '60471',
      151: '60472',
      152: '60473',
      153: '60474',
      154: '60475',
      155: '60476',
      156: '60477',
      157: '60478',
      158: '60479',
      159: '60480',
      160: '60481',
      161: '60483',
      162: '60486',
      163: '60487',
      164: '60489',
      165: '60491',
      166: '60492',
      167: '60493',
      168: '60494',
      169: '60495',
      170: '60496',
      171: '60497',
      172: '60498',
      173: '60499',
      174: '60500',
      175: '60501',
      176: '60502',
      177: '60534',
      178: '60535',
      179: '60536',
      180: '60537',
      181: '60545',
      182: '60547',
      183: '60546',
      184: '60548',
      185: '60549',
      186: '60550',
      187: '60551',
      188: '60552',
      189: '60553',
      190: '60554',
      191: '60560',
      192: '60561',
      193: '60562',
      194: '60563',
      195: '60564',
      196: '60565',
      197: '60566',
      198: '60567',
      199: '60571',
      200: '60572',
      201: '60573',
      202: '60575',
      203: '60576',
      204: '60577',
      205: '60578',
      206: '60580',
      207: '60581',
      208: '60582',
      209: '60583',
      210: '60584',
      211: '60585',
      212: '60586',
      213: '60587',
      214: '60589',
      215: '60590',
      216: '60593',
      217: '60595',
      218: '60596',
      219: '60597',
      220: '60599',
      221: '60600',
      222: '60601',
      223: '60603',
      224: '60605',
      225: '60606',
      226: '60607',
      227: '60608',
      228: '60612',
      229: '60613',
      230: '60614',
      231: '60615',
      232: '60616',
      233: '60617',
      234: '60618',
      235: '60619',
      236: '60620',
      237: '60621',
      238: '60622',
      239: '60623',
      240: '60624',
      241: '60625',
      242: '60626',
      243: '60627',
      244: '60628',
      245: '60629',
      246: '60630',
      247: '60631',
      248: '60632',
      249: '60633',
      251: '60636',
      252: '60637',
      253: '60638',
      254: '60639',
      255: '60640',
      256: '60641',
      257: '60642',
      258: '60643',
      259: '60644',
      260: '60645',
      261: '60646',
      262: '60647',
      263: '60648',
      264: '60649',
      265: '60650',
      266: '60651',
      267: '60688',
      268: '60690',
      269: '60692',
      270: '60693',
      271: '60694',
      272: '60696'
    }
    this.gameSize = window.innerWidth * 0.95
    this.objectUrl = 'https://objkt.com/users/tz1Vq5mYKXw1dD9js26An8dXdASuzo3bfE2w'
    this.objectKalaUrl = 'https://objkt.com/tokens/kalamint/'
    if (this.gameSize > 1000) {
      this.gameSize = 1000
    }
    this.board = new Three.Group()
        // General 
    this.scene = new Three.Scene();
    
    //Camera
    this.camera = new Three.PerspectiveCamera(45, 1, 1, 5000);
    this.camera.position.x = 0;
    this.camera.position.y = 0;
    this.camera.position.z = 200;
    this.camera.lookAt(this.scene.position)

    const loader = new Three.TextureLoader(); 
   
    this.nftTexture = loader.load(require('../assets/nftExample2.jpeg')); // Replace with the path to your image
    this.nftMaterial = new Three.MeshBasicMaterial({ map: this.nftTexture });
    this.defaultGeometry = new Three.BoxGeometry(150, 150, 0.1, 1)
    // Materials
    //this.defaultMaterial = new Three.MeshMatcapMaterial({color: 'green', opacity:0.9, transparent:true});
    this.defaultMaterial = new Three.MeshNormalMaterial()
    this.socket.on('resizeGame', (width) => {
      if (!this.user) {
        this.resizeGameRender(width)
      }
    }); 
  },
  mounted () {
    this.renderer = new Three.WebGLRenderer({antialias: true});
    this.renderer.setSize(this.gameSize, this.gameSize)
   
    this.$refs.container.appendChild(this.renderer.domElement);
    this.buildGame()
    this.renderer.render(this.scene, this.camera);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.flipCard()
  },
  methods: {
    animate: function() {
      this.controls.update();
      requestAnimationFrame(this.animate);  
      this.renderer.render(this.scene, this.camera);
    },
    flipCard: function() {
      //this.controls.update();
      requestAnimationFrame(this.flipCard);  
      let time = Date.now() * 0.001;
      this.nftTeaser.rotation.y = time;
      this.renderer.render(this.scene, this.camera);
    },
    buildGame: function() {
      this.nftTeaser = new Three.Mesh(this.defaultGeometry, this.nftMaterial); 
      this.nftTeaser.position.set(0, 0, 0);
      this.board.add(this.nftTeaser) 
      this.scene.add(this.board)                
      },
    browseAllOnObjkt () {
      window.open(this.objectUrl, '_blank');
    },
    checkThisOnObjkt (txlId) {
      const kalaId = this.idLookUp[txlId]
      console.log(this.objectKalaUrl + kalaId)
      window.open(this.objectKalaUrl + kalaId, '_blank');
    },
    resizeGameRender: function(width) {
      this.gameSize = width * 0.95
      if (this.gameSize > this.maxGameSize) {
        this.gameSize = this.maxGameSize
      }
      this.renderer.setSize(this.gameSize, this.gameSize)
    }   
  },
}
</script>

<template>
  <div class="canvas-container" >        
      2.725K Browser Coming Soon!!!!
      <a class="gameManagement">
        <a class="actionButton" @click="checkThisOnObjkt(txlId)"> Buy {{ txlId }} On All Objeckt </a>
        <a class="actionButton" @click="browseAllOnObjkt"> Browse On All Objeckt </a>
          <div 
            @click="flipCard"
            class="mainBody"
            ref="container"
          >
        </div>
      </a>     
  </div>
</template>


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
