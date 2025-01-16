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
