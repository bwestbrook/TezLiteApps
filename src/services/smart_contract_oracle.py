import smartpy as sp

@sp.module
def main():
    class RandomOracle(sp.Contract):
        
        def __init__(self):
            '''
            '''               
            #Game Control         
            self.data.admin = sp.address("tz1Vq5mYKXw1dD9js26An8dXdASuzo3bfE2w")
            self.data.oracle = sp.address("tz1XbrvTMVa5dWQQBSCn2jgX7BPZyLRhgtKS")
            self.data.txlContract = sp.address("KT1HD71gj4ZdehpS4Ri8nasjpDTPDQ574Sxy")
            self.data.requests = {}
            self.data.currentRequestIndex = 0
           
            
        @sp.entrypoint
        def getRandomNumber(self):
            '''
            
            '''
            sp.cast(sp.now, sp.timestamp)
            sp.cast(sp.sender, sp.address)
            #time = sp.now
            new_request = sp.record(
                requester = sp.sender,
                time = sp.now,
                randomNumber = 0
            )
            sp.emit((sp.sender, sp.now), tag='randomRequested')
            self.data.requests[self.data.currentRequestIndex] = new_request
            self.data.currentRequestIndex += 1


        @sp.entrypoint
        def setRandomNumber(self, params):
            '''
            Verify coming from Oracle sender only
            '''
            sp.cast(sp.sender, sp.address)
            sp.cast(params.requestId, sp.int_or_nat)
            sp.cast(params.randomNumber, sp.int_or_nat)
            self.data.requests[params.requestId].randomNumber = params.randomNumber
            sp.emit((sp.sender, sp.now), tag='randomReturned')

               
      

       
@sp.add_test()
def test():
    s = sp.test_scenario("my first test", main)
    player1 = sp.test_account("player1")
    a = main.RandomOracle()
    s += a
    #a.set_initial_balance(sp.tez(2))
    player1 = sp.test_account("player1")
    player2 = sp.test_account("player2")
    player3 = sp.test_account("player3")
    player4 = sp.test_account("tz1Vq5mYKXw1dD9js26An8dXdASuzo3bfE2w")
    a.getRandomNumber(
        _sender = player1.address,
        _amount = sp.tez(1)
    )
    a.setRandomNumber(
        _sender = player2.address,
        requestId = sp.int_or_nat(0),
        randomNumber = sp.int_or_nat(50)
    )
    s.show(a.balance)


    