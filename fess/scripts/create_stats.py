from __future__ import print_function
import argparse
import sys
from collections import defaultdict
import forgi.threedee.model.coarse_grain as ftmc
import forgi.threedee.utilities.graph_pdb as ftug
import logging
logging.basicConfig(level=logging.DEBUG)
def get_parser():
    parser=argparse.ArgumentParser("Create stats")
    parser.add_argument("cg", nargs="+", help="One or more cg files.")
    return parser

parser=get_parser()
if __name__ == "__main__":
    args = parser.parse_args()
    next_id = defaultdict(int)
    for cgfile in args.cg:
        cg = ftmc.CoarseGrainRNA(cgfile)
        if sys.stderr.isatty():
            print(cg.name, file=sys.stderr)
        for elem in cg.defines.keys():
            if elem in cg.incomplete_elements:
                print("Skipping element", elem, file = sys.stderr)
                continue
            base_name = "{}:{}_".format(cg.name, elem[0])
            for stat in cg.get_stats(elem):
                idnr = next_id[base_name]
                next_id[base_name]+=1
                name = base_name+str(idnr)
                stat.pdb_name = name
                if elem.startswith("m"):
                    try:
                        dist = ftug.junction_virtual_atom_distance(cg, elem)
                        stat_dist = stat.get_virtual_atom_distance()
                    except:
                        print(stat)
                        #raise
                    else:
                        print(stat, "# distance: {}. stat_dist {}".format(dist, stat_dist))
                else:
                    print(stat)
