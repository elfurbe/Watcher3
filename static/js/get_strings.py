import os
import sys
import argparse

os.chdir(os.path.dirname(os.path.realpath(__file__)))

parser = argparse.ArgumentParser(description='')
parser.add_argument('-n', help='Language name.', type=str)
parser.add_argument('-o', help='Output file name.', type=str)
parser.add_argument('-v', help='Verbose output.', action='store_true')
args = parser.parse_args()

if not args.n:
    print('Usage:')
    print('get_strings.py -n language_name [-o output_file.js] [-v]')
    sys.exit(1)
name = args.n

if args.o:
    output = args.o
else:
    output = f'js_strings_{name}.js'

verbose = True if args.v else False

print(f'Writing to output file: {output}')

scripts = []
strings = {}

for root, dirs, files in os.walk('.'):
    for file in files:
        if root.endswith('lib'):
            continue
        if file.endswith('.js'):
            scripts.append(os.path.join(root, file))

for script in scripts:
    if verbose:
        print(f'Parsing {script}')

    with open(script) as f:
        t = f.read()
        t = t.split('_("')[1:]
        if len(t) == 0:
            continue
        for i in t:
            string = i.split('")')[0]
            if verbose:
                print(f'Found string: "{string}"')
            if string not in strings.keys():
                strings[string] = [os.path.basename(script)]
            else:
                strings[string].append(os.path.basename(script))

with open(output, 'w+') as f:
    f.write(('"{}" : {{\n').format(name))
    for string, files in strings.items():
        ln = '\t\t"{}": "", \t//{}\n'.format(string, ', '.join(files))
        f.write(ln)

    for i in ('Waiting', 'Wanted', 'Found', 'Snatched', 'Finished', 'Bad', 'Available'):
        ln = f'\t\t"{i}": "",\n'
        f.write(ln)

    f.write('\t\t}')
