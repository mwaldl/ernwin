import multiprocessing as mp
import warnings

import itertools as it
import fess.builder.models as models
import os.path as op

import forgi.threedee.model.coarse_grain as ftmc
import forgi.threedee.utilities.pdb as ftup
import forgi.threedee.utilities.average_atom_positions as ftua
import forgi.threedee.utilities.graph_pdb as ftug
import forgi.threedee.utilities.vector as cuv
ftuv = cuv
import forgi.utilities.debug as fud

import fess.builder.ccd as cbc

import forgi.threedee.model.similarity as brmsd
import forgi.graph.bulge_graph as fgb
#import borgy.aux.Barnacle as barn
#import fess.aux.CPDB.BarnacleCPDB as barn

import Bio.PDB as bpdb
import Bio.PDB.Atom as bpdba
import Bio.PDB.Residue as bpdbr
import Bio.PDB.Chain as bpdbc
import Bio.PDB.Model as bpdbm
import Bio.PDB.Structure as bpdbs

import scipy.stats as ss

from scipy.stats import norm, poisson

import os, math, sys
import fess.builder.config as conf
import copy, time
import random as rand

import logging
log=logging.getLogger(__name__)

import numpy as np

def get_measurement_vectors1(ress, r1, r2):
    return( ress[r2]["C4'"].get_vector().get_array(),
            ress[r2]["C3'"].get_vector().get_array(),
            ress[r2]["O3'"].get_vector().get_array())

def get_measurement_vectors2(ress, r1, r2):
    return( ress[r2]["O4'"].get_vector().get_array(),
            ress[r2]["C1'"].get_vector().get_array(),
            ress[r2]["C2'"].get_vector().get_array())

def rotate_stem(stem, (u, v, t)):
    '''
    Rotate a particular stem.
    '''
    stem2 = stem.copy()
    rot_mat4 = models.get_stem_rotation_matrix(stem, (u,v,t))
    stem2.rotate(rot_mat4, offset=stem.mids[0])

    return stem2

def reconstruct_stems(sm):
    '''
    Reconstruct the stems around a Spatial Model.

    @param sm: Spatial Model
    '''

    new_chains = {}
    for stem_name in sm.elem_defs.keys():
        if stem_name[0]!="s": continue
        models.reconstruct_stem(sm, stem_name, new_chains)
        '''
        # The following code is just for debugging/logging.
        # Useless unless searching for a particular bug
        log.debug("+++ADDED STEM %s +++", stem_name)
        for chain in new_chains.values():
            for res in chain.get_residues():
                log.debug(res.child_dict["C1'"].coord)
        '''
    return new_chains

def output_chain(chain, filename, fr=None, to=None):
    '''
    Dump a chain to an output file. Remove the hydrogen atoms.

    @param chain: The Bio.PDB.Chain to dump.
    @param filename: The place to dump it.
    '''
    class HSelect(bpdb.Select):
        def accept_atom(self, atom):
            if atom.name.find('H') >= 0:
                return False
            else:
                return True

    m = bpdbm.Model(' ')
    s = bpdbs.Structure(' ')

    m.add(chain)
    s.add(m)

    io = bpdb.PDBIO()
    io.set_structure(s)
    io.save(filename, HSelect())

def splice_stem(chain, define):
    '''
    Extract just the defined stem from the chain and return it as
    a new chain.

    @param chain: A Bio.PDB.Chain containing the stem in define
    @param define: The BulgeGraph stem define
    '''
    start1 = define[0]
    end1 = define[1]

    start2 = define[2]
    end2 = define[3]

    new_chain = bpdbc.Chain(' ')

    for i in xrange(start1, end1+1):
        #new_chain.insert(i, chain[i])
        new_chain.add(chain[i])

    for i in xrange(start2, end2+1):
        new_chain.add(chain[i])

    '''
    m = Model(' ')
    s = Structure(' ')
    m.add(new_chain)
    s.add(m)

    io=PDBIO()
    io.set_structure(s)
    io.save('temp.pdb')
    '''

    return new_chain

def print_alignment_pymol_file(handles):
    output_str = """
select bb, /s2///%d/O4' | /s2///%d/C1' | /s2///%d/C1'
show sticks, bb
color red, bb

select bb, /s2///%d/O4' | /s2///%d/C1'| /s2///%d/C2'
show sticks, bb
color red, bb

select bb, s1///%d/O4' | s1///%d/C1' | s1///%d/C2'
show sticks, bb
color green, bb

select bb, s1///%d/O4' | s1///%d/C1' | s1///%d/C2'
show sticks, bb
color green, bb

show cartoon, all
""" % (handles[2], handles[2], handles[2],
        handles[3], handles[3], handles[3],
        handles[0], handles[0], handles[0],
        handles[1], handles[1], handles[1])
    output_file = os.path.join(conf.Configuration.test_output_dir, "align.pml")
    f = open(output_file, 'w')
    f.write(output_str)
    f.flush()
    f.close()

def get_flanking_stem_vres_distance(bg, ld):
    '''
    Get the distance between the two virtual residues adjacent
    to this bulge region.

    @param bg: The BulgeGraph data structure
    @param ld: The name of the linking bulge
    '''

    if len(bg.edges[ld]) == 2:
        connecting_stems = list(bg.edges[ld])

        (s1b, s1e) = bg.get_sides(connecting_stems[0], ld)
        (s2b, s2e) = bg.get_sides(connecting_stems[1], ld)

        if s1b == 1:
            (vr1_p, vr1_v, vr1_v_l, vr1_v_r) = ftug.virtual_res_3d_pos(bg, connecting_stems[0], bg.stem_length(connecting_stems[0]) - 1)
        else:
            (vr1_p, vr1_v, vr1_v_l, vr1_v_r) = ftug.virtual_res_3d_pos(bg, connecting_stems[0], 0)

        if s2b == 1:
            (vr2_p, vr2_v, vr2_v_l, vr2_v_r) = ftug.virtual_res_3d_pos(bg, connecting_stems[1], bg.stem_length(connecting_stems[1]) - 1)
        else:
            (vr2_p, vr2_v, vr2_v_l, vr2_v_r) = ftug.virtual_res_3d_pos(bg, connecting_stems[1], 0)

        dist2 = cuv.vec_distance((vr1_p + 7 * vr1_v), (vr2_p + 7. * vr2_v))
    else:
        dist2 = 0.

    return dist2

a_5_names = ["P", "OP1", "OP2", "P", "O5'", "C5'", "C4'", "O4'", "O2'"]
a_3_names = ["C1'", "C2'", "C3'", "O3'"]

backbone_atoms = ['P', "O5'", "C5'", "C4'", "C3'", "O3'"]

side_chain_atoms = dict()

side_chain_atoms['U'] = ['N1', 'C2', 'O2', 'N3', 'C4', 'O4', 'C5', 'C6']
side_chain_atoms['C'] = ['N1', 'C2', 'O2', 'N3', 'C4', 'N4', 'C5', 'C6']

side_chain_atoms['A'] = ['N1', 'C2', 'N3', 'C4', 'C5', 'C6', 'N6', 'N7', 'C8', 'N9']
side_chain_atoms['G'] = ['N1', 'C2', 'N2', 'N3', 'C4', 'C5', 'C6', 'O6', 'N7', 'C8', 'N9']
side_chain_atoms['rU'] = ['N1', 'C2', 'O2', 'N3', 'C4', 'O4', 'C5', 'C6']
side_chain_atoms['rC'] = ['N1', 'C2', 'O2', 'N3', 'C4', 'N4', 'C5', 'C6']

side_chain_atoms['rA'] = ['N1', 'C2', 'N3', 'C4', 'C5', 'C6', 'N6', 'N7', 'C8', 'N9']
side_chain_atoms['rG'] = ['N1', 'C2', 'N2', 'N3', 'C4', 'C5', 'C6', 'O6', 'N7', 'C8', 'N9']

a_names = dict()
a_names['U'] = a_5_names + side_chain_atoms['U'] + a_3_names
a_names['C'] = a_5_names + side_chain_atoms['C'] + a_3_names

a_names['A'] = a_5_names + side_chain_atoms['A'] + a_3_names
a_names['G'] = a_5_names + side_chain_atoms['G'] + a_3_names

a_names['rU'] = a_5_names + side_chain_atoms['U'] + a_3_names
a_names['rC'] = a_5_names + side_chain_atoms['C'] + a_3_names

a_names['rA'] = a_5_names + side_chain_atoms['A'] + a_3_names
a_names['rG'] = a_5_names + side_chain_atoms['G'] + a_3_names

def get_alignment_vectors(ress, r1, r2):
    '''
    return( ress[r1]["C4'"].get_vector().get_array(),
            ress[r1]["C3'"].get_vector().get_array(),
            ress[r1]["O3'"].get_vector().get_array())
    '''
    vec = []
    for aname in backbone_atoms:
        try:
            r1_v = [ress[r1][aname].get_vector().get_array()]
            r2_v = [ress[r2][aname].get_vector().get_array()]

            vec += r1_v
            vec += r2_v
        except KeyError as ke:
            raise ke

    return vec

def get_measurement_vectors(ress, r1, r2):
    return( ress[r2]["C2'"].get_vector().get_array(),
            ress[r2]["C3'"].get_vector().get_array(),
            ress[r2]["O3'"].get_vector().get_array())

def get_atom_coord_array(chain, start_res, end_res):
    '''
    Return an array of the coordinates of all the atoms in the chain,
    arranged in the following order:

    P, O5', C5', C4', O4', C3', C1', C2', base_atoms, O3'

    @param chain: The chain from which to get the coordinates.
    @param start_res: The number of the starting residue
    @param end_res: The number of the ending residue
    @return (coords, indeces): coords - A 3 x n matrix where n is the number of atoms in the matrix
        indeces - The indeces into this array, which indicate the position of the P atoms of each residue

    '''

    coords = []
    indeces = dict()
    count = 0

    rids = [r.id for r in chain]
    start_index = rids.index(start_res)
    end_index = rids.index(end_res)

    for i in range(start_index, end_index+1):
        res = chain[rids[i]]
        indeces[res.id] = count

        for aname in a_names[res.resname.strip()]:
            try:
                coords += [res[aname].get_vector().get_array()]
            except KeyError:
                #alternate name for the OP1 atoms
                if aname == 'OP1':
                    coords += [res['O1P'].get_vector().get_array()]
                elif aname == 'OP2':
                    coords += [res['O2P'].get_vector().get_array()]
                else:
                    raise

            count += 1
            continue


    return (coords, indeces, rids)

def get_atom_name_array(chain, start_res, end_res):
    '''
    Return an array of the coordinates of all the atoms in the chain,
    arranged in the following order:

    P, O5', C5', C4', O4', C3', C1', C2', base_atoms, O3'

    @param chain: The chain from which to get the coordinates.
    @param start_res: The number of the starting residue
    @param end_res: The number of the ending residue
    @return (coords, indeces): coords - A 3 x n matrix where n is the number of atoms in the matrix
        indeces - The indeces into this array, which indicate the position of the P atoms of each residue

    '''

    coords = []
    indeces = dict()
    count = 0

    for i in range(start_res, end_res+2):
        res = chain[i]
        indeces[res.id[1]] = count
        for aname in a_names[res.resname.strip()]:
            coords += ['%d%s' % (i, aname)]
            count += 1
            continue


    return (coords, indeces)

def set_atom_coord_array(chain, coords, rids):
    '''
    Set the coordinates of the atoms in the chain to the ones in coords.

    P, O5', C5', C4', O4', C3', C1', C2', base_atoms, O3'

    @param chain: The chain which will recieve coordinates
    @param coords: The coordinates to be entered
    @param start_res: The number of the starting residue
    @param end_res: The number of the ending residue
    @return (coords, indeces): coords - A 3 x n matrix where n is the number of atoms in the matrix
        indeces - The indeces into this array, which indicate the position of the P atoms of each residue

    '''
    count = 0

    for r in rids:
        res = chain[r]
        for aname in a_names[res.resname.strip()]:
            #chain[i][aname].coord = bpdb.Vector(coords[count])
            try:
                chain[r][aname].coord = coords[count]
            except KeyError:
                if aname == 'OP1':
                    chain[r]['O1P'].coord = coords[count]
                elif aname == 'OP2':
                    chain[r]['O2P'].coord = coords[count]
                else:
                    raise
            count += 1

    return chain

def align_all(chains_fragment, chains_scaffold, nucleotides):
    """
    Translate and rotate a chains_fragment to optimally match
    the scaffold at the specified nucleotides.

    :param chains_scaffold: A dict {chain_id:chain} that contains the stems
                            where the fragment should be inserted.
    :param chains_fragment: A dict {chain_id:chain} that contains the fragment
                            to be inserted (with adjacent nucleotides)
    :param nucleotides: A list of tuples (seq_id_fragment, seq_id_scaffold)
                        The two seq_ids in each tuple spould refer to the same
                        nucleotide (the fragments adjacent nts), once in the
                        fragment, once in the scaffold.
    """
    # The point-clouds that will be aligned.
    points_fragment = []
    points_scaffold = []
    log.info("nts %s", nucleotides)
    for res_frag, res_scaf in nucleotides:
        #log.debug("res_frag %s res_scaf %s", res_frag, res_scaf)
        residue_frag = chains_fragment[res_frag.chain][res_frag.resid]
        residue_scaf = chains_scaffold[res_scaf.chain][res_scaf.resid]
        for atom_label in ["C4'", "C3'", "O3'"]:
            points_fragment.append(residue_frag[atom_label].coord)
            points_scaffold.append(residue_scaf[atom_label].coord)
    points_fragment = np.asarray(points_fragment)
    points_scaffold = np.asarray(points_scaffold)

    centroid_frag = ftuv.get_vector_centroid(points_fragment)
    centroid_scaf = ftuv.get_vector_centroid(points_scaffold)

    points_fragment -= centroid_frag
    points_scaffold -= centroid_scaf

    sup = brmsd.optimal_superposition(points_fragment, points_scaffold)

    for chain in chains_fragment.values():
        for atom in chain.get_atoms():
            atom.transform(np.eye(3,3), -centroid_frag)
            atom.transform(sup, centroid_scaf)


def align_starts(chains_stems, chains_loop, handles, end=0, reverse=False):
    '''
    Align the sugar rings of one part of the stem structure to one part
    of the loop structure.

    @param chains_stems: The chains containing the stems
    @param chains_loop: The chains containing the sampled loop
    @param handles: The indexes into the stem and loop for the overlapping residues.
    '''

    v1 = []
    v2 = []

    for handle in handles:
        if end == 2:
            assert len(handles)==1
            if reverse:
                # used for aligning the 5' region, the back of which needs
                # to be aligned to the beginning of the stem
                residue1 = chains_stems[handle[1].chain][handle[1].resid]
                residue2 = chains_loop[handle[3].chain][handle[3].resid]
            else:
                residue1 = chains_stems[handle[0].chain][handle[0].resid]
                residue2 = chains_loop[handle[2].chain][handle[2].resid]
            v1 = (residue1["C4'"].get_vector().get_array(),
                  residue1["C3'"].get_vector().get_array(),
                  residue1["O3'"].get_vector().get_array())
            v2 = (residue2["C4'"].get_vector().get_array(),
                  residue2["C3'"].get_vector().get_array(),
                  residue2["O3'"].get_vector().get_array())

        else:
            assert False, "TODO"
            # BT: This will be used again in the future, but I am
            # currently onlty porting the case of end==2 to the new version with
            # of dicts of chains.
            if end == 0:
                v1 += get_alignment_vectors(chains_stems, handle[0], handle[1])
                v2 += get_alignment_vectors(chains_loop, handle[2], handle[3])

            else:
                v1 += get_measurement_vectors(chains_stems, handle[0], handle[1])
                v2 += get_measurement_vectors(chains_loop, handle[2], handle[3])

    v1_centroid = cuv.get_vector_centroid(v1)
    v2_centroid = cuv.get_vector_centroid(v2)

    v1_t = v1 - v1_centroid
    v2_t = v2 - v2_centroid

    sup = brmsd.optimal_superposition(v2_t, v1_t)

    for chain in chains_loop.values():
        for atom in bpdb.Selection.unfold_entities(chain, 'A'):
            atom.transform(np.eye(3,3), -v2_centroid)
            atom.transform(sup, v1_centroid)

def get_adjacent_interatom_distances(chain, start_res, end_res):
    adjacent_atoms = dict()
    adjacent_atoms['P'] = ["O5'", 'OP1', 'OP2']
    adjacent_atoms["O5'"] = ["C5'"]
    adjacent_atoms["C5'"] = ["C4'"]
    adjacent_atoms["C4'"] = ["O4'", "C3'"]
    adjacent_atoms["O4'"] = ["C1'"]
    adjacent_atoms["C1'"] = ["C2'"]
    adjacent_atoms["C2'"] = ["C3'", "O2'"]
    adjacent_atoms["C3'"] = ["O3'"]

    distances = []
    ress = list(chain.get_list())
    for i in range(start_res, end_res+1):
        res = chain[i]
        for key in adjacent_atoms.keys():
            for value in adjacent_atoms[key]:
                distances += [res[key] - res[value]]

    for i in range(start_res, end_res+1):
        distances += [ress[i]['P'] - ress[i-1]["O3'"]]

    return distances


def get_adjacent_interatom_names(chain, start_res, end_res):
    adjacent_atoms = dict()
    adjacent_atoms['P'] = ["O5'", 'OP1', 'OP2']
    adjacent_atoms["O5'"] = ["C5'"]
    adjacent_atoms["C5'"] = ["C4'"]
    adjacent_atoms["C4'"] = ["O4'", "C3'"]
    adjacent_atoms["O4'"] = ["C1'"]
    adjacent_atoms["C1'"] = ["C2'"]
    adjacent_atoms["C2'"] = ["C3'", "O2'"]
    adjacent_atoms["C3'"] = ["O3'"]

    distances = []
    ress = list(chain.get_list())
    for i in range(start_res, end_res+1):
        for key in adjacent_atoms.keys():
            for value in adjacent_atoms[key]:
                distances += [str(key) + "-" + str(value)]

    for i in range(start_res, end_res+1):
        distances += ['%dP-O3' % (i)]

    return distances

def add_residue_to_rosetta_chain(chain, residue):
    '''
    Add a residue and rename all of it's atoms to the Rosetta convention.

    C1' -> C1'

    @param chain: The chain to add to
    @param residue: The residue to be added
    '''
    removed_atoms = []

    for atom in residue.get_list():
        # H-atoms are unnecessary at this moment
        if atom.name.find('H') < 0:
            removed_atoms += [atom]

        residue.detach_child(atom.id)

        atom.name = atom.name.replace("\'", "'")
        atom.id = atom.name

    for atom in removed_atoms:
        residue.add(atom)

    detached_residues = []
    if residue.id[1] in chain:
        detached_residues += [chain[residue.id[1]]]
        #chain.detach_child(chain[residue.id[1]].id)
        chain.detach_child((' ', residue.id[1], ' '))

    chain.add(residue)

    # there should only be one element in the
    # detached residues array
    return detached_residues

def add_loop_chain(chain, loop_chain, handles, length):
    '''
    Add all of the residues in loop_chain to chain.

    @param chain: The target chain to which the residues will be added.
    @param loop_chain: The source of the loop residues.
    @param handles: The indeces of the adjacent stem regions as well as the indeces into the loop
        chain which define which section is actually the loop and which is the additional linker
        region.
    '''
    # detach the residues of the helix which are adjacent to the loop
    #r1_id = chain[handles[0]].id
    #chain.detach_child(r1_id)
    #replace them with the residues of the loop
    #loop_chain[handles[2]].id = r1_id
    #add_residue_to_rosetta_chain(chain, loop_chain[handles[2]])

    if handles[1] != length:
        r2_id = chain[handles[1]].id
        chain.detach_child(r2_id)
        loop_chain[handles[3]].id = (' ', handles[1], ' ')
        add_residue_to_rosetta_chain(chain, loop_chain[handles[3]])
    else:
        loop_chain[handles[3]].id = (' ', handles[1], ' ')
        add_residue_to_rosetta_chain(chain, loop_chain[handles[3]])

    # We won't replace the last residue
    # ... or will we?
    counter = 1
    for i in range(handles[2]+1, handles[3]+1):
        loop_chain[i].id = (' ', handles[0] + counter, ' ')
        add_residue_to_rosetta_chain(chain, loop_chain[i])
        counter += 1

def get_initial_measurement_distance(chain_stems, chain_loop, handles):
    '''
    Calculate the rmsd between the measurement vectors after aligning
    the starts.

    @param chain_stems: The PDB coordinates of the chain with the stem.
    @param chain_loop: The PDB coordinates of the sampled loop.
    @param iterations: The number of iterations to use for the CCD loop closure.
    '''
    align_starts(chain_stems, chain_loop, handles)
    c1_target = []
    c1_sampled = []

    for i in range(2):
        target = np.array(get_measurement_vectors(chain_stems, handles[0], handles[1]))
        sampled = np.array(get_measurement_vectors(chain_loop, handles[2], handles[3]))
        '''
        for a in backbone_atoms:
            c1_target += [cuv.magnitude(
                chain_stems[handles[0] - i][a] - chain_stems[handles[1] + i][a])]
            c1_sampled += [cuv.magnitude(
                chain_loop[handles[2] - i][a] - chain_loop[handles[3] + i][a])]

    c1_target = np.array(c1_target)
    c1_sampled = np.array(c1_sampled)
        '''
    #return cbc.calc_rmsd(np.array(c1_target), np.array(c1_sampled))
    #return math.sqrt(sum([c ** 2 for c in c1_sampled - c1_target]))
    distances = [cuv.magnitude((sampled - target)[i]) for i in range(len(sampled))]
    rmsd = cuv.vector_set_rmsd(sampled, target)
    #dist = math.sqrt(sum([cuv.magnitude((sampled - target)[i]) ** 2 for i in range(len(sampled))]))
    return rmsd
    #return cuv.magnitude(sampled - target)

def close_fragment_loop(chain_stems, chain_loop, handles, iterations=5000, move_all_angles=True, move_front_angle=True, no_close=False):
    '''
    Align the chain_loop so that it stretches from the end of one stem to the
    start of the other.

    @param chain_stems: The PDB coordinates of the chain with the stem.
    @param chain_loop: The PDB coordinates of the sampled loop.
    @param iterations: The number of iterations to use for the CCD loop closure.
    '''

    #align_starts(chain_stems, chain_loop, handles)
    e = np.eye(3,3)

    for handle in handles:
        (moving, indeces, rids) = get_atom_coord_array(chain_loop, handle[2], handle[3])
        fixed = np.array(get_measurement_vectors(chain_stems, handle[0], handle[1]))

        start_res = handle[2]
        end_res = handle[3]

        #start_index = indeces[handle[2]+1]
        end_index = len(moving)

        if no_close:
            rmsd = cbc.calc_rmsd(moving[end_index-3:end_index], fixed)
            return rmsd, chain_loop

        points = []
        #points += [indeces[handle[2]+1]]

        #points += indeces[handle[2]+1] #O3' -> P bond
        if move_all_angles:
            angle_to_move = range(1, len(rids)) #range(handle[2]+1, handle[3]+1)
        else:
            angle_to_move = [1, len(rids)-1] #[handle[2]+1, handle[3]]

        for i in angle_to_move:
            si = indeces[rids[i]]

            #
            if move_front_angle:
                points += [si]
            points += [si+4, si+5, si+6]

        rot_mat = np.eye(3,3)

        '''
        distances = get_adjacent_interatom_distances(chain_loop, handle[2], handle[3])
        names = get_adjacent_interatom_names(chain_loop, handle[2], handle[3])
        '''
        moving = np.array(moving)
        points = np.array(points)

        import fess.aux.ccd.cytvec as cv

        cv.ccd_cython(moving, fixed, points, end_index-3, iterations)
        rmsd = cbc.calc_rmsd(moving[end_index-3:end_index], fixed)


        chain_loop = set_atom_coord_array(chain_loop, moving, rids)
        '''
        assert(not np.allclose(moving_orig, moving))

        (moving_new, indeces) = get_atom_coord_array(chain_loop, handles[2], handles[3])

        assert(not np.allclose(moving_orig, moving_new))

        distances2 = get_adjacent_interatom_distances(chain_loop, handles[2], handles[3])

        assert(np.allclose(distances, distances2))
        '''

    return (rmsd, chain_loop)

def align_and_close_loop(cg_to, chains, chains_loop, handles, move_all_angles=True, move_front_angle=True, no_close=False):
    '''
    Align chain_loop to the scaffold present in chain.

    This means that nt i1 in chain_loop will be aligned
    to nt a, and nt i2 will attempt to be aligned to nt b.

    :param cg_to: The CoarseGrainRNA that is being reconstructed to a pdb.
    :param chains: A dict { chainid : chain }. The scaffold containing the stems
    :param chains_loop: A dict { chainid : chain }. The fragment for the loop region

    :param handles: A (a,b,i1,i2), the handles indicating which nucleotides
                       will be aligned

    :return: (r, loop_chain), where r is the rmsd of the closed loop
            and loop_chain is the closed loop
    '''
    loop_atoms = []
    for chain in chains_loop:
        loop_atoms += chain.get_atoms()

    ns = bpdb.NeighborSearch(loop_atoms)
    contacts1 = len(ns.search_all(0.8))

    if handles[0] == 0 or handles[0]-1 in cg_to.backbone_breaks_after:
        align_starts(chain, chain_loop, handles[0], end=1)
        loop_chain = chain_loop
        r = 0.000
    elif handles[1] == seq_len or handles[1] in cg_to.backbone_breaks_after:
        align_starts(chain, chain_loop, handles[0], end=0)
        loop_chain = chain_loop
        r = 0.000
    else:
        r, loop_chain = close_fragment_loop(chains, chains_loop, handles, iterations=10000, move_all_angles=move_all_angles, move_front_angle=move_front_angle, no_close=no_close)

    return (r, loop_chain)

def build_loop(stem_chain, loop_seq, (a,b,i1,i2), seq_len, iterations, consider_contacts=False, consider_starting_pos = True):
    '''
    Build a loop.

    The alignment vectors of the nucleotides a and b in stem_chain
    should align to the alignment vectors of nucleotides i1 and i2
    of the sequence sampled by loop_seq.

    @param stem_chain: A chain containing the assembled stems.
    @param loop_seq: The sequence of the loop region including the
                     adjacent stem segments
    @param (a,b,i1,i2): The numbers of the nucleotides defining
                     where the loop starts in the whole sequence (a and b)
                     and within the loop sequence (i1 and i2)
    @param seq_len: The length of the entire sequence (including the stems)
    @param iterations: The number of MCMC iterations to run
    @param consider_contacts: The into account the contact between the loop and other portions
                              of the structure

    @return: A Bio.PDB.Chain structure containing the best sampled loop.
    '''
    import fess.aux.CPDB.BarnacleCPDB as barn

    if consider_contacts:
        model = barn.BarnacleCPDB(loop_seq, 1.9)
    else:
        model = barn.BarnacleCPDB(loop_seq, 0.)

    best_loop_chain = None
    min_energy = (1000000., 100000.)
    prev_energy = min_energy
    handles = (a,b,i1,i2)

    for i in range(iterations):
        sample_len = ss.poisson.rvs(2)
        while sample_len > (len(loop_seq) - 1):
            sample_len = ss.poisson.rvs(2)

        start = rand.randint(0, len(loop_seq) - sample_len)
        end = rand.randint(start + sample_len, len(loop_seq))

        model.sample()
        chain_loop = list(model.structure.get_chains())[0]
        chain_unclosed_loop = chain_loop.copy()

        if handles[0] != 0 and handles[1] != seq_len:
            align_starts(stem_chain, chain_unclosed_loop, [(a,b,i1,i2)], end=2)

        loop_chain = chain_unclosed_loop.copy()
        (r, loop_chain) = align_and_close_loop(seq_len, stem_chain, loop_chain, [(a, b, i1, i2)], no_close=False)

        if handles[0] == 0 or handles[1] == seq_len:
            r_start = 0.
        else:
            '''
            r_start = cuv.magnitude(loop_chain[handles[3]]['P'] -
                                     chain_unclosed_loop[handles[3]]['P'])
            '''
            r_start = cuv.magnitude(loop_chain[handles[2]]['P'] -
                                     chain_unclosed_loop[handles[3]]['P'])


        orig_loop_chain = loop_chain.copy()

        all_chain = stem_chain.copy()
        ftup.trim_chain(loop_chain, i1, i2+1)
        add_loop_chain(all_chain, loop_chain, (a,b,i1,i2), seq_len)

        if consider_contacts:
            contacts2 = ftup.num_noncovalent_clashes(all_chain)
        else:
            contacts2 = 0.

        sys.stderr.write('.')
        sys.stderr.flush()

        if consider_starting_pos:
            energy = (contacts2, r_start)
        else:
            energy = (contacts2, r)

        if energy > prev_energy:
            model.undo()

        prev_energy = energy
        if energy < min_energy:
            min_energy = energy
            min_r = r
            best_loop_chain = orig_loop_chain.copy()
        '''
        if min_contacts < (0, .1):
            break
        '''

        #trim_chain(loop_chain, i1, i2)

    sys.stderr.write(str(min_energy))
    return (best_loop_chain, min_r)

def reconstruct_loop(chains, sm, ld, side=0, samples=40, consider_contacts=True, consider_starting_pos=True):
    '''
    Reconstruct a particular loop.

    The chain should already have the stems reconstructed.

    :param chains: A dict chainid : Bio.PDB.Chain.
    :param sm: A SpatialModel structure
    :param ld: The name of the loop
    '''
    bg = sm.bg
    seq = bg.get_flanking_sequence(ld, side)
    (a,b,i1,i2) = bg.get_flanking_handles(ld, side)
    if a == 0 and b == 1:
        # the loop is just a placeholder and doesn't
        # have a length.

        # This should be taken care of in a more elegant
        # manner, but it'll have to wait until it causes
        # a problem
        return None

    # get some diagnostic information
    bl = abs(bg.defines[ld][side * 2 + 1] - bg.defines[ld][side * 2 + 0])
    dist = cuv.vec_distance(bg.coords[ld][1], bg.coords[ld][0])
    dist2 = get_flanking_stem_vres_distance(bg, ld)

    sys.stderr.write("reconstructing %s ([%d], %d, %.2f, %.2f):" % (ld, len(bg.edges[ld]), bl, dist, dist2))

    (best_loop_chain, min_r) = build_loop(chains, seq, (a,b,i1,i2), bg.seq_length, samples, consider_contacts, consider_starting_pos)

    print_alignment_pymol_file((a,b,i1,i2))

    ftup.trim_chain(best_loop_chain, i1, i2+1)
    sys.stderr.write('\n')

    add_loop_chain(chains, best_loop_chain, (a,b,i1,i2), bg.seq_length)

    return ((a,b,i1,i2), best_loop_chain, min_r)


    #sys.stderr.flush()

from multiprocessing import Process, Pipe
from itertools import izip

def spawn(f):
    def fun(pipe,x):
        pipe.send(f(*x))
        pipe.close()
    return fun

def parmap(f,X):
    pipe=[Pipe() for x in X]
    proc=[Process(target=spawn(f),args=(c,x)) for x,(p,c) in izip(X,pipe)]
    [p.start() for p in proc]
    [p.join() for p in proc]
    return [p.recv() for (p,c) in pipe]

def reconstruct_loops(chains, sm, samples=40, consider_contacts=False):
    '''
    Reconstruct the loops of a chain.

    All of the stems should already be reconstructed in chain.

    :param chain: A dict chain-id: Bio.PDB.Chain chain.
    :param sm: The SpatialModel from which to reconstruct the loops.
    '''
    args = []
    for d in sm.bg.defines.keys():
        if d[0] != 's':
            if d[0] == "i":
                args += [(chains, sm, d, 0, samples, consider_contacts)]
                args += [(chains, sm, d, 1, samples, consider_contacts)]
            else:
                args += [(chains, sm, d, 0, samples, consider_contacts)]

    #pool = mp.Pool(processes=4)
    #r = parmap(reconstruct_loop, args)
    r = [reconstruct_loop(*arg) for arg in args]
    r = [x for x in r if x is not None]

    for ((a,b,i1,i2), best_loop_chain, min_r) in r:
        add_loop_chain(chains, best_loop_chain, (a,b,i1,i2), sm.bg.length)

def _compare_cg_chains_partial(cg, chains):
    """
    :param cg: The CoarseGrainRNA
    :param chains: A dict {chain_id: Chain}
    """
    for chain in chains.values():
        for res in chain.get_residues():
            resid = fgb.RESID(chain.id, res.id)
            pdb_coords = res["C1'"].coord
            cg_coords = cg.virtual_atoms(cg.seq_ids.index(resid)+1)["C1'"]
            if ftuv.magnitude(pdb_coords-cg_coords)>2:
                log.error("Residue %s, C1' coords %s do not "
                          "match the cg-coords (virtual atom) %s by %f", resid, pdb_coords,
                          cg_coords, ftuv.magnitude(pdb_coords-cg_coords))

def reconstruct(sm):
    '''
    Re-construct a full-atom model from a coarse-grain model.

    @param bg: The BulgeGraph
    @return: A Bio.PDB.Chain chain
    '''
    chains = reconstruct_stems(sm)
    _compare_cg_chains_partial(sm.bg, chains)
    ftup.output_multiple_chains(chains.values(), "reconstr_stems.pdb")

    '''# Some validation. Useless unless searching for a bug
    chains_in_file = ftup.get_all_chains("reconstr_stems.pdb")
    chains_in_file = { c.id:c for c in chains_in_file }
    for c in chains:
        r = ftup.pdb_rmsd(chains[c], chains_in_file[c], superimpose = False)[1]
        assert r<0.001, "r={} for chain {}".format(r, c)
    '''
    for l in sm.bg.defines:
        if l[0]=="s": continue
        reconstruct_with_fragment(chains, sm, l)
    ftup.output_multiple_chains(chains.values(), "reconstr_all.pdb")
    return chains

def replace_base(res_dir, res_ref):
    '''
    Orient res_ref so that it points in the same direction
    as res_dir.

    @param res_dir: The residue indicating the direction
    @param res_ref: The reference residue to be rotated
    @return res: A residue with the atoms of res_ref pointing in the direction of res_dir
    '''
    #av = { 'U': ['N1', 'C6', 'C2'], 'C': ['N1', 'C6', 'C2'], 'A': ['N9', 'C4', 'C8'], 'G': ['N9', 'C4', 'C8'] }
    av = { 'U': ['N1', "C1'", "C2'"], 'C': ['N1', "C1'", "C2'"], 'A': ['N9', "C1'", "C2'"], 'G': ['N9', "C1'", "C2'"], 'rU': ['N1', "C1'", "C2'"], 'rC': ['N1', "C1'", "C2'"], 'rA': ['N9', "C1'", "C2'"], 'rG': ['N9', "C1'", "C2'"] }

    dv = av[res_dir.resname.strip()]
    rv = av[res_ref.resname.strip()]

    dir_points = np.array([res_dir[v].get_vector().get_array() for v in dv])
    ref_points = np.array([res_ref[v].get_vector().get_array() for v in rv])

    dir_centroid = cuv.get_vector_centroid(dir_points)
    ref_centroid = cuv.get_vector_centroid(ref_points)

    #sup = brmsd.optimal_superposition(dir_points - dir_centroid, ref_points - ref_centroid)
    sup = brmsd.optimal_superposition(ref_points - ref_centroid, dir_points - dir_centroid)
    new_res = res_ref.copy()

    for atom in new_res:
        atom.transform(np.eye(3,3), -ref_centroid)
        atom.transform(sup, dir_centroid)

    return new_res

def replace_bases(chain, cg):
    '''
    Go through the chain and replace the bases with the ones specified in the
    sequence.

    This is necessary since the stems are sampled by their length rather than
    sequence. Therefore some stem fragments may contain a sequence that is
    different from the one that is required.

    This method will change the identity of those bases, as well as align the atoms
    according to their N1->C2, N1->C6 or N9->C4, N9->C8. vector pairs.

    param @chain: A Bio.PDB.Chain with some reconstructed residues
    param @seq: The sequence of the structure represented by chain
    '''

    if fbc.Configuration.template_residues is None:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            fbc.Configuration.template_residues = bpdb.PDBParser().get_structure('t', conf.Configuration.template_residue_fn)
    s1 = fbc.Configuration.template_residues
    tchain = list(s1.get_chains())[0]


    tindeces = { 'A': 1, 'C': 2, 'G': 3, 'U': 4}

    ress = chain.get_list()

    for i in range(len(ress)):
        #num = ress[i].id[1]
        name = ress[i].resname.strip()

        seq_num = cg.seq_ids.index(ress[i].id)
        ref_res = tchain[tindeces[cg.seq[seq_num]]]
        new_res = replace_base(ress[i], ref_res)

        sca = side_chain_atoms[ress[i].resname.strip()]
        for aname in sca:
            ress[i].detach_child(aname)

        sca = side_chain_atoms[new_res.resname.strip()]
        for aname in sca:
            ress[i].add(new_res[aname])

        ress[i].resname = new_res.resname
        '''
        ress[i].resname = new_res.resname
        ress[i].child_list = new_res.child_list
        ress[i].child_dict = new_res.child_dict
        '''
def mend_breakpoint(h, chain, source_chain):
    # try to make the last residue of the connecting stem transition
    # into the loop region

    # this is done by making a copy of the loop region and aligning
    # it to the backbone of the last residue of the stem

    # the new section (last residue of the stem and two residues of
    # the loop, newly aligned) are then loop-closed to align to the
    # original orientation of the fitted loop region
    temp_loop_chain = source_chain.copy()
    align_starts(chain, temp_loop_chain, [h], end=2)
    rev_handles = [(h[2]-1, h[2]+1, h[0]-1, h[0]+1)]
    temp_loop_chain[h[2] + 1].id = (' ', h[0]+1, ' ')
    temp_loop_chain[h[2] + 2].id = (' ', h[0]+2, ' ')
    temp_loop_chain[h[2] + 3].id = (' ', h[0]+3, ' ')

    detached_residues = []
    detached_residues += add_residue_to_rosetta_chain(chain, temp_loop_chain[h[2]+1])
    detached_residues += add_residue_to_rosetta_chain(chain, temp_loop_chain[h[2]+2])
    #detached_residues += add_residue_to_rosetta_chain(chain, temp_loop_chain[h[2]+3])
    (r1, stem_chain) = align_and_close_loop(10000, source_chain, chain, rev_handles, move_all_angles=False, move_front_angle=False)

    for dr in detached_residues:
        add_residue_to_rosetta_chain(chain, dr)

def get_ideal_stem(template_stem_length):
    '''
    Load the model for an ideal stem of a particular length.

    TODO: Remove the duplicate code in graph_pdb.py (get_mids_core)
    '''
    tstart1 = 1
    tstart2 = template_stem_length * 2
    tend1 = template_stem_length
    tend2 = template_stem_length + 1
    angle_stat = sm.elem_defs[ld]

    template_filename = 'ideal_1_%d_%d_%d.pdb' % (tend1, tend2, tstart2)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        ideal_chain = list(bpdb.PDBParser().get_structure('test',
                op.join(conf.Configuration.stem_fragment_dir, template_filename)).get_chains())[0]

        chain = ftug.extract_define_residues([tstart1,tend1,tend2,tstart2], ideal_chain)
    return chain

def mend_breakpoint_new(chain, res1, res2):
    '''
    Try and mend the breakpoint between res1 and res2.

    This will be done by excising all residues in the range [res1, res2].
    The excised region will be replaced by a new, connected region (nr),
    consisting of residues [res1-1, res2+1]. The new region will be aligned
    along residue res1-1 and will be loop-closed to res2+1. It will
    then be inserted into the chain as the new section.
    '''
    region_len = res2 - res1 + 2
    replacement_length = get_ideal_stem(region_len)
    h = [(res1,res2+1,1,region_len)]

    nr = get_ideal_stem(region_len)
    align_starts(chain, nr, h, end=2)

    h1 = h

    (r1, loop_chain) = align_and_close_loop(10000, chain, nr, h, move_all_angles=False, move_front_angle=False)
    add_loop_chain(chain, nr, h[0], h[0][3] - h[0][2])

def align_source_to_target_fragment(target_chain, source_chain, sm, angle_def, ld):
    '''
    Align a PDB chain to the position where it is supposed to
    bridge the gap between two stems.

    @param target_chain: The chain the fragment is to be inserted into
    @param source_chain: The chain from which the fragment comes
    @param sm: The SpatialModel being reconstructed
    @param angle_def: The define containing the residue numbers in source_chain
    @param ld: The name of the fragment.
    '''
    connections = sm.bg.connections(ld)

    (s1b, s1e) = sm.bg.get_sides(connections[0], ld)
    #(s2b, s2e) = sm.bg.get_sides(connections[1], ld)

    (sd, bd) = sm.bg.get_sides_plus(connections[0], ld)

    t_v = (target_chain[sm.bg.defines[connections[0]][sd]]["C3'"].get_vector().get_array(),
           target_chain[sm.bg.defines[connections[0]][sd]]["C4'"].get_vector().get_array(),
           target_chain[sm.bg.defines[connections[0]][sd]]["O4'"].get_vector().get_array())

    s_v = (source_chain[angle_def.define[bd]]["C3'"].get_vector().get_array(),
           source_chain[angle_def.define[bd]]["C4'"].get_vector().get_array(),
           source_chain[angle_def.define[bd]]["O4'"].get_vector().get_array())

    t_centroid = cuv.get_vector_centroid(t_v)
    s_centroid = cuv.get_vector_centroid(s_v)

    t_v1 = t_v - t_centroid
    s_v1 = s_v - s_centroid

    sup = brmsd.optimal_superposition(s_v1, t_v1)

    for atom in bpdb.Selection.unfold_entities(source_chain, 'A'):
        atom.transform(np.eye(3,3), -s_centroid)
        atom.transform(sup, t_centroid)

    pass

def reconstruct_bulge_with_fragment_core(chain, source_chain, sm, ld, sd0, sd1, angle_def, move_all_angles=False):
    connections = sm.bg.connections(ld)

    a0 = sm.bg.defines[connections[0]][sd0]
    b0 = sm.bg.defines[connections[1]][sd1]
    a = [a0,b0]
    a.sort()
    (a0,b0) = a

    if len(angle_def.define) == 4:
        '''
        a0_1 = sm.bg.defines[connections[0]][sm.bg.same_stem_end(sd0)]
        b0_1 = sm.bg.defines[connections[1]][sm.bg.same_stem_end(sd1)]
        b = [a0_1, b0_1]
        b.sort()
        (a0_1, b0_1) = b
        '''

        # sort the defines by the first entry in each define
        # i.e. [3,4,1,2] -> [1,2,3,]
        s1 = map(list, zip(*[iter(sm.bg.defines[ld])]*2))
        s1.sort()

        for s in s1:
            s[0] -= 1
            s[1] += 1

        s2 = map(list, zip(*[iter(angle_def.define)]*2))
        s2.sort()

        for s in s2:
            s[0] -= 1
            s[1] += 1

        # Associate the defines of the source with those of the loop
        # according to which are lower and which are greater:
        # s1: [(21, 22), (46, 48)]
        # s2: [(134, 135), (142, 144)]
        # handles: [[21, 22, 134, 135], [46, 48, 142, 144]]

        handles = [[i for l in s for i in l] for s in zip(s1, s2)]
        '''

        if angle_def.ang_type == 2 and sd0 == 1:
        #if False:
            i1_0 = angle_def.define[2]
            i2_0 = angle_def.define[3]
            i1_1 = angle_def.define[0]
            i2_1 = angle_def.define[1]
        else:
            i1_0 = angle_def.define[0]
            i2_0 = angle_def.define[1]
            i1_1 = angle_def.define[2]
            i2_1 = angle_def.define[3]

        handles = [(a0,b0,i1_0,i2_0), (a0_1, b0_1, i1_1, i2_1)]
        '''
    else:
        i1_0 = angle_def.define[0]
        i2_0 = angle_def.define[1]
        handles = [(a0,b0,i1_0-1,i2_0+1)]

    seq_len = handles[0][3] - handles[0][2] # i2_0 - i1_0
    align_starts(chain, source_chain, handles, end=0)

    (r, loop_chain) = align_and_close_loop(seq_len, chain, source_chain, handles, move_all_angles=move_all_angles)

    for h in handles:
        mend_breakpoint(h, chain, source_chain)
    for h in handles:
        add_loop_chain(chain, source_chain, h, h[3] - h[2])
        mend_breakpoint_new(chain, h[0], h[0]+1)

    #(r, chain) = align_and_close_loop(seq_len, source_chain, chain,

def reconstruct_bulge_with_fragment(chain, sm, ld, fragment_library=dict(), move_all_angles=False):
    '''
    Reconstruct a loop with the fragment its statistics were derived from.

    @param chain: The chain containing the reconstructed stems.
    @param sm: The SpatialModel containing the information about the sampled
        stems and angles
    @param ld: The name of the loop to reconstruct.
    '''

    angle_def = sm.elem_defs[ld]

    # the file containing the pdb coordinates of this fragment
    filename = '%s_%s.pdb' % (angle_def.pdb_name, "_".join(map(str, angle_def.define)))
    filename = os.path.join(conf.Configuration.stem_fragment_dir, filename)

    # do some caching while loading the filename
    if filename in fragment_library.keys():
        source_chain = fragment_library[filename].copy()
    else:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            source_chain = list(bpdb.PDBParser().get_structure('temp', filename).get_chains())[0]
        fragment_library[filename] = source_chain

    #align_source_to_target_fragment(chain, source_chain, sm, angle_def, ld)

    connections = sm.bg.connections(ld)
    (sd0, bd0) = sm.bg.get_sides_plus(connections[0], ld)
    (sd1, bd1) = sm.bg.get_sides_plus(connections[1], ld)


    if len(angle_def.define) == 2:
        reconstruct_bulge_with_fragment_core(chain, source_chain, sm, ld, sd0, sd1, angle_def, move_all_angles=move_all_angles)
        return

    reconstruct_bulge_with_fragment_core(chain, source_chain, sm, ld, sd0, sd1, angle_def, move_all_angles=move_all_angles)

    return

def reconstruct_loop_with_fragment(chain, sm, ld, fragment_library=dict()):
    '''
    Reconstruct a loop with the fragment its statistics were derived from.

    @param chain: The chain containing the reconstructed stems.
    @param sm: The SpatialModel containing the information about the sampled
        stems and angles
    @param ld: The name of the loop to reconstruct.
    '''

    loop_def = sm.elem_defs[ld]
    angle_def = loop_def

    if loop_def.define[1] - loop_def.define[0] == 1:
        return

    # the file containing the pdb coordinates of this fragment
    filename = '%s_%s.pdb' % (loop_def.pdb_name, "_".join(map(str, loop_def.define)))
    filename = os.path.join(conf.Configuration.stem_fragment_dir, filename)

    # do some caching while loading the filename
    if filename in fragment_library.keys():
        source_chain = fragment_library[filename].copy()
    else:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            source_chain = list(bpdb.PDBParser().get_structure('temp', filename).get_chains())[0]
        fragment_library[filename] = source_chain

    align_source_to_target_fragment(chain, source_chain, sm, loop_def, ld)
    connection = list(sm.bg.edges[ld])[0]

    (sd0, bd0) = sm.bg.get_sides_plus(connection, ld)

    if sd0 == 0:
        a0,b0 = sm.bg.defines[connection][0], sm.bg.defines[connection][3]
    else:
        a0,b0 = sm.bg.defines[connection][1], sm.bg.defines[connection][2]

    i1_0 = angle_def.define[0] - 1
    i2_0 = angle_def.define[1] + 1

    seq_len = i2_0 - i1_0
    align_starts(chain, source_chain, [(a0,b0,i1_0,i2_0)], end=0)
    (r, loop_chain) = align_and_close_loop(seq_len, chain, source_chain, [(a0,b0,i1_0,i2_0)], move_all_angles=False)
    add_loop_chain(chain, source_chain, (a0,b0,i1_0,i2_0), i2_0 - i1_0)
    mend_breakpoint_new(chain, a0, a0+1)

    return

def reconstruct_fiveprime_with_fragment(chain, sm, ld, fragment_library=dict()):
    '''
    Reconstruct a 5' unpaired region with the fragment its statistics were derived from.

    @param chain: The chain containing the reconstructed stems.
    @param sm: The SpatialModel containing the information about the sampled
        stems and angles
    @param ld: The name of the loop to reconstruct.
    '''

    try:
        fiveprime_def = sm.elem_defs[ld]
    except:
        reconstruct_loop(chain, sm, ld)
        return

    if fiveprime_def.define[1] - fiveprime_def.define[0] == 1:
        return


    # the file containing the pdb coordinates of this fragment
    filename = '%s_%s.pdb' % (fiveprime_def.pdb_name, "_".join(map(str, fiveprime_def.define)))
    filename = os.path.join(conf.Configuration.stem_fragment_dir, filename)

    # do some caching while loading the filename
    if filename in fragment_library.keys():
        source_chain = fragment_library[filename].copy()
    else:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            source_chain = list(bpdb.PDBParser().get_structure('temp', filename).get_chains())[0]
        fragment_library[filename] = source_chain

    align_source_to_target_fragment(chain, source_chain, sm, fiveprime_def, ld)

    # add the new chain to the old one
    for j in range(0, len(fiveprime_def.define), 2):
        for k in range(max(fiveprime_def.define[j],1), fiveprime_def.define[j+1]+1):
            target_index = sm.bg.defines[ld][j] + k - fiveprime_def.define[j]

            if target_index in chain:
                chain.detach_child(chain[target_index].id)

            e = source_chain[k]
            e.id = (e.id[0], target_index, e.id[2])

            chain.add(e)
    pass

def reconstruct_threeprime_with_fragment(chain, sm, ld, fragment_library=dict()):
    '''
    Reconstruct a 5' unpaired region with the fragment its statistics were derived from.

    @param chain: The chain containing the reconstructed stems.
    @param sm: The SpatialModel containing the information about the sampled
        stems and angles
    @param ld: The name of the loop to reconstruct.
    '''

    threeprime_def = sm.elem_defs[ld]

    # the file containing the pdb coordinates of this fragment
    filename = '%s_%s.pdb' % (threeprime_def.pdb_name, "_".join(map(str, threeprime_def.define)))
    filename = os.path.join(conf.Configuration.stem_fragment_dir, filename)

    # do some caching while loading the filename
    if filename in fragment_library.keys():
        source_chain = fragment_library[filename].copy()
    else:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            source_chain = list(bpdb.PDBParser().get_structure('temp', filename).get_chains())[0]
        fragment_library[filename] = source_chain

    align_source_to_target_fragment(chain, source_chain, sm, threeprime_def, ld)

    # add the new chain to the old one
    for j in range(0, len(threeprime_def.define), 2):
        for k in range(threeprime_def.define[j], threeprime_def.define[j+1]+1):
            target_index = sm.bg.defines[ld][j] + k - threeprime_def.define[j]

            if target_index in chain:
                chain.detach_child(chain[target_index].id)

            e = source_chain[k]
            e.id = (e.id[0], target_index, e.id[2])

            chain.add(e)
    pass

def reconstruct_from_average(sm):
    '''
    Reconstruct a molecule using the average positions of each atom in
    the elements comprising this structure.

    @param sm: A SpatialModel.
    '''
    atoms = ftug.virtual_atoms(sm.bg, given_atom_names = None)
    c = bpdbc.Chain(' ')

    anum = 1
    for d in sm.bg.defines:
        for rnum in sm.bg.define_residue_num_iterator(d):
            rname = "  " + sm.bg.seq[rnum-1]
            r = bpdbr.Residue((' ', rnum, ' '), rname, '    ')

            for aname in atoms[rnum]:
                atom = bpdba.Atom(aname, atoms[rnum][aname], 0., 1., ' ', aname, 1)
                r.add(atom)

            c.add(r)

    return c


def insert_element(cg_to, cg_from, elem_to, elem_from,
                   chains_to, chains_from):
    '''
    Take an element (elem_from) from one dict of chains (chains_from, cg_from) and
    insert it on the new chain while aligning on the adjoining elements.

    The neighboring elements need to be present in chain_to in order
    for the next element to be aligned to their starting and ending
    positions.

    The dimensions and type of elem_to and elem_from need to be identical.

    @param cg_to: The coarse-grain representation of the target chain
    @param cg_from: The coarse-grain representation of the source chain
    @param elem_to: The element to replace
    @param elem_from: The source element
    @param chains_to: A dict chainid:chain. The chains to graft onto
    @param chains_from: A dict chainid:chain. The chains to excise from
    '''

    assert elem_from[0]==elem_to[0]
    # The define of the loop with adjacent nucleotides (if present) in both cgs
    define_a_to = cg_to.define_a(elem_to)
    define_a_from = cg_from.define_a(elem_from)
    assert len(define_a_to) == len(define_a_from)
    # The defines translated to seq_ids.
    closing_bps_to = []
    closing_bps_from = []
    for nt in define_a_to:
        closing_bps_to.append(cg_to.seq_ids[nt-1])
    for nt in define_a_from:
        closing_bps_from.append(cg_from.seq_ids[nt-1])
    # Seq_ids of all nucleotides in the loop that will be inserted
    seq_ids_a_from = []
    for i in range(0, len(define_a_from), 2):
        for nt in range(define_a_from[i], define_a_from[i+1]+1):
            seq_ids_a_from.append(cg_from.seq_ids[nt-1])
    #The loop fragment to insert in a dict {chain_id:chain}
    try:
        pdb_fragment_to_insert = ftup.extract_subchains_from_seq_ids(chains_from, seq_ids_a_from)
    except:
        log.error("Could not extract fragment %s from pdb: "
                  " At least one of the seq_ids %s not found."
                  " Chains are %s", elem_from, seq_ids_a_from, chains_from.keys())
        raise

    # A list of tuples (seq_id_from, seq_id_to) for the nucleotides
    # that will be used for alignment.
    log.info("Closing_bps _from are %s", closing_bps_from)
    alignment_positions = []
    if elem_from[0]=="t": #Use only left part of define
        alignment_positions.append((closing_bps_from[0], closing_bps_to[0]))
    elif elem_from[0]=="f": #Use only right part of define
        alignment_positions.append((closing_bps_from[1], closing_bps_to[1]))
    else: #Use all flanking nucleotides
        assert elem_from[0]!="s", "No stems allowed in insert_element"
        for i in range(len(closing_bps_from)):
            alignment_positions.append((closing_bps_from[i], closing_bps_to[i]))
    align_all(chains_from, chains_to, alignment_positions)

    #The defines and seq_ids WITHOUT adjacent elements
    define_to = cg_to.defines[elem_to]
    define_from = cg_from.defines[elem_from]
    seq_ids_to = []
    seq_ids_from = []
    for i in range(0, len(define_from), 2):
        for nt in range(define_from[i], define_from[i+1]+1):
            seq_ids_from.append(cg_from.seq_ids[nt-1])
        for nt in range(define_to[i], define_to[i+1]+1):
            seq_ids_to.append(cg_to.seq_ids[nt-1])
    assert len(seq_ids_to)==len(seq_ids_from)
    # Now copy the residues from the fragment chain to the scaffold chain.
    for i in range(len(seq_ids_from)):
        resid_from = seq_ids_from[i]
        resid_to   = seq_ids_to[i]

        residue = chains_from[resid_from.chain][resid_from.resid]
        #Change the resid to the target
        residue.id = resid_to.resid
        if resid_to.chain not in chains_to:
            log.info("Adding chain with id %r for residue %r", resid_to.chain, resid_to)
            chains_to[resid_to.chain] =  bpdb.Chain.Chain(resid_to.chain)
        #Now, add the residue to the target chain
        chains_to[resid_to.chain].add(residue)


def reconstruct_element(cg_to, cg_from, elem_to, elem_from, chains_to,
                        chains_from, close_loop=True, reverse=False):
    '''
    Take an element (elem_from) from one dict of chains (chains_from, cg_from) and
    place it on the new chain while aligning on the adjoining elements.

    The neighboring elements need to be present in chain_to in order
    for the next element to be aligned to their starting and ending
    positions.

    The dimensions and type of elem_to and elem_from need to be identical.

    @param cg_to: The coarse-grain representation of the target chain
    @param cg_from: The coarse-grain representation of the source chain
    @param elem_to: The element to replace
    @param elem_from: The source element
    @param chains_to: A dict chainid:chain. The chains to graft onto
    @param chains_from: A dict chainid:chain. The chains to excise from
    '''
    # get the range of the nucleotides
    ranges_to = cg_to.define_range_iterator(elem_to, adjacent=True,
                                            seq_ids=True)
    ranges_from = cg_from.define_range_iterator(elem_from, adjacent=True,
                                                seq_ids=True)


    # the chains containing the aligned and loop-closed nucleotides
    new_chains = []

    # iterate over each strand
    for r1,r2 in zip(ranges_to, ranges_from):
        # It is not guaranteed (?) that seq-ids in a range will be increasing.
        # So we have to go to positions and then back to seq_ids to
        # construct the correct range.
        r2_seqids = []
        for r in range(cg_from.seq_ids.index(r2[0])+1, cg_from.seq_ids.index(r2[1])+2):
            r2_seqids.append(cg_from.seq_ids[r-1])
        try:
            chains_to_align = ftup.extract_subchains_from_seq_ids(chains_from, r2_seqids)
        except:
            log.error("seq_ids: %s  \nin chains: %s",r2_seqids, [r.id for c in chains_from.values() for r in c])
            raise
        handles = r1 + r2

        align_starts(chains_to, chains_to_align, [handles], end=2, reverse=reverse)

        r = 0.
        if close_loop:
            (r, chains_to_align) = align_and_close_loop(cg_to, chains_to,
                                                       chains_to_align,
                                                       handles)
        fud.pv('elem_to, r')
        new_chains += [loop_chain]

        counter = 1
        for res1, res2 in zip(cg_to.iterate_over_seqid_range(*r1),
                              cg_from.iterate_over_seqid_range(*r2)):

            if elem_to[0] != 'f':
                # omit the frist nucleotide, since that should be part of
                # the preceding stem, except in the case of 5' unpaired regions
                if counter > 1:
                    loop_chain[res2].id = res1
                    add_residue_to_rosetta_chain(chains_to, loop_chain[res2])
            else:
                loop_chain[res2].id = res1
                add_residue_to_rosetta_chain(chains_to, loop_chain[res2])

            counter += 1

    return new_chains

def source_cg_from_stat_name(stat):
    stat_name = stat.pdb_name
    pdb_basename = stat_name.split(":")[0]
    pdb_filename = op.expanduser(op.join('/scratch2/thiel/DATA/nonredundant_RNA_structures2.110/', "".join(pdb_basename.split("_")[:-1])+".pdb"))
    cg_filename = op.expanduser(op.join('/scratch2/thiel/DATA/nonredundant_RNA_structures2.110/cgs/', pdb_basename+".cg"))
    #Make sure the files exist.
    with open(pdb_filename): pass
    with open(cg_filename): pass
    log.debug("Opening cg-file %s to extract stat %s", cg_filename, stat.pdb_name)
    cg = ftmc.CoarseGrainRNA(cg_filename) #The cg with the template

    chains = ftup.get_all_chains(pdb_filename)
    chains = {c.id:c for c in chains}
    return cg, chains

def reconstruct_with_fragment(chains, sm, ld):
    '''
    Reconstruct a loop with the fragment its statistics were derived from.

    @param chains: A dict chain_id:chain that will be filled.
    @param sm: The SpatialModel containing the information about the sampled
        stems and angles
    @param ld: The name of the loop to reconstruct.
    '''

    close_loop = True

    try:
        angle_stat = sm.elem_defs[ld]
    except KeyError:
        # Not part of the minimal spanning tree. We probably need to do use CCD or BARNACLE
        warnings.warn("ML that is not part o the MST is not yet implemented!")
        return

    cg_from, chains_from = source_cg_from_stat_name(angle_stat)
    cg_to = sm.bg
    chains_to = chains
    elem_to = ld
    elem_from = cg_from.get_node_from_residue_num(angle_stat.define[0])

    insert_element(cg_to, cg_from, elem_to, elem_from, chains_to, chains_from)

    return chains

def reorder_residues(chain, cg):
    '''
    Reorder the nucleotides in the chain's list so that they match the order
    in the cg representation.

    @param chain: A Bio.PDB.Chain file
    @param cg: A coarse grain representation
    @return: The same chain, except with reordered nucleotides.
    '''
    chain.child_list.sort(key=lambda x: cg.seq_ids.index(x.id))
    return chain
