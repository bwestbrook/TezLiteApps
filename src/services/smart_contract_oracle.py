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
            self.data.adContract = sp.address("KT1W3Z2zVw8FhNpihuFJS8P2iLDC2APwHTD2")
            self.data.txlContract = sp.address("KT1HD71gj4ZdehpS4Ri8nasjpDTPDQ574Sxy")
            self.data.requests = {}
            self.data.lambdas = {}
            self.data.currentRequestIndex = 0
            self.data.fee = sp.mutez(100000)
            self.data.entryPointParams = sp.record (
                    gameId = 0,
                    hash = 'doadfg',
                    card = 3143534
                )
           
        @sp.entrypoint
        def default(self):
            pass
            
        @sp.entrypoint
        def makeRequest(self, params):
            '''
            Random Number Type
            0: 'flat'
            --- randomNumberParam1 = low end inclusive
            --- randomNumberParam2 = high end inclusive
            --- cantBeNumbers = , seperated string of numbers
            '''
            getRandomNumber = 0
            if sp.sender == self.data.oracle:
                getRandomNumber = 1
            else:
                sp.emit('wrongOracleFee', tag='wrongOracleFee')
            if sp.amount == self.data.fee:
                getRandomNumber = 1
            else:
                sp.emit('noFeeNotAdmin', tag='noFeeNotAdmin')     
            
            if getRandomNumber == 1:
                sp.cast(sp.now, sp.timestamp)
                sp.cast(sp.sender, sp.address)
                sp.cast(params.contractAddress, sp.address)
                sp.cast(params.randomNumberType, sp.nat)
                sp.cast(params.randomNumberMax, sp.nat)
                sp.cast(params.randomNumberExcludes, sp.string)
                sp.cast(params.entryPoint, sp.string)
                sp.cast(params.entryPointParams, sp.string)
                sp.cast(params.requestId, sp.string)            
                #time = sp.now
                isNewRequest = 1
                checkRequest = 0
                while checkRequest < self.data.currentRequestIndex:       
                    if self.data.requests[checkRequest].requestId == params.requestId:
                        isNewRequest =  0
                    checkRequest += 1
                if isNewRequest == 1:
                    new_request = sp.record(
                        requestStatus = 0, 
                        requester = sp.sender,
                        requestTime = sp.now,
                        requestFillTime = sp.now,
                        randomNumber = 0,
                        opHash = '', 
                        type = params.randomNumberType,
                        requestId = params.requestId,
                        randomNumberMax = params.randomNumberMax,
                        randomNumberExcludes = params.randomNumberExcludes,
                        contractAddress = params.contractAddress,
                        entryPoint = params.entryPoint,
                        entryPointParams = params.entryPointParams
                    )
                    sp.emit((sp.sender, sp.now), tag='randomRequested')
                    self.data.requests[self.data.currentRequestIndex] = new_request
                    self.data.currentRequestIndex += 1
                else:
                    sp.emit('notNewRequest')
            else:
                sp.emit('failed Oracle', tag='failedOracle')            

        @sp.entrypoint
        def logRequest(self, params):
            '''
            '''
            sp.cast(params.requestIndex, sp.nat)
            sp.cast(params.contractLambda, sp.lambda_(sp.record(card = sp.nat, gameId = sp.nat, hash = sp.string), sp.unit, with_storage="no-access", with_operations=True, with_exceptions=True, with_mutez_overflow=True, with_mutez_underflow=True))
            sp.emit(params.contractLambda)
            #self.data.lambdas[params.requestId] = params.contractLambda
            pass
                
       
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
    adContract = "KT1W3Z2zVw8FhNpihuFJS8P2iLDC2APwHTD2"
    fee = sp.mutez(100000)
    a.makeRequest(
        _sender = player1.address,
        _amount = fee,
        randomNumberType = sp.nat(0),
        randomNumberMax = sp.nat(1),
        randomNumberExcludes = '10',
        contractAddress = a.data.adContract,
        requestId = 'AD-Game1-Card1',
        entryPoint = 'firstCard',
        entryPointParams = 'gameId-0 card-*RN*'
    )
    s.show(a.balance) 
     #params built by oracle  
    paramTypes = sp.record (    
        card = sp.nat,
        gameId = sp.nat,
        hash = sp.string
    )
    contractParams = sp.record (    
        card = sp.nat(3),
        gameId = sp.nat(0),
        hash = 'adfavio4534afaufA897'
    )
    contract = a.data.adContract
    params = {
        'contract': contract,
        'paramTypes': paramTypes,
        'contractParams': contractParams
    }
    def new_contract(params):
        administrated = sp.contract(paramTypes, contract, entrypoint="firstCard")
        sp.transfer(params, sp.tez(0), administrated.unwrap_some())
    contractLambda = sp.build_lambda(new_contract, with_operations=True)

    a.logRequest(
        _sender = a.data.oracle,
        requestIndex = sp.nat(0),
        contractLambda = contractLambda)
    
     