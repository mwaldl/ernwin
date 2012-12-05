import unittest

import time
import os
import corgy.aux.Barnacle as barn
import corgy.aux.CPDB.src.examples.BarnacleCPDB as cbarn

import numpy as np
import numpy.linalg as nl
import random as rand

import Bio.PDB as bp
import pdb, sys, copy

import corgy.builder.config as cbc
import corgy.builder.models as cbm
import corgy.builder.reconstructor as rtor
import corgy.graph.bulge_graph as cgb
import corgy.graph.graph_pdb as cgg
import corgy.utilities.debug as cud
import corgy.utilities.vector as cuv
import corgy.visual.pymol as cvp

def get_random_orientation():
    '''
    Return a random tuple (u, v, t) such that
    0 <= u <= pi
    -pi <= v <= pi
    -pi <= t <= pi
    '''

    return (rand.uniform(0, np.pi), rand.uniform(-np.pi, np.pi), rand.uniform(-np.pi, np.pi))

def get_random_translation():
    '''
    Return a random translation.
    '''

    return np.array([rand.uniform(-10, 10), rand.uniform(-10, 10), rand.uniform(-10, 10)])

class TestReconstructor(unittest.TestCase):
    def setUp(self):
        self.bg = cgb.BulgeGraph(os.path.join(cbc.Configuration.test_input_dir, "2b3j/graph", "temp.comp"))
        s = bp.PDBParser().get_structure('temp', os.path.join(cbc.Configuration.test_input_dir, "2b3j/prepare", "temp.pdb"))

        self.chain = list(s.get_chains())[0]
        self.stem = cbm.define_to_stem_model(self.chain, self.bg.defines['s0'])
    
    def test_rotate_stem(self):
        stem1 = cbm.StemModel()

        stem1.mids = self.bg.coords['s0']
        stem1.twists = self.bg.twists['s0']

        stem2 = rtor.rotate_stem(stem1, get_random_orientation())

        self.assertFalse(np.allclose(stem1.twists[0], stem2.twists[0]))
        self.assertFalse(np.allclose(stem1.twists[1], stem2.twists[1]))

        self.assertTrue(np.allclose(stem1.mids[0], stem2.mids[0]))
        self.assertTrue(np.allclose(cuv.magnitude(stem1.mids[1] - stem1.mids[0]), cuv.magnitude(stem2.mids[1] - stem2.mids[0])))

    def test_define_to_stem_model(self):
        stem1 = cbm.StemModel()
        stem1.mids = self.bg.coords['s0']
        stem1.twists = self.bg.twists['s0']

        stem2 = cbm.define_to_stem_model(self.chain, self.bg.defines['s0'])

        self.assertTrue(stem1 == stem2)

    def test_rerotate_stem(self):
        stem1 = copy.deepcopy(self.stem)

        orientation = get_random_orientation()
        stem2 = rtor.rotate_stem(stem1, orientation)

        # vector should not be rotated away from itself... duh!
        (r, u, v, t) = cgg.get_stem_orientation_parameters(stem1.vec(), stem1.twists[0], stem1.vec(), stem1.twists[0])
        self.assertTrue(np.allclose((u,v,t), (np.pi/2,0.,0.)))

        (r, u, v, t) = cgg.get_stem_orientation_parameters(stem1.vec(), stem1.twists[0], stem2.vec(), stem2.twists[0])

        # Figure out why exactly this works!!!
        orientation1 = (np.pi-u, -v, -t)
        rot_mat = cbm.get_stem_rotation_matrix(stem1, orientation1)
        
        stem3 = copy.deepcopy(stem2)
        stem3.rotate(nl.inv(rot_mat), offset=stem3.mids[0])

        (r, u, v, t) = cgg.get_stem_orientation_parameters(stem1.vec(), stem1.twists[0], stem3.vec(), stem3.twists[0])
        self.assertTrue(np.allclose((u,v,t),(np.pi/2, 0., 0.)))

    def test_splice_stem(self):
        define = self.bg.defines['s0']

        start1 = define[0]
        end1 = define[1]

        start2 = define[2]
        end2 = define[3]

        new_chain = rtor.splice_stem(self.chain, define)
        residues = bp.Selection.unfold_entities(new_chain, 'R')

        # Make sure only the residues specified are in the chain
        for res in residues:
            self.assertTrue((res.id[1] >= start1 and res.id[1] <= end1) or (res.id[1] >= start2 and res.id[1] <= end2))

        # try to access each residue to see if they are really there
        # if not, the testing framework will catch the error and report it
        for i in xrange(start1, end1+1):
            res = new_chain[i]
        
        for i in xrange(start2, end2+1):
            res = new_chain[i]

    def test_rotate_atom_stem(self):
        chain = rtor.splice_stem(self.chain, self.bg.defines['s0'])

        stem1 = cbm.define_to_stem_model(chain, self.bg.defines['s0'])
        orientation = get_random_orientation()
        stem2 = rtor.rotate_stem(stem1, orientation)

        self.assertFalse(stem1 == stem2)

        (r, u, v, t) = cgg.get_stem_orientation_parameters(stem1.vec(), stem1.twists[0], stem2.vec(), stem2.twists[0])
        rot_mat = cbm.get_stem_rotation_matrix(stem1, (np.pi-u, -v, -t))
        cbm.rotate_chain(chain, nl.inv(rot_mat), stem1.mids[0])

        stem3 = cbm.define_to_stem_model(chain, self.bg.defines['s0'])

        self.assertTrue(stem2 == stem3)

    def test_align_chain_to_stem(self):
        chain = rtor.splice_stem(self.chain, self.bg.defines['s0'])

        stem1 = cbm.define_to_stem_model(chain, self.bg.defines['s0'])
        orientation = get_random_orientation()
        translation = get_random_translation()

        stem2 = rtor.rotate_stem(stem1, orientation)
        #stem2.translate(translation)

        self.assertFalse(stem1 == stem2)
        cbm.align_chain_to_stem(chain, self.bg.defines['s0'], stem2)
        stem3 = cbm.define_to_stem_model(chain, self.bg.defines['s0'])

        self.assertTrue(stem2 == stem3)

    def test_align_chain_to_stem1(self):
        chain = rtor.splice_stem(self.chain, self.bg.defines['s0'])

        stem1 = cbm.define_to_stem_model(chain, self.bg.defines['s0'])
        orientation = get_random_orientation()
        translation = get_random_translation()

        stem2 = rtor.rotate_stem(stem1, orientation)
        stem2.translate(translation)

        self.assertFalse(stem1 == stem2)
        cbm.align_chain_to_stem(chain, self.bg.defines['s0'], stem2)
        stem3 = cbm.define_to_stem_model(chain, self.bg.defines['s0'])

        self.assertTrue(stem2 == stem3)

    def check_reconstructed_stems(self, sm, chain, stem_names):
        for stem_name in stem_names:
            stem_def = sm.stem_defs[stem_name]
            bg_stem_def = sm.bg.defines[stem_name]
        
            stem = cbm.define_to_stem_model(chain, bg_stem_def)

            '''
            print '['
            cud.pv('str(stem)')
            print '---'
            cud.pv('str(sm.stems[stem_name])')
            print ']'
            '''

            self.assertEqual(stem, sm.stems[stem_name])
    
    def check_pymol_stems(self, bg, coarse_filename, pdb_filename):
        '''
        Check whether the file output by pymol_printer is consistent
        with the output pdb file.
        '''
        found = 0
        num_stems = 0

        chain = list(bp.PDBParser().get_structure('t', pdb_filename).get_chains())[0]
        stems = []
        for d in bg.defines.keys():
            if d[0] == 's':
                stem = cbm.define_to_stem_model(chain, bg.defines[d])
                stems += [stem]

                num_stems += 1

        f = open(coarse_filename, 'r')
        cylinders = []

        for line in f:
            if line.find('CYLINDER') >= 0:
                parts = line.strip().split(', ')
                start = np.array(map(float, parts[1:4]))
                end = np.array(map(float, parts[4:7]))

                for stem in stems:
                    if ((np.allclose(stem.mids[0], start, atol=0.1) and np.allclose(stem.mids[1], end, atol=0.1)) or 
                        (np.allclose(stem.mids[1], start, atol=0.1) and np.allclose(stem.mids[0], end, atol=0.1))):
                            found += 1
                            break

        self.assertEquals(found, num_stems)

    def test_reconstruct_sampled_whole_model(self):
        '''
        Test the reconstruction of the stems of the cbm.SpatialModel.
        '''
        bgs = []
        #bgs += [self.bg]
        bgs += [cgb.BulgeGraph(os.path.join(cbc.Configuration.test_input_dir, "1gid/graph", "temp.comp"))]

        for bg in bgs:
            sm = cbm.SpatialModel(bg)
            sm.traverse_and_build()
            chain = rtor.reconstruct_stems(sm)
            rtor.replace_bases(chain, bg.seq)

            self.check_reconstructed_stems(sm, chain, sm.stem_defs.keys())
            rtor.output_chain(chain, os.path.join(cbc.Configuration.test_output_dir, 'r1.pdb'))

    def test_reconstruct_sampled_saved_model(self):
        '''
        Test the reconstruction of a model that was previously sampled and is now saved.
        '''
        bg = cgb.BulgeGraph(os.path.join(cbc.Configuration.test_input_dir, "1y26/graph", "temp.comp"))
        sm = cbm.SpatialModel(bg)
        sm.traverse_and_build()
        sm.bg.output(os.path.join(cbc.Configuration.test_output_dir, 'sampled.coords'))

        bg = cgb.BulgeGraph(os.path.join(cbc.Configuration.test_output_dir, "sampled.coords"))
        sm = cbm.SpatialModel(bg)
        sm.sample_native_stems()
        sm.create_native_stem_models()

        chain = rtor.reconstruct_stems(sm)
        self.check_reconstructed_stems(sm, chain, sm.stem_defs.keys())

    def test_reconstruct_native_whole_model(self):
        bgs = []
        #bgs += [self.bg]
        bgs += [cgb.BulgeGraph(os.path.join(cbc.Configuration.test_input_dir, "1gid/graph", "temp.comp"))]

        for bg in bgs:
            sm = cbm.SpatialModel(bg)
            sm.sample_native_stems()
            sm.create_native_stem_models()
            #sm.traverse_and_build()
            chain = rtor.reconstruct_stems(sm)

            self.check_reconstructed_stems(sm, chain, sm.stem_defs.keys())
    
    def test_twice_defined_stem(self):
        bg = cgb.BulgeGraph(os.path.join(cbc.Configuration.test_input_dir, "1gid/graph", "temp.comp"))
        sm = cbm.SpatialModel(bg)

        for d1 in bg.defines.keys():
            if d1[0] == 's':
                for d2 in bg.defines.keys():
                    if d2[0] == 's':
                        if d1 != d2 and bg.defines[d1][1] - bg.defines[d1][0] == bg.defines[d2][1] - bg.defines[d2][0]:

                            sm.traverse_and_build()
                            sm.stem_defs[d2] = sm.stem_defs[d1]
                            sm.traverse_and_build()

                            chain = rtor.reconstruct_stems(sm)
                            self.check_reconstructed_stems(sm, chain, sm.stem_defs.keys())

                            return

    def test_output_chain(self):
        bg = cgb.BulgeGraph(os.path.join(cbc.Configuration.test_input_dir, "1gid/graph", "temp.comp"))
        sm = cbm.SpatialModel(bg)

        # If we don't sample the native stems, then the coarse grain model that is created
        # from the sampled stems may not be exactly equal to the one we had before (although
        # it should be close)
        #
        # This is because the twists of the coarse grain model are created by averaging
        # the vectors from the center of the helical region to C1' atom of the nucleotides
        # at each end of the stem
        sm.sample_native_stems()
        sm.traverse_and_build()

        chain = rtor.reconstruct_stems(sm)

        self.check_reconstructed_stems(sm, chain, sm.stem_defs.keys())

        output_file = os.path.join(cbc.Configuration.test_output_dir, "output_chain")

        pymol_printer = cvp.PymolPrinter()
        pymol_printer.print_text = False
        pymol_printer.add_twists = True
        pymol_printer.add_longrange = False

        pymol_printer.coordinates_to_pymol(sm.bg)
        pymol_printer.chain_to_pymol(chain)

        # this will dump both the coarse grain representation as well as the
        # stem reconstruction
        pymol_printer.dump_pymol_file(output_file)

        chain = list(bp.PDBParser().get_structure('t', output_file + ".pdb").get_chains())[0]

        self.check_reconstructed_stems(sm, chain, sm.stem_defs.keys())
        self.check_pymol_stems(bg, output_file + ".pym", output_file + ".pdb")

    def test_reconstruct_loops(self):
        bg = cgb.BulgeGraph(os.path.join(cbc.Configuration.test_input_dir, "1y26/graph", "temp.comp"))
        sm = cbm.SpatialModel(bg)
        sm.sample_native_stems()
        sm.create_native_stem_models()

        #sm.traverse_and_build()
        chain = rtor.reconstruct_stems(sm)
        rtor.reconstruct_loops(chain, sm, samples=40, consider_contacts=True)
        '''
        rtor.reconstruct_loop(chain, sm, 'b15')
        #rtor.reconstruct_loop(chain, sm, 'b1')
        rtor.reconstruct_loop(chain, sm, 'b11')
        rtor.reconstruct_loop(chain, sm, 'b18')
        #rtor.reconstruct_loop(chain, sm, 'b16')
        #rtor.reconstruct_loop(chain, sm, 'x2', 0)
        #rtor.reconstruct_loop(chain, sm, 'x2', 1)
        '''

        #self.check_reconstructed_stems(sm, chain, sm.stem_defs.keys())
        rtor.output_chain(chain, os.path.join(cbc.Configuration.test_output_dir, 'r1.pdb'))

    def test_align_and_close_loop(self):
        bg = cgb.BulgeGraph(os.path.join(cbc.Configuration.test_input_dir, "1y26/graph", "temp.comp"))
        sm = cbm.SpatialModel(bg)
        sm.sample_native_stems()
        sm.create_native_stem_models()
        chain = rtor.reconstruct_stems(sm)

        bg = sm.bg
        ld = 'b3'
        side = 0
        seq = bg.get_flanking_sequence(ld, side)
        (a,b,i1,i2) = bg.get_flanking_handles(ld, side)

        cud.pv('(a,b,i1,i2)')
        #print "ld:", ld, "(a,b,i1,i2)", a,b,i1,i2
        #print "seq:", seq

        #model = barn.Barnacle(seq)
        model = cbarn.BarnacleCPDB(seq, 2.0)
        min_r = 100.

        best_loop_chain = None

        for i in range(20):
            model.sample()
            chain_loop = list(model.structure.get_chains())[0]
            orig_chain_loop = copy.deepcopy(chain_loop)
            (r, loop_chain) = rtor.align_and_close_loop(bg, chain, chain_loop, (a, b, i1, i2))
            cud.pv('r')


            if r < min_r:
                best_loop_chain = copy.deepcopy(loop_chain)
                min_r = r
                rtor.output_chain(loop_chain, 'r_barnacle.pdb')
                rtor.output_chain(orig_chain_loop, 'r_orig_barnacle.pdb')

        real_struct = bp.PDBParser().get_structure('temp',
                os.path.join(cbc.Configuration.test_input_dir, "1y26/prepare", "temp.pdb"))
        chain_loop = list(real_struct.get_chains())[0]
        (r, loop_chain) = rtor.align_and_close_loop(bg, chain, chain_loop, (a, b, a, b))
        cud.pv('r')
        rtor.output_chain(loop_chain, 'r_native.pdb')


    def test_reconstruct_loop(self):
        bg = cgb.BulgeGraph(os.path.join(cbc.Configuration.test_input_dir, "1y26/graph", "temp.comp"))
        sm = cbm.SpatialModel(bg)
        sm.sample_native_stems()
        sm.create_native_stem_models()

        #sm.traverse_and_build()
        chain = rtor.reconstruct_stems(sm)
        rtor.reconstruct_loop(chain, sm, 'b2', samples=40, consider_contacts=True)

        #self.check_reconstructed_stems(sm, chain, sm.stem_defs.keys())
        rtor.output_chain(chain, os.path.join(cbc.Configuration.test_output_dir, 'r1.pdb'))

    def test_get_stem_coord_array(self):
        bg = cgb.BulgeGraph(os.path.join(cbc.Configuration.test_input_dir, "1gid/graph", "temp.comp"))
        ld = 'b15'
        seq = bg.get_flanking_sequence(ld)
        (a,b,i1,i2) = bg.get_flanking_handles(ld)
        model = barn.Barnacle(seq)
        model.sample()
        chain = list(model.structure.get_chains())[0]

        (coords, indeces) = rtor.get_atom_coord_array(chain, i1, i2)
        
        for i in range(i1, i2+1):
            res = chain[i]
            self.assertTrue(np.allclose(coords[indeces[res.id[1]]], res['P'].get_vector().get_array()))

    def test_close_fragment_loop(self):
        bg = cgb.BulgeGraph(os.path.join(cbc.Configuration.test_input_dir, "1gid/graph", "temp.comp"))
        sm = cbm.SpatialModel(bg)
        sm.sample_native_stems()
        sm.create_native_stem_models()

        ld = 'b15'
        seq = bg.get_flanking_sequence(ld)
        (a,b,i1,i2) = bg.get_flanking_handles(ld)

        model = barn.Barnacle(seq)
        model.sample()
        s = model.structure

        chain_stems = rtor.reconstruct_stems(sm) 
        chain_barnacle = list(model.structure.get_chains())[0]

        rtor.align_starts(chain_stems, chain_barnacle, (a,b,i1,i2))
        distances = rtor.get_adjacent_interatom_distances(chain_barnacle, i1, i2)
        (moving, indeces) = rtor.get_atom_coord_array(chain_barnacle, i1, i2)

        r, chain_loop = rtor.close_fragment_loop(chain_stems, chain_barnacle, (a,b,i1,i2), iterations=10)

        (moving1, indeces1) = rtor.get_atom_coord_array(chain_loop, i1, i2)

        # make sure that the loop closure actually did something
        self.assertFalse(np.allclose(moving, moving1))
        distances1 = rtor.get_adjacent_interatom_distances(chain_loop, i1, i2)
        self.assertTrue(np.allclose(distances, distances1))

    def test_barnacle(self):
        model = barn.Barnacle('ACGU')
        model.sample()

    def test_get_handles(self): 
        bg = cgb.BulgeGraph(os.path.join(cbc.Configuration.test_input_dir, "1gid/graph", "temp.comp"))
        sm = cbm.SpatialModel(bg)

        sm.traverse_and_build()
        chain = rtor.reconstruct_stems(sm)

        #fr = bg.get_flanking_region('b15', 0)
        (a,b,i1,i2) = bg.get_flanking_handles('b15')

        rtor.get_alignment_vectors(chain, a, b)

    def test_pdb_rmsd1(self):
        s1 = bp.PDBParser().get_structure('t', os.path.join(cbc.Configuration.test_input_dir, '1gid/prepare/temp.pdb'))
        s2 = bp.PDBParser().get_structure('t', os.path.join(cbc.Configuration.test_input_dir, '1gid/prepare/temp_sampled.pdb'))

        c1 = list(s1.get_chains())[0]
        c2 = list(s2.get_chains())[0]

        print "rms:", rtor.pdb_rmsd(c1, c2)

    def test_pdb_rmsd2(self):
        bg = cgb.BulgeGraph(os.path.join(cbc.Configuration.test_input_dir, "1y26/graph", "temp.comp"))
        sm = cbm.SpatialModel(bg)
        sm.traverse_and_build()

        #sm.traverse_and_build()
        chain = rtor.reconstruct_stems(sm)
        rtor.replace_bases(chain, bg.seq)
        rtor.reconstruct_loops(chain, sm, samples=5)

        rtor.output_chain(chain, os.path.join(cbc.Configuration.test_output_dir, 'r1.pdb'))

        s1 = bp.PDBParser().get_structure('t', os.path.join(cbc.Configuration.test_input_dir, '1y26/prepare/temp.pdb'))
        print "rmsd:", rtor.pdb_rmsd(chain, list(s1.get_chains())[0])

    def test_replace_side_chains(self):
        bg = cgb.BulgeGraph(os.path.join(cbc.Configuration.test_input_dir, "1y26/graph", "temp.comp"))
        sm = cbm.SpatialModel(bg)
        sm.traverse_and_build()

        s1 = bp.PDBParser().get_structure('t', os.path.join(cbc.Configuration.test_input_dir, '1y26/prepare/temp.pdb'))

        reference_chain = list(s1.get_chains())[0]
        sampled_chain = rtor.reconstruct_stems(sm)
        replaced_chain = copy.deepcopy(sampled_chain)
        rtor.replace_bases(replaced_chain, bg.seq)

        anchor_atom = {'A': 'N9', 'C':'N1', 'G':'N9', 'U':'N1'}

        # check that the N1 position is the same in 
        for res1 in sampled_chain:
            res2 = replaced_chain[res1.id[1]]
            res3 = reference_chain[res1.id[1]]

            #print res1.resname, res2.resname, res3.resname

            #print res1[anchor_atom[res1.resname.strip()]].get_vector().get_array()
            #print res2[anchor_atom[res2.resname.strip()]].get_vector().get_array()

            '''
            self.assertTrue(np.allclose(res1[anchor_atom[res1.resname.strip()]].get_vector().get_array(),
                                     res2[anchor_atom[res2.resname.strip()]].get_vector().get_array())) 
            '''


            # make sure all of the atoms in the reference chain are also in the relaced chain
            side_chain_atoms = rtor.side_chain_atoms[res3.resname.strip()]

            for atom_name in side_chain_atoms:
                self.assertTrue(atom_name in res2.child_dict)

    def test_copy_chain(self):
        files = os.listdir(cbc.Configuration.stem_fragment_dir)
        pdb_file = os.path.join(cbc.Configuration.stem_fragment_dir, rand.choice(files))

        chain1 = list(bp.PDBParser().get_structure('temp', pdb_file).get_chains())[0]
        chain2 = chain1.copy()

        residues1 = bp.Selection.unfold_entities(chain1, 'R')
        residues2 = bp.Selection.unfold_entities(chain2, 'R')

        for i in range(len(residues1)):
            res1 = residues1[i]
            res2 = residues2[i]

            self.assertEqual(res1.id[1], res2.id[1])
            self.assertFalse(res1 is res2)

            chain1[res1.id[1]]
            chain2[res1.id[1]]

        atoms1 = bp.Selection.unfold_entities(chain1, 'A')
        atoms2 = bp.Selection.unfold_entities(chain2, 'A')

        for i in range(len(atoms1)):
            atom1 = atoms1[i]
            atom2 = atoms2[i]

            self.assertTrue(np.allclose(atom1.get_vector().get_array(), atom2.get_vector().get_array()))
        
        t1 = time.time()
        for i in range(50):
            copy.deepcopy(chain1)
        print "deepcopy time:", time.time() - t1

        t1 = time.time()
        for i in range(50):
            chain1.copy()
        print "chain.copy time:", time.time() - t1

        t1 = time.time()
        for i in range(50):
            chain1 = list(bp.PDBParser().get_structure('temp', pdb_file).get_chains())[0]
        print "file load time:", time.time() - t1


