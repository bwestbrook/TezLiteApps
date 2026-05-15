# ⚠️ DEPRECATED — historical reference only.
#
# This watcher hardcodes `api.ghostnet.tzkt.io` and the ghostnet TXL
# manager `KT1HD71gj4ZdehpS4Ri8nasjpDTPDQ574Sxy`. Ghostnet was
# decommissioned in 2026 along with Baking Bad's TzKT Ghostnet API, so
# every HTTP call below now fails DNS. The live TXL manager + snapshot
# oracle path needs to be re-implemented against shadownet (or whichever
# network the redeployed manager lives on) before this script is useful
# again. See src/services/TXL_OWNERS_DATA.md for the current state.
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


