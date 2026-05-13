import smartpy as sp


@sp.module
def main():   
    
           
    class RandomOracle(sp.Contract):
        
        def __init__(self):
            # Game control
            self.data.admin = sp.address("tz1Vq5mYKXw1dD9js26An8dXdASuzo3bfE2w")
            self.data.oracle = sp.address("tz1XbrvTMVa5dWQQBSCn2jgX7BPZyLRhgtKS")
            self.data.adContract = sp.address("KT1W3Z2zVw8FhNpihuFJS8P2iLDC2APwHTD2")
            self.data.txlContract = sp.address("KT1HD71gj4ZdehpS4Ri8nasjpDTPDQ574Sxy")

            # Outstanding random-number requests. Indexed by the oracle's
            # own monotonic counter (currentRequestIndex). Each value is the
            # full record described by `new_request` further down — we tell
            # SmartPy the type up front so the compiled storage isn't left
            # with unresolved type variables.
            self.data.requests = sp.cast({}, sp.map[sp.nat, sp.record(
                requestStatus=sp.nat,
                requester=sp.address,
                requestTime=sp.timestamp,
                requestFillTime=sp.timestamp,
                randomNumber=sp.nat,
                opHash=sp.string,
                type=sp.nat,
                requestId=sp.string,
                randomNumberMax=sp.nat,
                randomNumberExcludes=sp.string,
                contractAddress=sp.address,
                entryPoint=sp.string,
                entryPointParams=sp.string,
            )])

            # NOTE: the old `self.data.lambdas = {}` field was untyped AND
            # never written to (its only assignment is commented out in
            # logRequest). Removed — was the second source of the "unknown
            # type variable" warning at origination time.

            self.data.currentRequestIndex = sp.nat(0)
            self.data.fee = sp.mutez(100000)

            # Scratch default — typed explicitly so SmartPy doesn't try to
            # guess int vs nat for the literal `0`/`3143534`. String
            # literals just stay as bare Python strings (sp.string is a
            # type-only — not a value constructor).
            self.data.entryPointParams = sp.record(
                gameId=sp.nat(0),
                hash="doadfg",
                card=sp.nat(3143534),
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
    """Deployment scenario for RandomOracle.

    Reduced to the minimum the SmartPy compiler needs to emit Michelson:
    instantiate the contract and add it to a scenario. The old expanded
    test (calling makeRequest, building a lambda for logRequest) relied on
    `sp.build_lambda`, which was removed from SmartPy in 2024. That entire
    behaviour-exercising block is gone — it was decorative for deployment.
    Add behavior tests back here once you settle on the current SmartPy
    lambda-building API.
    """
    s = sp.test_scenario("RandomOracle deployment", main)
    s.h1("Originate RandomOracle")
    oracle = main.RandomOracle()
    s += oracle
