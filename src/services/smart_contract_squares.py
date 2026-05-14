import smartpy as sp


@sp.module
def main():   
    
           
    class FootBallSquares(sp.Contract):
        
        def __init__(self):
            '''
            KNOWN ISSUE: the original `games` map mixed string keys ('winDict')
            with int keys (1..100 for grid spaces). SmartPy can't compile a
            mixed-key map. Until this is restructured into a proper per-game
            record (spaces / winDict / xLabels / yLabels), the contract will
            fail compile. See TODO in newGrid().
            '''
            self.data.admin = sp.address("tz1ZU2RLW7UgY8XXz49ccKihNy86zs6TdQ8Q")
            self.data.oracle = sp.address("tz1ZU2RLW7UgY8XXz49ccKihNy86zs6TdQ8Q")
            # AD contract (current deployed on shadownet). When AD redeploys,
            # update via `updateAdContract` — no admin entrypoint exists yet;
            # add one when ready.
            self.data.adContract = sp.address("KT1VpPzzwqyJEywjEv2TyfMNrQRPs3rGT1Zs")
            self.data.txlContract = sp.address("KT1Ro63rVDUx2x8pMChCLSySso8t6JH47oRQ")
            self.data.games = sp.cast({}, sp.map[sp.nat, sp.map[sp.nat, sp.record(
                owner=sp.address,
                amountPerSquare=sp.mutez,
                x=sp.nat,
                y=sp.nat,
            )]])
            self.data.currentGridIndex = sp.nat(0)
            # winDict moved out of the per-grid map (string keys + nat keys
            # can't coexist). Holds per-grid quarter-winner records keyed by
            # gridId, then by quarter-tag string.
            self.data.winDicts = sp.cast({}, sp.map[sp.nat, sp.map[sp.string, sp.nat]])
            # Oracle-supplied axis randomization. Keyed by gridId.
            self.data.axes = sp.cast({}, sp.map[sp.nat, sp.record(
                xLabels=sp.map[sp.nat, sp.nat],
                yLabels=sp.map[sp.nat, sp.nat],
                seed=sp.string,
            )])
            self.data.fee = sp.mutez(100000)
            
           
        @sp.entrypoint
        def default(self):
            pass
            
        @sp.entrypoint
        def newGrid(self, params):
            '''Open a new grid. Creator buys `nSquares` of the 100 spaces.'''
            sp.cast(params.nSquares, sp.nat)
            assert params.nSquares > 0, "nSquares must be > 0"
            assert params.nSquares <= 100, "nSquares too large"
            assert sp.amount > self.data.fee, "amount must exceed fee"
            amountPerSquare = sp.split_tokens(sp.amount - self.data.fee, 1, params.nSquares)
            sp.send(self.data.txlContract, self.data.fee)
            new_grid = sp.cast({}, sp.map[sp.nat, sp.record(
                owner=sp.address,
                amountPerSquare=sp.mutez,
                x=sp.nat,
                y=sp.nat,
            )])
            i = sp.nat(1)
            while i <= params.nSquares:
                new_grid[i] = sp.record(
                    owner=sp.sender,
                    amountPerSquare=amountPerSquare,
                    x=sp.nat(0),
                    y=sp.nat(0),
                )
                i += 1
            self.data.games[self.data.currentGridIndex] = new_grid
            # Initialize the win-dict for this grid (all quarters zeroed).
            self.data.winDicts[self.data.currentGridIndex] = sp.cast({
                'winQ1': 0, 'winQ1R': 0,
                'winQ2': 0, 'winQ2R': 0,
                'winQ3': 0, 'winQ3R': 0,
                'winQ4': 0, 'winQ4R': 0,
            }, sp.map[sp.string, sp.nat])
            self.data.currentGridIndex += 1

        @sp.entrypoint
        def joinGrid(self, params):
            '''Join an existing grid by buying additional squares.'''
            sp.cast(params.nSquares, sp.nat)
            sp.cast(params.gridId, sp.nat)
            assert params.nSquares > 0, "nSquares must be > 0"
            assert sp.amount > self.data.fee, "amount must exceed fee"
            amountPerSquare = sp.split_tokens(sp.amount - self.data.fee, 1, params.nSquares)
            sp.send(self.data.txlContract, self.data.fee)
            grid = self.data.games[params.gridId]
            grid_size = sp.cast(0, sp.nat)
            for _k in grid.keys():
                grid_size += 1
            assert params.nSquares + grid_size <= 100, "grid full"
            i = sp.nat(0)
            while i < params.nSquares:
                grid[grid_size + i + 1] = sp.record(
                    owner=sp.sender,
                    amountPerSquare=amountPerSquare,
                    x=sp.nat(0),
                    y=sp.nat(0),
                )
                i += 1
            self.data.games[params.gridId] = grid

        @sp.entrypoint
        def randomizeAxes(self, params):
            '''Oracle submits two shuffled [0..9] permutations.'''
            assert sp.sender == self.data.oracle, "not oracle"
            sp.cast(params.gridId, sp.nat)
            sp.cast(params.xLabels, sp.map[sp.nat, sp.nat])
            sp.cast(params.yLabels, sp.map[sp.nat, sp.nat])
            sp.cast(params.seed, sp.string)
            self.data.axes[params.gridId] = sp.record(
                xLabels=params.xLabels,
                yLabels=params.yLabels,
                seed=params.seed,
            )
            sp.emit([params.gridId, params.seed], tag='axesRandomized')

        @sp.entrypoint
        def setWinner(self, params):
            '''Mark a quarter winner. Oracle-only.'''
            assert sp.sender == self.data.oracle, "not oracle"
            sp.cast(params.gridId, sp.nat)
            sp.cast(params.winType, sp.string)
            self.data.winDicts[params.gridId][params.winType] = sp.nat(1)
            sp.emit([params.gridId, params.winType], tag='winnerSet')

       
@sp.add_test()
def test():
    s = sp.test_scenario("squares basic compile", main)
    a = main.FootBallSquares()
    s += a
