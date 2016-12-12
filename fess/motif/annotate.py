from __future__ import print_function
import os.path as op
import os
import subprocess as sp
import pandas as pa
import warnings
import motif_atlas as ma
import collections as clcs
import fess.builder.config as cbc
import forgi.utilities.debug as fud
import forgi.threedee.model.coarse_grain as ftmc
import sys
import forgi.graph.bulge_graph as fgb
all = [ "annotate_structure" ]

JARED_DIR = op.expanduser(cbc.Configuration.jar3d_dir)
JARED_BIN = cbc.Configuration.jar3d_jar
IL_FILE = cbc.Configuration.jar3d_IL #Download from http://rna.bgsu.edu/data/jar3d/models/ #Relative to JARED_DIR
MOTIF_ATLAS_FILE = cbc.Configuration.jar3d_motif #Click Download at http://rna.bgsu.edu/rna3dhub/motifs/release/il/current# #Relative to JARED_DIR
def annotate_structure(cg, temp_dir, exclude_structure=None, jared_file=None, il_file=None, atlas_file=None):
    '''
    Get the motifs present in this structure.

    :param cg: A CoarseGrainRNA
    :param temp_dir: A directory to place the intermediate files
    :param exclude_structure: None or a string containing a pdb id.
    :param jared_file: path to the jared executable
    :param il_file: path to the interior loop motif atlas file.

    :return: A string containing the motifs.
    '''
    temp_dir = op.expanduser(temp_dir)
    # enumerate the interior loops in the structure
    loop_file = op.join(temp_dir, 'loops')
    try:
        os.makedirs(op.dirname(loop_file))
    except OSError:
        pass
    with open(loop_file, 'w') as f:
        loop_str = cg_to_jared_input(cg)
        f.write(loop_str)

    #fud.pv('jared_file')
    if jared_file is None:
        jared_file = op.expanduser(op.join(JARED_DIR,JARED_BIN))

    if il_file is None:
        il_file = op.expanduser(op.join(JARED_DIR,IL_FILE))

    # run the loops through JAR3D
    jared_output = op.join(temp_dir, 'jared_output')
    cmd = ['java', '-jar', jared_file,
              loop_file, il_file,
              op.join(temp_dir, 'IL_loop_results.txt'),
              op.join(temp_dir, 'IL_sequence_results.txt')]

    #fud.pv("cmd")
    #fud.pv('" ".join(cmd)')
    devnull = open('/dev/null', 'w')
    p = sp.Popen(cmd, stdout=devnull)
    out, err = p.communicate()
    return parse_jared_output(op.join(temp_dir, 'IL_sequence_results.txt'), atlas_file,
                       exclude_structure=exclude_structure, cg=cg)



def get_cg_from_pdb(pdb_file, chain_id, temp_dir=None, cg_filename=None):
    '''
    Get a BulgeGraph from a pdb file.
    
    @param pdb_file: The filename of the pdb file
    @param chain_id: The chain within the file for which to load the BulgeGraph.
    '''
    if temp_dir is not None:
        temp_dir = op.join(temp_dir, 'cg_temp')

    print("Creating CG RNA for:", pdb_file, file=sys.stderr)
    cg = ftmc.from_pdb(pdb_file, chain_id=chain_id,
                      intermediate_file_dir=temp_dir,
                      remove_pseudoknots=False)

    if cg_filename is not None:
        if not op.exists(op.dirname(cg_filename)):
            os.makedirs(op.dirname(cg_filename))

        with open(cg_filename, 'w') as f:
            f.write(cg.to_cg_string())

    #print >>sys.stderr, "Loading cg representation from pdb:", pdb_file, "chain id:", chain_id
    return cg

def get_coarse_grain_file(struct_name, chain_id, temp_dir=None):
    '''
    Load the coarse-grain file for a particular chain in a structure.

    @param struct_name: The name of the structure (i.e. '1Y26')
    @param chain_id: The identifier of the chain for which to return the cg
                     representation (i.e. 'A')
    @return: A forgi.graph.bulge_graph structure describing this chain.
    '''
    CG_DIR = op.join(JARED_DIR, "cgs")
    PDB_DIR = op.join(JARED_DIR, "pdbs")

    if not op.exists(PDB_DIR):
        os.makedirs(PDB_DIR)

    if not op.exists(CG_DIR):
        os.makedirs(CG_DIR)

    cg_filename = op.join(CG_DIR, struct_name + "_" + chain_id + ".cg")

    # do we already have the cg representation
    if op.exists(cg_filename):
        return fgb.BulgeGraph(cg_filename)
    else:
        pdb_filename = op.join(PDB_DIR, struct_name + ".pdb")
        #print >>sys.stderr, "no cg representation found... looking for pdb file:", pdb_filename

        #do we at least have a pdb file
        if op.exists(pdb_filename):
            #print >>sys.stderr, "Found!"
            return get_cg_from_pdb(pdb_filename, chain_id, 
                                   temp_dir=temp_dir, cg_filename=cg_filename)
        else:
            # take it from the top (the RCSB, of course)
            #print >>sys.stderr, "No pdb file found, downloading from the RCSB..."
            print ("Downloading pdb for:", struct_name, file=sys.stderr)
            import urllib2
            response = urllib2.urlopen('http://www.rcsb.org/pdb/download/downloadFile.do?fileFormat=pdb&compression=NO&structureId=%s' % (struct_name))
            html = response.read()
            
            #print >>sys.stderr, "Done. Saving in:", pdb_filename

            with open(pdb_filename, 'w') as f:
                f.write(html)
                f.flush()

                return get_cg_from_pdb(pdb_filename, chain_id, temp_dir=temp_dir,
                                      cg_filename=cg_filename)

    # does the structure exist in CG_DIR?
        # load it and return
    # else
        # does the pdb file exist in PDB_DIR?
            # create a CG representation and save it in CG_DIR
            # return the CG representation
        # else
            # download the file from the pdb
            # create a CG representation and save it in CG_DIR
            # return the CG representation
    

def motifs_to_cg_elements(motifs, temp_dir=None, filename=None):
    '''
    Convert all of the motif alignments to coarse-grain element names. This
    requires that the coarse grain representation of the pdb file from
    which the motif comes from be loaded and the element name be determined
    from the nucleotides within the motif.

    @param motifs: A dictionary indexed by an element name. The values are the
                   json motif object from the BGSU motif atlas.
    @return: A dictionary indexed by an element name containing a list of
             tuples describing where this element can be found in the source
             alignment structures.
    '''
    new_motifs = clcs.defaultdict(list)

    for key in motifs:
        for motif_entry in motifs[key]:
            for a in motif_entry['alignment']:
                alignment = ma.MotifAlignment(motif_entry['alignment'][a],
                                        motif_entry['chainbreak'])

                if len(alignment.chains) > 1:
                    continue

                alignment_chain = list(alignment.chains)[0]
                cg = get_coarse_grain_file(alignment.struct,
                                           alignment_chain,
                                          temp_dir=temp_dir)

                elements = []
                for r in alignment.residues:
                    elements += [cg.get_node_from_residue_num(r, seq_id=True)]

                iloop_elements = set()
                for e in elements:
                    if e[0] == 'i':
                        iloop_elements.add(e)

                #here we should probably verify that all the nucleotides in the
                #alignment are present in the define of the cg element
                if len(iloop_elements) > 0:
                    element_id = list(iloop_elements)[0]
                    new_motifs[key] += [(alignment.struct, alignment_chain, 
                                         element_id, cg.defines[element_id])]

    if filename:    
        if filename=="STDOUT":
            print_motifs(new_motifs, motifs, sys.stdout)
        if filename=="STDERR":
            print_motifs(new_motifs, motifs, sys.stderr)
        else:
            with open(filename, "w") as file_:
                print_motifs(new_motifs, motifs, file_)

    return new_motifs
    
def print_motifs(new_motifs, motifs, file_):
    for key in new_motifs:
        for (pdb_name, chain_id, elem_name, define) in new_motifs[key]:
            if len(define) == 4:
                print(key, pdb_name + "_" + chain_id, len(define), " ".join(map(str, [define[1] - define[0] + 1, define[3] - define[2] + 1])), " ".join(map(str, define)), '"' + motifs[key][0]['common_name'] + '"', file=file_)
                
            else:
                print(key, pdb_name + "_" + chain_id, len(define), " ".join(map(str, [define[1] - define[0] + 1, 0])), " ".join(map(str, define)), '"' + motifs[key][0]['common_name'] + '"', file=file_)

def cg_to_jared_input(cg):
    '''
    Take a coarse grain RNA and output all of the loop
    regions within it in a format that JAR3D can understand.

    :param cg: A CoarseGrainRNA structure
    :return: A string containing the interior loops for jared
    '''
    bg = cg
    out_str = ''

    #iterate over the interior loops
    loops = False
    for il in bg.iloop_iterator():
        # get a tuple containing the sequence on each strand
        seqs = bg.get_define_seq_str(il, adjacent=True)
        il_id = ">%s_%s" % (bg.name, 
                                  "_".join(map(str, bg.defines[il])))
        out_str += il_id + "\n"
        out_str += "*".join(seqs) + "\n"
        loops = True

    if not loops:
        raise ValueError("No interior loops found in structure")

    return out_str

def parse_jared_output(sequence_results, motif_atlas_file=None, exclude_structure=None, cg=None):
    '''
    Parse the output of the JAR3D file and return all of the motifs.

    :param sequence_results: The sequence results file from JAR3D.
    :param motif_atlas_file: The location of the motif atlas.
    '''
    if motif_atlas_file is None:
        motif_atlas_file = op.join(JARED_DIR, MOTIF_ATLAS_FILE)
    motif_atlas_file = op.expanduser(motif_atlas_file)
    #print ("SEQ", sequence_results)
    data = pa.read_csv(sequence_results)
    atlas = ma.MotifAtlas(motif_atlas_file)
    found_motifs = clcs.defaultdict(list)

    for motif in set(data['identifier']): #In older versions of JAR3D, identifier was sequenceId
        subdata = data[data['identifier'] == motif]
        with warnings.catch_warnings():
            #We do not care if subdata is a view or copy from data.
            #We assign to subdata, but never access the corresponding part of data later on!
            warnings.simplefilter("ignore")
            subdata['score'] = subdata['score'].astype(float)
        subdata = subdata.sort(columns='score', ascending=False)
        for i, row in subdata.iterrows():
            # only take the top scoring motif
            motif_id = row['motifId'].split('.')[0]
            motif_entry = atlas.motifs[motif_id]
            res_num = int(motif.split('_')[-1])

            if exclude_structure:
                if atlas.struct_in_motif(motif_id, exclude_structure):
                    # this motif comes from the given structure so we'll exclude it
                    # when reporting the results
                    #print "** Excluding entry...", cg.get_node_from_residue_num(res_num), motif_id, motif_entry['common_name']
                    continue

            if cg:
                #print '--------------------------------'
                element_name = cg.get_node_from_residue_num(res_num)
                #print element_name, motif, motif_id, motif_entry['common_name']

                if motif_entry['alignment']:
                    '''
                    for a in motif_entry['alignment']:
                        # Print out where this motif comes from
                        print ma.MotifAlignment(motif_entry['alignment'][a],
                                                motif_entry['chainbreak'])
                    '''

                    found_motifs[element_name] += [motif_entry]
            else:
                print ('x', motif, motif_id, motif_entry['common_name'], motif_entry['alignment'])

    
            # only return the top scoring motif
            break

    return found_motifs