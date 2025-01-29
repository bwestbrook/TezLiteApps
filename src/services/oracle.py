import requests
import time
import random
from pytezos import pytezos

# Generate a random integer between 1 and 10 (inclusive)
class WatchAceyDuecy():
    def __init__(self):
        '''
        '''
        self.pytezos = pytezos
        print(self.pytezos)
        self.contractAddress = "KT1TcSzvz6891eK8SZ69ih2fkYKDPnm3eP9u"
        self.contract = self.pytezos.contract(self.contractAddress)
        self.builder = self.pytezos.contract(self.contractAddress)
        self.wallet = self.pytezos.contract(self.contractAddress)
        self.apiUrl = 'https://api.ghostnet.tzkt.io/v1/contracts/' + self.contractAddress + '/storage'

    def watch(self):
        '''
        '''
        i = 0
        response = requests.get(self.apiUrl).json()
        while i < 10000:
            response = requests.get(self.apiUrl).json()
            for gameId, gameData in response['games'].items():
                if gameData['gameStatus'] == '0':
                    print('dealing cards')
                    self.dealCards(int(gameId))
                elif gameData['gameStatus'] == '2':
                    print('dealing Final')
                    self.lastCard(int(gameId))
                else:
                    print('static game')
            time.sleep(5)
            i += 1

    def dealCards(self, gameId):
        '''
        '''
        firstCard = random.randint(1, 13)
        secondCard = random.randint(1, 13)
        cards = list(sorted([firstCard, secondCard]))
        print(gameId, cards)
        firstCard = cards[0]
        secondCard = cards[1]
        self.pytezos.bulk(
           self.builder.firstTwoCards(gameId = gameId, firstCard = firstCard, secondCard = secondCard)
        ).send(min_confirmations=1)

    def lastCard(self, gameId):
        '''
        '''
        lastCard = random.randint(1, 13)
        try:
            self.pytezos.bulk(self.builder.lastCard(gameId = gameId, lastCard = lastCard)).send(min_confirmations=2)
        except: 
            print('dog')



if __name__ == '__main__':
    wad = WatchAceyDuecy()
    wad.watch()


