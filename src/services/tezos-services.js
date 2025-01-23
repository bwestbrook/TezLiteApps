import { TezosToolkit } from '@taquito/taquito'
//import { RemoteSigner } from '@taquito/remote-signer';
import { NODE_URL } from '../constants'
//const cors = require('cors');
const Tezos = new TezosToolkit(NODE_URL);

export const getContractService = async(nft_contract_address) => {
  const contract = await Tezos.wallet.at(nft_contract_address);
  return contract
}

export const createGameService = async() => {
  console.log('createGame')
}

