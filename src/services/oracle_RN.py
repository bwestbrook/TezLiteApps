import requests
import hashlib
import time
import os
import random
from pytezos import pytezos
from pytezos import Key
import smartpy as sp
import numpy as np
import pylab as pl
from random_word import RandomWords

def makeContract(params):
    administrated = sp.contract(
                        sp.record(    
                                card3 = sp.nat,
                                gameId = sp.nat,
                                hash = sp.string
                            ), 
                            a.data.adContract, 
                            entrypoint="firstCard")
    sp.transfer(sp.record (    
            card3 = sp.nat(3),
            gameId = sp.nat(0),
            hash = 'adfavio4534a22222faufA897'
        ), sp.tez(0), administrated.unwrap_some())
# Generate a random integer between 1 and 10 (inclusive)
class WatchRandomNumber():
    '''
    '''

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
        self.contractAddress = "KT1RKS19cEDCaLVxXQyJK85eK8iwrBoRsKQj"
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
            for requestIdIdx, requestData in contractStorage['requests'].items():
                contractAddress = requestData['contractAddress']
                entryPoint = requestData['entryPoint']
                requestId = requestData['requestId']
                randomNumberMax = requestData['randomNumberMax']
                entryPointParams = requestData['entryPointParams']
                print(requestId, requestData)
                if requestData['requestStatus'] == '0':
                    
                    #import ipdb;ipdb.set_trace()
                    self.setRandomNumber(contractAddress, entryPointParams, int(requestIdIdx), int(randomNumberMax))
                else:
                    time.sleep(3)
                    print('...')
            i += 1

    def setRandomNumber(self, contractAddress, entryPointParams, requestId, randomNumberMax, params={}):
        '''
        '''
        
        opHash = ''
        signingHash = self.getSigningHash()
        randomNumber, signingHash = self.getRandomNumber(randomNumberMod=randomNumberMax)
        print()
        print(entryPointParams)
        print(randomNumber)
        while len(opHash) == 0:
            try:
                print('Injection Operation')
                params = {
                    "randomNumber": randomNumber,
                    "opHash": signingHash, 
                    "requestId": requestId
                }      
                print(params)   
                time.sleep(2)       
                print(self.builder)
                operation = self.builder.logRequest(**params).send(min_confirmations=2)
                opHash = (operation.hash())    
                
            except:
                print('fail log Random Number')   

    def getRandomNumber(self, randomNumberMod=6, params={}):
        '''
        '''      
        rWords = RandomWords()
        hash = "'secretbox_NONCEBYTES', 'signMessage', 'toHex' with the previous requested module '@airgap/beacon-dapp'"
        randomNumbers = []
        for i in range(10):
            hash += rWords.get_random_word()
            for j in (range(10)):
                randomNumber = random.randint(-2.78e9, 3.141e9)  
                randomNumber += random.randint(-2.78e9, 3.141e9)  
                hash += str(randomNumber)
        hash_object = hashlib.sha256(hash.encode())
        signingHash = hash_object.hexdigest()        
        randomNumber = int(signingHash, 16)
        randomNumber = randomNumber % randomNumberMod
        print(signingHash, randomNumber)
        time.sleep(1)
        return randomNumber, signingHash

    def getSigningHash(self, params={}):
        '''
        '''      
        rWords = RandomWords()
        hash = "'secretbox_NONCEBYTES', 'signMessage', 'toHex' with the previous requested module '@airgap/beacon-dapp'"
        for i in range(25):
            hash += rWords.get_random_word()
            for j in (range(100)):
                 randomNumber = random.randint(-2.78e9, 3.141e9)  
                 randomNumber += random.randint(-2.78e9, 3.141e9)  
                 hash += str(randomNumber)
        hash_object = hashlib.sha256(hash.encode())
        signingHash = hash_object.hexdigest()
        #print(signingHash)
        #time.sleep(2)
        return signingHash
    
           



if __name__ == '__main__':
    wrn = WatchRandomNumber()
    wrn.watch()
    


