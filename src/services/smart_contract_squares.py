import smartpy as sp


@sp.module
def main():   
    
           
    class FootBallSquares(sp.Contract):
        
        def __init__(self):
            '''
            '''               
            #Game Control         
            self.data.admin = sp.address("tz1Vq5mYKXw1dD9js26An8dXdASuzo3bfE2w")
            self.data.oracle = sp.address("tz1XbrvTMVa5dWQQBSCn2jgX7BPZyLRhgtKS")
            self.data.adContract = sp.address("KT1W3Z2zVw8FhNpihuFJS8P2iLDC2APwHTD2")
            self.data.txlContract = sp.address("KT1HD71gj4ZdehpS4Ri8nasjpDTPDQ574Sxy")
            self.data.games = {}
            self.data.currentGridIndex = 0
            self.data.winDict = {                
                'winQ1': 0,
                'winQ1R': 0,
                'winQ2': 0,
                'winQ2R': 0,
                'winQ3': 0,
                'winQ3R': 0,
                'winQ4': 0,
                'winQ4R': 0
            }
            self.data.fee = sp.mutez(100000)
            
           
        @sp.entrypoint
        def default(self):
            pass
            
        @sp.entrypoint
        def newGrid (self, params):
            '''
            '''
            sp.cast(params.nSquares, sp.nat)
            amountPerSquare = sp.split_tokens(sp.amount - self.data.fee, 1, params.nSquares)            
            grid_space = sp.record(
                owner =  sp.sender,
                amountPerSquare = amountPerSquare,
                x =  sp.nat(0),
                y =  sp.nat(0),
                
                
            )
            
            i = 0 
            new_grid = {
                'winDict': self.data.winDict
            }
            while i < params.nSquares:
                new_grid[i + 1] = grid_space
                i+= 1
            self.data.games[self.data.currentGridIndex] = new_grid
            self.data.currentGridIndex += 1

        @sp.entrypoint
        def joinGrid(self, params):
            '''
            '''
            sp.cast(params.nSquares, sp.nat)
            sp.cast(params.gridId, sp.nat)
            amountPerSquare = sp.split_tokens(sp.amount - self.data.fee, 1, params.nSquares)   
 
            grid_space = sp.record(
                owner =  sp.sender,
                amountPerSquare = amountPerSquare,
                x =  sp.nat(0),
                y =  sp.nat(0),
            )
            grid = self.data.games[params.gridId]
            sp.emit(len(grid))
            grid_size = len(grid)
            i = 0 
            if params.nSquares + grid_size > 100:
                sp.emit('grid full')
            else:
                while i + grid_size < grid_size + params.nSquares:             
                    grid[i + grid_size + 1] = grid_space
                    i += 1 
            self.data.games[params.gridId] = grid

        @sp.entrypoint
        def randomizeGrid(self, params):
            '''
            '''
            sp.cast(params.gridId, sp.nat)
            i = 1
            grid = self.data.games[params.gridId]
            while i < 100:
                grid[i].x = 1
                grid[i].y = 2
                i += 1
            self.data.games[params.gridId] = grid


        @sp.entrypoint
        def setWinner(self, params):
            '''
            '''
            sp.cast(params.gridId, sp.nat)
            sp.cast(params.gridIndex, sp.nat)
            sp.cast(params.winType, sp.string)
            grid = self.data.games[params.gridId]
            grid[params.gridIndex].winDict[params.winType] = sp.nat(1)
            sp.emit(grid)
            self.data.games[params.gridId] = grid

       
@sp.add_test()
def test():
    s = sp.test_scenario("my first test", main)
  
    a = main.FootBallSquares()
    s += a
    #a.set_initial_balance(sp.tez(2))
    player1 = sp.test_account("player1")
    player2 = sp.test_account("player2")
    player3 = sp.test_account("player3")   
    fee = sp.mutez(400000)
    a.newGrid(
        _sender = player1.address,
        _amount = sp.mutez(3400000),
        nSquares = sp.nat(33)
    )
     
    a.joinGrid(
        _sender = player2.address,
        _amount = sp.mutez(3400000),
        nSquares = sp.nat(33),
        gridId = sp.nat(0)        
    )
    a.joinGrid(
        _sender = player3.address,
        _amount = sp.mutez(3500000),
        nSquares = sp.nat(34),
        gridId = sp.nat(0)        
    )
    a.randomizeGrid(
        gridId = sp.nat(0)
    )
    a.setWinner(
        gridId = sp.nat(0),
        gridIndex = sp.nat(3),
        winType = sp.string('winQ1')
    )
    s.show(a.balance) 
    
    
     