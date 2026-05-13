import os
import shutil

sortedFiles = []
for file in sorted(os.listdir('../assets')):
    try:
        if not file.startswith('.'):
            value = int(file.split('_')[0])
            print(value)
            if value < 10:
                newfile = '../assets/' + file
            else:
                newfile = '../assets/' + file
            sortedFiles.append("require('{0}')".format(newfile))
        else:
            pass
    except:
        pass

for file in sorted(sortedFiles):
    print('{0},'.format(file))
