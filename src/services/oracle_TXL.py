# ⚠️ DEPRECATED — DO NOT RUN, DO NOT REUSE THE SEED.
#
# The seed phrase below was the v1 oracle key. It's been publicly
# committed to git history, so the address it derives to
# (tz1XbrvTMVa5dWQQBSCn2jgX7BPZyLRhgtKS) must be considered
# compromised. The v2 contract uses a new key sourced from
# TXL_ORACLE_MNEMONIC in .env (see docs/TXL_MAINNET_RUNBOOK.md).
#
# Use src/services/reconcile_txl_owners.py instead — same job
# (sync TXL owners from Kalamint), but reads the network from arg,
# the contract address from constants.js, and the oracle key from
# .env. It also batches via the v2 batchUpdateOwner entrypoint.
#
# This file is kept only so a reader following git blame on
# TXL_CONTRACT_ADDRESS_MAINNET can see where the old oracle ran. It
# will be removed in a future commit.
import requests
import time
import random
from pytezos import pytezos
from pytezos import Key
import numpy as np

# Generate a random integer between 1 and 10 (inclusive)
class WatchAceyDuecy():
    def __init__(self):
        '''
        ''' 
        seedPhrase = [
            'viable', 
            'spy', 
            'camp', 
            'win',
            'honey', 
            'impact', 
            'assist', 
            'town', 
            'parrot', 
            'abandon', 
            'similar', 
            'you', 
            'print', 
            'avocado', 
            'arrive', 
            'camp', 
            'maze', 
            'pet', 
            'secret', 
            'park',
            'thing', 
            'leg',
            'milk',
            'flush'
            ]
        key = Key.from_mnemonic(seedPhrase)
        self.pytezos = pytezos.using(key=key)
        #self.pytezos.reveal().send()
        self.contractAddress = "KT1HD71gj4ZdehpS4Ri8nasjpDTPDQ574Sxy"
        self.tzktOwnerEndPoint ='https://api.tzkt.io/v1/bigmaps/857/keys?active=true&value.eq=1&select=key&key.nat.eq='
        self.contract = self.pytezos.contract(self.contractAddress)
        self.builder = self.pytezos.contract(self.contractAddress)
        self.wallet = self.pytezos.contract(self.contractAddress)
        self.apiUrl = 'https://api.ghostnet.tzkt.io/v1/contracts/' + self.contractAddress + '/storage'

    def watch(self):
        '''
        '''
        i = 0
        response = requests.get(self.apiUrl).json()
        while True:
            contractStorage = requests.get(self.apiUrl).json()
            print(contractStorage)
            kalaIds = list(reversed(sorted(contractStorage['idLookUp'].keys())))
            for j, kalaId in enumerate(kalaIds):
                nftData = contractStorage['idLookUp'][kalaId]
                tzktApiUrl = self.tzktOwnerEndPoint + kalaId
                apiResponse = requests.get(tzktApiUrl).json()
                if nftData['owner'] != apiResponse[0]['address']:
                    print('NEW OWNER!!')
                    self.updateOwner(int(kalaId), apiResponse[0]['address'])
                else:
                    print("idle rechecking", j + 1, 'of 271')
            print("Will check again in one hour")
            time.sleep(3600)
            i += 1

    def updateOwner(self, kalaId, address):
        '''
        '''
        print()
        print()
        print()
        print(kalaId, address)
        try:
            print('Injection Operation')
            #print(self.builder.updateOwner)
            print(self.builder.updateOwner(address=address, txlId=kalaId).send())
            
        except:
            print('fail bulk')



if __name__ == '__main__':
    wad = WatchAceyDuecy()
    wad.watch()


