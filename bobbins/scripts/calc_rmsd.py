#!/usr/bin/python

import sys

from corgy.builder.rmsd import centered_rmsd
from corgy.graph.bulge_graph import BulgeGraph

def main():
    if len(sys.argv) < 3:
        print >>sys.stderr, "Usage: ./calc_rmsd temp1.comp temp2.comp"
        print >>sys.stderr, "Calculate the rmsd between the two structures."
        sys.exit(1)

    bg1 = BulgeGraph(sys.argv[1])
    bg2 = BulgeGraph(sys.argv[2])

    print "rmsd:", centered_rmsd(bg1.get_centers(), bg2.get_centers())


if __name__ == '__main__':
    main()
