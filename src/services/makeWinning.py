from pprint import pprint
gameWinners = []
count = 0
if True:
    corner = [-1, -1, -1]  
    gameWinnerSet = []
    for i in range(0, 4):
        coord = [corner[0] + i, corner[1] + i, corner[2] + i]
        print(coord)
        gameWinnerSet.append(coord)
        count += 1
        if count == 4:
            gameWinners.append(gameWinnerSet)
            gameWinnerSet = []
            count = 0
    corner = [-1, -1, 2]  
    gameWinnerSet = []
    for i in range(0, 4):
        coord = [corner[0] + i, corner[1] + i, corner[2] - i]
        print(coord)
        gameWinnerSet.append(coord)
        count += 1
        if count == 4:
            gameWinners.append(gameWinnerSet)
            gameWinnerSet = []
            count = 0
    corner = [2, -1, -1]  
    gameWinnerSet = []
    for i in range(0, 4):
        coord = [corner[0] - i, corner[1] + i, corner[2] + i]
        print(coord)
        gameWinnerSet.append(coord)
        count += 1
        if count == 4:
            gameWinners.append(gameWinnerSet)
            gameWinnerSet = []
            count = 0
    corner = [2, -1, 2]  
    gameWinnerSet = []
    for i in range(0, 4):
        coord = [corner[0] - i, corner[1] + i, corner[2] - i]
        print(coord)
        gameWinnerSet.append(coord)
        count += 1
        if count == 4:
            gameWinners.append(gameWinnerSet)
            gameWinnerSet = []
            count = 0
if True:
    for i in range(-1, 3):
        gameWinnerSet = []
        for j in range(-1, 3):
            coord = [i, j, j]
            gameWinnerSet.append(coord)
            count += 1
            if count == 4:
                gameWinners.append(gameWinnerSet)
                gameWinnerSet = []
                count = 0
    for i in (range(-1, 3)):
        gameWinnerSet = []
        for j in reversed(range(-1, 3)):
            coord = [i, -j + 1, j]
            gameWinnerSet.append(coord)
            count += 1
            if count == 4:
                gameWinners.append(gameWinnerSet)
                gameWinnerSet = []
                count = 0
    for i in range(-1, 3):
        gameWinnerSet = []
        for j in range(-1, 3):
            coord = [j, i, j]
            gameWinnerSet.append(coord)
            count += 1
            if count == 4:
                gameWinners.append(gameWinnerSet)
                gameWinnerSet = []
                count = 0
    for i in (range(-1, 3)):
        gameWinnerSet = []
        for j in reversed(range(-1, 3)):
            coord = [-j + 1, i, j]
            gameWinnerSet.append(coord)
            count += 1
            if count == 4:
                gameWinners.append(gameWinnerSet)
                gameWinnerSet = []
                count = 0
    for i in range(-1, 3):
        gameWinnerSet = []
        for j in range(-1, 3):
            coord = [j, j, i]
            gameWinnerSet.append(coord)
            count += 1
            if count == 4:
                gameWinners.append(gameWinnerSet)
                gameWinnerSet = []
                count = 0
    count = 0
    for i in (range(-1, 3)):
        gameWinnerSet = []
        for j in reversed(range(-1, 3)):
            coord = [j, -j + 1, i]
            gameWinnerSet.append(coord)
            count += 1
            if count == 4:
                gameWinners.append(gameWinnerSet)
                gameWinnerSet = []
                count = 0
    count = 0
    for j in range(-1, 3):
        gameWinnerSet = []
        for k in range(-1, 3):
            for i in range(-1, 3):
                coord = [i, j, k]
                print(count, coord)
                gameWinnerSet.append(coord)
                count += 1
                if count == 4:
                    gameWinners.append(gameWinnerSet)
                    gameWinnerSet = []
                    count = 0
    count = 0
    for k in range(-1, 3):
        gameWinnerSet = []
        for i in range(-1, 3):
            for j in range(-1, 3):
                coord = [i, j, k]
                print(count, coord)
                gameWinnerSet.append(coord)
                count += 1
                if count == 4:
                    gameWinners.append(gameWinnerSet)
                    gameWinnerSet = []
                    count = 0
    count = 0
    for i in range(-1, 3):
        gameWinnerSet = []
        for j in range(-1, 3):
            for k in range(-1, 3):
                coord = [i, j, k]
                print(count, coord)
                gameWinnerSet.append(coord)
                count += 1
                if count == 4:
                    gameWinners.append(gameWinnerSet)
                    gameWinnerSet = []
                    count = 0
pprint(gameWinners)
print(len(gameWinners))



export const data.game_winners = {
    0: [111, 112, 113, 114],
    1: [121, 122, 123, 124],
    2: [131, 132, 133, 134],
    3: [141, 142, 143, 144],
    4: [211, 212, 213, 214],
    5: [221, 222, 223, 224],
    6: [231, 232, 233, 234],
    7: [241, 242, 243, 244],
    8: [311, 312, 313, 314],
    9: [321, 322, 323, 324],
    10: [331, 332, 333, 334],
    11: [341, 342, 343, 344],
    12: [411, 412, 413, 414],
    13: [421, 422, 423, 424],
    14: [431, 432, 433, 434],
    15: [441, 442, 443, 444],
    16: [111, 121, 131, 141],
    17: [211, 221, 231, 241],
    18: [311, 321, 331, 341],
    19: [411, 421, 431, 441],
    20: [112, 122, 132, 142],
    21: [212, 222, 232, 242],
    22: [312, 322, 332, 342],
    23: [412, 422, 432, 442],
    24: [113, 123, 133, 143],
    25: [213, 223, 233, 243],
    26: [313, 323, 333, 343],
    27: [413, 423, 433, 443],
    28: [114, 124, 134, 144],
    29: [214, 224, 234, 244],
    30: [314, 324, 334, 344],
    31: [414, 424, 434, 444],
    32: [111, 211, 311, 411],
    33: [112, 212, 312, 412],
    34: [113, 213, 313, 413],
    35: [114, 214, 314, 414],
    36: [121, 221, 321, 421],
    37: [122, 222, 322, 422],
    38: [123, 223, 323, 423],
    39: [124, 224, 324, 424],
    40: [131, 231, 331, 431],
    41: [132, 232, 332, 432],
    42: [133, 233, 333, 433],
    43: [134, 234, 334, 434],
    44: [141, 241, 341, 441],
    45: [142, 242, 342, 442],
    46: [143, 243, 343, 443],
    47: [144, 244, 344, 444],
    48: [111, 122, 133, 144],
    49: [114, 123, 132, 141],
    50: [211, 222, 233, 244],
    51: [214, 223, 232, 241],
    52: [311, 322, 333, 344],
    53: [314, 323, 332, 341],
    54: [411, 422, 433, 444],
    55: [414, 423, 432, 441],
    56: [111, 212, 313, 414],
    57: [114, 213, 312, 411],
    58: [121, 222, 323, 424],
    59: [124, 223, 322, 421],
    60: [131, 232, 333, 434],
    61: [134, 233, 332, 431],
    62: [141, 242, 343, 444],
    63: [144, 243, 342, 441],
    64: [111, 221, 331, 441],
    65: [141, 231, 321, 411],
    66: [112, 222, 332, 442],
    67: [142, 232, 322, 412],
    68: [113, 223, 333, 443],
    69: [143, 233, 323, 413],
    70: [114, 224, 334, 444],
    71: [144, 234, 324, 414],
    72: [111, 222, 333, 444],
    73: [414, 323, 232, 141],
    74: [441, 332, 223, 114]
}