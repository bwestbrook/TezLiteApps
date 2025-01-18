import { TezosToolkit } from '@taquito/taquito'
//import { RemoteSigner } from '@taquito/remote-signer';
import { NODE_URL, CONTRACT_ADDRESS } from '../constants'
//const cors = require('cors');
const Tezos = new TezosToolkit(NODE_URL);


export const getGamesFromContract = async() => {
  console.log('newGFC')
  const contract = await Tezos.wallet.at(CONTRACT_ADDRESS)
  const storage = await contract.storage()
  return storage.games
    }  
  


export const getContractService = async(nft_contract_address) => {
  const contract = await Tezos.wallet.at(nft_contract_address);
  return contract
}

export const createGameService = async() => {
  console.log('createGame')
}


