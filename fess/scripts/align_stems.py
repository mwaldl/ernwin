#!/usr/bin/python

import sys, os
import warnings
import numpy as np
import corgy.builder.stats as cbs
from optparse import OptionParser
import random
import corgy.builder.config as cbc
import corgy.builder.models as cbm
import corgy.builder.stats as cbs
import corgy.builder.reconstructor as rtor
import corgy.utilities.debug as cud
import corgy.utilities.protein as cup
import corgy.visual.pymol as cvp

import Bio.PDB as bpdb
import Bio.PDB.Chain as bpdbc

def stem_def_from_filename(filename):
    parts = filename.split('.')[0].split('_')

    stem_def = cbs.StemStat()
    stem_def.pdb_name = parts[0]
    stem_def.define = [int(parts[1]), int(parts[2]), int(parts[3]), int(parts[4])]
    stem_def.bp_length = stem_def.define[1] - stem_def.define[0]

    return stem_def

def main():
    usage = './align_stems.py [stem_length]'
    usage += 'Do diagnostics on the stem model'
    parser = OptionParser()

    parser.add_option('-i', '--iterations', dest='iterations', default=1, help="The number of times to repeat the alignment", type='int')
    parser.add_option('-l', '--length', dest='length', default=2, help="The length of the stem", type='int')
    parser.add_option('-o', '--output-pdb', dest='output_pdb', default=False, help="Output the structures to pdb files", action='store_true')
    parser.add_option('-f', '--from', dest='from_file', default=None, help='Specify a file to align from. Invalidates the -l option.', type='str')
    parser.add_option('-t', '--to', dest='to_file', default=None, help='Specify a file to align to. Invalidates the -l option.', type='str')

    (options, args) = parser.parse_args()

    if len(args) < 0:
        parser.print_help()
        sys.exit(1)

    stem_length = options.length
    if len(args) == 1:
        stem_length = int(args[0])

    if options.from_file == None or options.to_file == None:
        sss = cbs.get_stem_stats()

    rmsds = []

    for i in range(options.iterations):

        if options.from_file != None:
            filename = options.from_file
            stem_def = stem_def_from_filename(filename)
        else:
            stem_def = random.choice(sss[stem_length])
            filename = '%s_%s.pdb' % (stem_def.pdb_name, "_".join(map(str, stem_def.define)))

        #filename = '1jj2_17_18_505_506.pdb'
        #stem_def.define = [17,18,505,506]
        pdb_file = os.path.join(cbc.Configuration.stem_fragment_dir, filename)

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            try:
                chain = list(bpdb.PDBParser().get_structure('temp', pdb_file).get_chains())[0]
            except IOError as ie:
                cud.pv(ie)

        m = cbm.define_to_stem_model(chain, stem_def.define)

        new_chain = bpdbc.Chain(' ')
        #cud.pv('filename')
        try:
            if options.to_file != None:
                new_stem_def = stem_def_from_filename(options.to_file)
            else:
                new_stem_def = random.choice(sss[stem_def.bp_length])

            cbm.reconstruct_stem_core(new_stem_def, stem_def.define, new_chain, dict(), m)
        except IOError as ie:
            cud.pv('ie')

        if options.output_pdb:
            rtor.output_chain(chain, 'out1.pdb')
            rtor.output_chain(new_chain, 'out3.pdb')

        unsuperimposed_rmsd = cup.pdb_rmsd(chain, new_chain, backbone=False, superimpose=False)
        superimposed_rmsd = cup.pdb_rmsd(chain, new_chain, backbone=False, superimpose=True)

        rmsds += [[superimposed_rmsd[1], unsuperimposed_rmsd[1]]]

        #cud.pv('(superimposed_rmsd, unsuperimposed_rmsd)')

        if options.output_pdb:
            rtor.output_chain(new_chain, 'out2.pdb')
            pp = cvp.PymolPrinter()
            (p,n) = m.mids
            pp.add_stem_like_core(m.mids, m.twists, stem_def.bp_length+1, '')
            pp.stem_atoms(m.mids, m.twists, stem_def.bp_length+1)
            pp.dump_pymol_file('ss')

    means = np.mean(np.array(rmsds), axis=0) 
    print stem_length, " ".join(map(str, means)), means[1] / means[0]

if __name__ == '__main__':
    main()

