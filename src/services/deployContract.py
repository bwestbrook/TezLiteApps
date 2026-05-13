import requests
import time
from pytezos import pytezos
from pytezos import Key
import numpy as np

# Generate a random integer between 1 and 10 (inclusive)
class DeployContract():

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
    
    def compileContract(self):
        '''
        '''
        print(dir(self.pytezos))

if __name__ == '__main__':
    dp = DeployContract()
    dp.compileContract()