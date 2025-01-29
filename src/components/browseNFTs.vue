

<script>
import { RemoteSigner } from '@taquito/remote-signer';
import { getRandomIntInclusive, reduceAddress } from '@/utilities';
import * as Three from 'three'
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls";
import { GAME_WIDTH_FRACTION, MAX_GAME_SIZE, NFT_INFO, TXL_CONTRACT_ADDRESS, NODE_URL } from '../constants'

export default {
  name: 'browseNFTs',
  props: ["socket", "wallet", "tezos"],
  components: { 
  },
  data () {
    return {
      nftInfo: NFT_INFO,
      showInfo: false, 
      txlId: 68,
      rank: 0,
      txlRanking: 1,
      txlData: {},
      owner: '',
      tezosSymbol: 'ꜩ',
      intervalId: null,
      countDownSeconds: 5,
      pauseRandom: true,
      pauseState: 'Play',
      currentRotation: 0,
      pauseAnimation: false,
      pauseAnimationState: 'Pause'
    }
  },
 
  created () {
    // API and Static
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
    this.txlRankings= {
      "1": "139",
      "10": "211",
      "100": "118",
      "101": "256",
      "102": "57",
      "103": "244",
      "104": "254",
      "105": "16",
      "106": "62",
      "107": "129",
      "108": "124",
      "109": "71",
      "11": "45",
      "110": "105",
      "111": "210",
      "112": "23",
      "113": "203",
      "114": "70",
      "115": "109",
      "116": "44",
      "117": "242",
      "118": "252",
      "119": "222",
      "12": "14",
      "120": "102",
      "121": "243",
      "122": "266",
      "123": "55",
      "124": "130",
      "125": "114",
      "126": "13",
      "127": "219",
      "128": "174",
      "129": "228",
      "13": "68",
      "130": "88",
      "131": "265",
      "132": "142",
      "133": "165",
      "134": "111",
      "135": "26",
      "136": "64",
      "137": "163",
      "138": "182",
      "139": "136",
      "14": "195",
      "140": "220",
      "141": "50",
      "142": "36",
      "143": "9",
      "144": "1",
      "145": "53",
      "146": "95",
      "147": "106",
      "148": "158",
      "149": "206",
      "15": "125",
      "150": "177",
      "151": "66",
      "152": "82",
      "153": "69",
      "154": "104",
      "155": "188",
      "156": "52",
      "157": "48",
      "158": "160",
      "159": "108",
      "16": "27",
      "160": "236",
      "161": "24",
      "162": "190",
      "163": "267",
      "164": "198",
      "165": "87",
      "166": "178",
      "167": "38",
      "168": "37",
      "169": "260",
      "17": "224",
      "170": "217",
      "171": "63",
      "172": "185",
      "173": "39",
      "174": "74",
      "175": "115",
      "176": "131",
      "177": "81",
      "178": "240",
      "179": "90",
      "18": "33",
      "180": "91",
      "181": "153",
      "182": "147",
      "183": "169",
      "184": "253",
      "185": "47",
      "186": "76",
      "187": "231",
      "188": "43",
      "189": "259",
      "19": "189",
      "190": "92",
      "191": "83",
      "192": "42",
      "193": "138",
      "194": "214",
      "195": "152",
      "196": "179",
      "197": "186",
      "198": "235",
      "199": "237",
      "2": "40",
      "20": "107",
      "200": "167",
      "201": "119",
      "202": "29",
      "203": "10",
      "204": "41",
      "205": "146",
      "206": "123",
      "207": "212",
      "208": "94",
      "209": "234",
      "21": "207",
      "210": "162",
      "211": "101",
      "212": "150",
      "213": "204",
      "214": "216",
      "215": "261",
      "216": "144",
      "217": "205",
      "218": "132",
      "219": "200",
      "22": "59",
      "220": "172",
      "221": "148",
      "222": "181",
      "223": "85",
      "224": "232",
      "225": "180",
      "226": "258",
      "227": "134",
      "228": "264",
      "229": "86",
      "23": "120",
      "230": "20",
      "231": "72",
      "232": "116",
      "233": "225",
      "234": "248",
      "235": "100",
      "236": "28",
      "237": "80",
      "238": "32",
      "239": "249",
      "24": "112",
      "240": "110",
      "241": "60",
      "242": "193",
      "243": "226",
      "244": "245",
      "245": "271",
      "246": "121",
      "247": "187",
      "248": "17",
      "249": "122",
      "25": "54",
      "250": "218",
      "251": "89",
      "252": "213",
      "253": "97",
      "254": "61",
      "255": "215",
      "256": "170",
      "257": "7",
      "258": "155",
      "259": "246",
      "26": "173",
      "260": "201",
      "261": "77",
      "262": "161",
      "263": "113",
      "264": "140",
      "265": "25",
      "266": "98",
      "267": "128",
      "268": "126",
      "269": "65",
      "27": "11",
      "270": "22",
      "271": "75",
      "272": "241",
      "28": "154",
      "29": "227",
      "3": "247",
      "30": "229",
      "31": "197",
      "32": "239",
      "33": "5",
      "34": "51",
      "35": "250",
      "36": "4",
      "37": "67",
      "38": "251",
      "39": "46",
      "4": "175",
      "40": "3",
      "41": "6",
      "42": "103",
      "43": "263",
      "44": "262",
      "45": "117",
      "46": "176",
      "47": "133",
      "48": "194",
      "49": "268",
      "5": "184",
      "50": "12",
      "51": "141",
      "52": "137",
      "53": "171",
      "54": "192",
      "55": "164",
      "56": "233",
      "57": "159",
      "58": "2",
      "59": "151",
      "6": "156",
      "60": "31",
      "61": "15",
      "62": "223",
      "63": "8",
      "64": "49",
      "65": "238",
      "66": "221",
      "67": "157",
      "68": "0",
      "69": "127",
      "7": "84",
      "70": "78",
      "71": "255",
      "72": "30",
      "73": "93",
      "74": "145",
      "75": "34",
      "76": "18",
      "77": "143",
      "78": "183",
      "79": "35",
      "8": "58",
      "80": "135",
      "81": "208",
      "82": "199",
      "83": "270",
      "84": "166",
      "85": "56",
      "86": "257",
      "87": "202",
      "88": "19",
      "89": "269",
      "9": "196",
      "90": "99",
      "91": "168",
      "92": "73",
      "93": "191",
      "94": "79",
      "95": "149",
      "96": "96",
      "97": "21",
      "98": "209",
      "99": "230"
    }
    this.txlRevRankings  = {
      1: 68,
      2: 144,
      3: 58,
      4: 40,
      5: 36,
      6: 33,
      7: 41,
      8: 257,
      9: 63,
      10: 143,
      11: 203,
      12: 27,
      13: 50,
      14: 126,
      15: 12,
      16: 61,
      17: 105,
      18: 248,
      19: 76,
      20: 88,
      21: 230,
      22: 97,
      23: 270,
      24: 112,
      25: 161,
      26: 265,
      27: 135,
      28: 16,
      29: 236,
      30: 202,
      31: 72,
      32: 60,
      33: 238,
      34: 18,
      35: 75,
      36: 79,
      37: 142,
      38: 168,
      39: 167,
      40: 173,
      41: 2,
      42: 204,
      43: 192,
      44: 188,
      45: 116,
      46: 11,
      47: 39,
      48: 185,
      49: 157,
      50: 64,
      51: 141,
      52: 34,
      53: 156,
      54: 145,
      55: 25,
      56: 123,
      57: 85,
      58: 102,
      59: 8,
      60: 22,
      61: 241,
      62: 254,
      63: 106,
      64: 171,
      65: 136,
      66: 269,
      67: 151,
      68: 37,
      69: 13,
      70: 153,
      71: 114,
      72: 109,
      73: 231,
      74: 92,
      75: 174,
      76: 271,
      77: 186,
      78: 261,
      79: 70,
      80: 94,
      81: 237,
      82: 177,
      83: 152,
      84: 191,
      85: 7,
      86: 223,
      87: 229,
      88: 165,
      89: 130,
      90: 251,
      91: 179,
      92: 180,
      93: 190,
      94: 73,
      95: 208,
      96: 146,
      97: 96,
      98: 253,
      99: 266,
      100: 90,
      101: 235,
      102: 211,
      103: 120,
      104: 42,
      105: 154,
      106: 110,
      107: 147,
      108: 20,
      109: 159,
      110: 115,
      111: 240,
      112: 134,
      113: 24,
      114: 263,
      115: 125,
      116: 175,
      117: 232,
      118: 45,
      119: 100,
      120: 201,
      121: 23,
      122: 246,
      123: 249,
      124: 206,
      125: 108,
      126: 15,
      127: 268,
      128: 69,
      129: 267,
      130: 107,
      131: 124,
      132: 176,
      133: 218,
      134: 47,
      135: 227,
      136: 80,
      137: 139,
      138: 52,
      139: 193,
      140: 1,
      141: 264,
      142: 51,
      143: 132,
      144: 77,
      145: 216,
      146: 74,
      147: 205,
      148: 182,
      149: 221,
      150: 95,
      151: 212,
      152: 59,
      153: 195,
      154: 181,
      155: 28,
      156: 258,
      157: 6,
      158: 67,
      159: 148,
      160: 57,
      161: 158,
      162: 262,
      163: 210,
      164: 137,
      165: 55,
      166: 133,
      167: 84,
      168: 200,
      169: 91,
      170: 183,
      171: 256,
      172: 53,
      173: 220,
      174: 26,
      175: 128,
      176: 4,
      177: 46,
      178: 150,
      179: 166,
      180: 196,
      181: 225,
      182: 222,
      183: 138,
      184: 78,
      185: 5,
      186: 172,
      187: 197,
      188: 247,
      189: 155,
      190: 19,
      191: 162,
      192: 93,
      193: 54,
      194: 242,
      195: 48,
      196: 14,
      197: 9,
      198: 31,
      199: 164,
      200: 82,
      201: 219,
      202: 260,
      203: 87,
      204: 113,
      205: 213,
      206: 217,
      207: 149,
      208: 21,
      209: 81,
      210: 98,
      211: 111,
      212: 10,
      213: 207,
      214: 252,
      215: 194,
      216: 255,
      217: 214,
      218: 170,
      219: 250,
      220: 127,
      221: 140,
      222: 66,
      223: 119,
      224: 62,
      225: 17,
      226: 233,
      227: 243,
      228: 29,
      229: 129,
      230: 30,
      231: 99,
      232: 187,
      233: 224,
      234: 56,
      235: 209,
      236: 198,
      237: 160,
      238: 199,
      239: 65,
      240: 32,
      241: 178,
      242: 272,
      243: 117,
      244: 121,
      245: 103,
      246: 244,
      247: 259,
      248: 3,
      249: 234,
      250: 239,
      251: 35,
      252: 38,
      253: 118,
      254: 184,
      255: 104,
      256: 71,
      257: 101,
      258: 86,
      259: 226,
      260: 189,
      261: 169,
      262: 215,
      263: 44,
      264: 43,
      265: 228,
      266: 131,
      267: 122,
      268: 163,
      269: 49,
      270: 89,
      271: 83,
      272: 245
    }
    this.selectRandom()
    this.objectUrl = 'https://objkt.com/users/tz1Vq5mYKXw1dD9js26An8dXdASuzo3bfE2w?fa_contract=KT1EpGgjQs73QfFJs9z7m1Mxm5MTnpC2tqse&availability=for_sale'
    this.objectKalaUrl = 'https://objkt.com/tokens/kalamint/'
    this.ipfsHttpsLink = "https://ipfs.io/ipfs/"
    this.tzktMetadataEndPoint = 'https://api.tzkt.io/v1/bigmaps/861/keys?key.eq='
    this.tzktOwnerEndPoint ='https://api.tzkt.io/v1/bigmaps/857/keys?active=true&value.eq=1&select=key&key.nat.eq='
    this.rankingsHashUrl = 'https://ipfs.io/ipfs/QmTY4jY9q4XwcyEVNfsQJj8t4Liesi7nhzKcqyPYwMdm1t'
    //Three
    this.board = new Three.Group()
    this.scene = new Three.Scene();    
    this.gameSize = window.innerWidth * GAME_WIDTH_FRACTION
    this.maxGameSize = MAX_GAME_SIZE
    this.camera = new Three.PerspectiveCamera(45, 1, 1, 5000);
    this.camera.position.x = 0;
    this.camera.position.y = 0;
    this.camera.position.z = 200;
    this.camera.lookAt(this.scene.position)
    this.loader = new Three.TextureLoader();  
    this.nftTexture = this.loader.load(''); 
    this.nftMaterial = new Three.MeshBasicMaterial({ map: this.nftTexture, transperant: true, alpha: 0.2});
    this.defaultGeometry = new Three.BoxGeometry(130, 130, 3, 1)
    // Socket Management
    this.socket.on('resizeGame', (width) => {
      this.resizeGameRender(width)
    }); 
  },
  mounted () {    
    this.intervalId = setInterval(() => {
      if (!this.pauseRandom) {
        this.selectRandom()
      }
    }, 5000);
    this.intervalId = setInterval(() => {
      this.countDown();
    }, 1000);
    this.renderer = new Three.WebGLRenderer({antialias: true});
    this.socket.emit("resizeGame", window.innerWidth)
    this.$refs.container.appendChild(this.renderer.domElement);
    this.selectRandom()
    this.buildGame()
    this.getNftData()
    this.renderer.render(this.scene, this.camera);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    if (this.pauseAnimation) {
      this.dislplayNft()
    } else {
      this.animateNft()
    }    
    this.socket.emit("resizeGame", window.innerWidth) 
  },
  methods: {
    async animateNft() {
      this.animationFrame = requestAnimationFrame(this.animateNft); 
      //this.nftDisplay.rotation.y = this.currentRotation
      
      let time = 0
      time = Date.now() * 0.001;
      this.nftDisplay.rotation.y = this.currentRotation + time;
      this.renderer.render(this.scene, this.camera);
    },
    async dislplayNft() {
      this.displayFrame = requestAnimationFrame(this.dislplayNft); 
      this.nftDisplay.rotation.y = this.currentRotation
      this.renderer.render(this.scene, this.camera);
    },
    async toggleAnimation() {
      if (this.pauseAnimation) {
        this.pauseAnimation = false
        this.pauseAnimationState = 'Pause'
        cancelAnimationFrame(this.displayFrame); 
        this.animateNft()
      } else {
        this.pauseAnimation = true
        this.pauseAnimationState = 'Animate'
        cancelAnimationFrame(this.animationFrame); 
        this.currentRotation = this.nftDisplay.rotation.y 
        this.dislplayNft()        
      }
    },
    async buildGame() {
      this.nftDisplay = new Three.Mesh(this.defaultGeometry, this.nftMaterial); 
      this.nftDisplay.position.set(0, 0, 0);
      this.scene.add(this.nftDisplay)                
      },
    async browseAllOnObjkt () {
      window.open(this.objectUrl, '_blank');
    },
    async checkThisOnObjkt () {
      const kalaId = this.idLookUp[this.txlId]
      window.open(this.objectKalaUrl + kalaId, '_blank');
    },
    async resizeGameRender(width) {
      this.gameSize = width * GAME_WIDTH_FRACTION
      if (this.gameSize > this.maxGameSize) {
        this.gameSize = this.maxGameSize
      }
      await this.renderer.setSize(this.gameSize, this.gameSize)
    }, 
    async getNftDataId() {
      await this.getNftData()
    },
    async getNftDataRank() {
      this.txlId = this.txlRevRankings[this.txlRanking] 
      await this.getNftData()
    },
    async getNftData() {
      await this.setNewNftImage() 
      await this.getNftMetaData() 
      await this.getOwner()
      this.txlRanking = Number(this.txlRankings[this.txlId.toString()]) + 1
    },
    async getNftMetaData() {
      const response = await fetch(this.rankingsHashUrl);
      const data = await response.json();
      this.txlData = await data[this.txlId]
    },
    async getIpfsHash () {
      const kalaId = this.idLookUp[this.txlId]
      const tzktApiUrl = this.tzktMetadataEndPoint + kalaId
      const response = await fetch(tzktApiUrl);
      const data = await response.json();
      const ipfsHash = data[0].value.ipfs_hash
      return ipfsHash
    },
    async getOwner () {
      const kalaId = this.idLookUp[this.txlId]
      const tzktApiUrl = this.tzktOwnerEndPoint + kalaId
      const response = await fetch(tzktApiUrl);
      const data = await response.json();
      const address = data[0].address
      if (reduceAddress(address) == 't.Upyq') {
        this.owner = 'PRIMARY - OBJKT.COM'
      } else {
        this.owner = reduceAddress(address)
      }      
    },
    async setNewNftImage() {
      const ipfsHash = await this.getIpfsHash()
      const displayLink = this.ipfsHttpsLink + ipfsHash.split('//')[1]
      this.loader.load(displayLink, (texture) => {
        this.nftTexture.dispose(); // Dispose old texture
        this.nftTexture = texture;
        this.nftDisplay.material.map = texture;
        this.nftDisplay.material.needsUpdate = true;
      });
    },
    async selectRandom() {        
      const newId = await getRandomIntInclusive(1, 273)
      this.txlId = newId    
      this.getNftData()  
      if (!this.pauseRandom) {
        this.countDownSeconds = 5    
      }
    },
    async togglePauseRandom() {  
      if (this.pauseRandom) {
        this.pauseRandom = false
        this.pauseState = 'Pause'
      } else {
        this.pauseRandom = true
        this.pauseState = 'Play'
      }
    },
    async prevTxl() {  
      this.txlId -= 1
      if (this.txlId < 0) {
        this.txlId = 0
      }    
      this.getNftData()  
    },
    async nextTxl() {  
      this.txlId += 1
      if (this.txlId > 273) {
        this.txlId = 273
      }    
      this.getNftData()  
    },
    async prevRank() {  
      this.txlRanking -= 1
      this.txlId = this.txlRevRankings[this.txlRanking]     
      this.getNftData()  
    },
    async nextRank() {  
      this.txlRanking += 1
      this.txlId = this.txlRevRankings[this.txlRanking] 
      this.getNftData()  
    },
    async showLearnMore() {
      if (this.showInfo)  {
        this.showInfo = false
      } else {
        this.showInfo = true
      }
    },
    async countDown() {
      if (!this.pauseRandom) {
        this.countDownSeconds -= 1 
      }
    },
    async leaveGameBC(gameId) { 
      if (gameId < 0) {
          return
      }    
      const activeAccount = await this.wallet.client.getActiveAccount() 
      if (!activeAccount) {
          return
      }    
      this.blockchainStatus = 'Joining Game on Smart Contract'              
      this.getSigner(activeAccount)  
      this.tezos.wallet
          .at(TXL_CONTRACT_ADDRESS)
          .then((contract) => {
              return contract.methods.leaveGame(gameId).send()
          })
          .then((op) => {
              console.log(`Waiting for ${op.opHash} to be confirmed...`);
              return op.confirmation().then(() => op.opHash);
          })
          .then((op) => {
              console.log(`Operation injected: https://ghost.tzstats.com/${op.hash}`)
            })
          .then(() => this.blockchainStatus = `Joined Game on Smart Contract ${{gameId}}` )
          .catch((error) => console.log(`Error3: ${JSON.stringify(error, null, 2)}`));
    },
    async getSigner(activeAccount) { 
            const signer = new RemoteSigner(activeAccount.address, NODE_URL )
            await this.tezos.setProvider({signer:signer})
            await this.tezos.setWalletProvider(this.wallet)  
            return signer
    },
  }
}
</script>

<template>
 
  <div class="centerBody">
    <div class="gameManagement" > 
        <div class="rowFlex">
          <div class="gameManagement"> 
            <div class="actionButton" @click="prevRank()" > &larr;  Prev Rank </div>
            <div class="actionButton" @click="prevTxl()" >  &larr;  Prev ID </div>
          </div>   
            <div class="gameManagement" >      
              <div class="gameManagement">Select New Rank </div>
              <select class="selectBox" v-model="txlRanking" @change="getNftDataRank()">
                <option v-for="(key, value) in txlRevRankings" :key="key" :value="value"> {{ value}} </option>
              </select>
            </div>           
          <div class="gameManagement"> 
            <div class="gameManagement" >Select New ID </div>
            <select class="selectBox" v-model="txlId" @change="getNftDataId()">
              <option v-for="(key, value) in idLookUp" :key="key" :value="value"> {{ value}} </option>
            </select>
          </div> 
          <div class="gameManagement"> 
            <div class="actionButton" @click="nextRank()" > Next Rank  &rarr; </div>
            <div class="actionButton" @click="nextTxl()" > Next ID  &rarr; </div>
          </div>
        </div>
        </div>
        <div class="rowFlex">  
          <div class="actionButton" @click="selectRandom"> Select Random TXL </div>
          <div class="actionButton" @click="checkThisOnObjkt(txlId)"> Buy {{ txlId.toString() }} On All Objkt.com </div>
          <div class="actionButton" @click="browseAllOnObjkt"> Browse On All Objkt.com </div>
          <div class="actionButtonHelp" @click="showLearnMore"> Learn More About 2.725K</div>
        </div>        
        <div v-if="showInfo" @click="showLearnMore" class="infoPopup"> 
          <div>
            <ul>
              <li class="infoPopup" v-for="(key, value) in nftInfo" :key="key" :value="value">{{ key }}</li>
            </ul>
          </div>
        </div>
        <div >    
          <div 
            ref="container"
          >
          </div> 
        </div>
        <div class="rowFlex">
          <div class="actionButton" @click="toggleAnimation"> {{pauseAnimationState}}  </div>
          <div class="gameInfo"> Random TXL in {{ countDownSeconds }} </div> 
          <div class="actionButton" @click="togglePauseRandom"> {{pauseState}} Random </div>
          <div class="actionButton" @click="payNftHolderBC"> Pay out TXL </div>
        </div>     
        <div class="rowFlex">       
          <div class="txlRank"> Rank: {{ txlRanking }}</div>
          <div class="txlRank"> ID: {{ txlId }}</div>
          <div class="txlRank"> Owner: {{ owner }}</div>           
          <div class="txlRank" v-for="(key, value) in txlData" :key="key" :value="value"> {{ value }}: {{ key }} </div>           
        </div> 
      </div>
    
</template>

<!-- Add "scoped" attribute to limit CSS to this component only -->
<style >
</style>
