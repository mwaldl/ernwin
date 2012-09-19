import unittest, os, copy

from corgy.builder.config import Configuration
from corgy.builder.models import SpatialModel
from corgy.builder.stats import AngleStat
from corgy.graph.bulge_graph import BulgeGraph

from numpy import allclose, pi
from random import uniform

import numpy as np
import corgy.utilities.vector as cuv

class TestSpatialModel(unittest.TestCase):
    def setUp(self):
        self.bg = BulgeGraph(os.path.join(Configuration.test_input_dir, "1gid/graph", "temp.comp"))

    def check_side_integrity(self, bg):
        '''
        Test to make sure that the sides of each stem are
        consistent.
        '''
        for d in bg.defines.keys():
            if d[0] == 's':
                for edge in bg.edges[d]:
                    (s1b, s1e) = bg.get_sides(d, edge)

                    stem_mid = bg.coords[d][s1b]
                    bulge_mids = bg.coords[edge]

                    self.assertTrue(allclose(stem_mid, bulge_mids[0]) or allclose(stem_mid, bulge_mids[1]))

    def check_angle_integrity(self, sm):
        '''
        Test to make sure that the angles match up with the ones
        in the defs.
        '''
        for b in sm.sampled_bulges:
            angle_stat = sm.bg.get_bulge_angle_stats(b)

            self.assertTrue((angle_stat[0] == sm.angle_defs[b]) or (angle_stat[1] == sm.angle_defs[b]))

    def check_angle_composition(self, bg, angle_stats):
        for define in bg.defines.keys():
            if define[0] != 's' and len(bg.edges[define]) == 2:
                connections = list(bg.edges[define])

                (stem1, twist1, stem2, twist2, bulge) = get_stem_twist_and_bulge_vecs(bg, define, connections)

                # Get the orientations for orienting these two stems
                (r, u, v, t) = get_stem_orientation_parameters(stem1, twist1, stem2, twist2)
                (r1, u1, v1) = get_stem_separation_parameters(stem1, twist1, bulge)

                dims = bg.get_bulge_dimensions(define)

                this_stat = AngleStat('', dims[0], dims[1], u, v, t, r1, u1, v1)
                stats_list = angle_stats[dims[0]][dims[1]]

                found = False

                for a_s in stats_list:
                    if a_s == this_stat:

                        found=True
                        break

                self.assertTrue(found)
                         

    def test_angle_stat_equality(self):
        '''
        Check if the equality function for two stats works.
        '''

        for i in range(10):
            u = uniform(0., pi)
            v = uniform(-pi, pi)
            t = uniform(-pi, pi)

            r1 = uniform(0, 20)
            u1 = uniform(0., pi)
            v1 = uniform(-pi, pi)

            a_s1 = AngleStat('', 0, 0, u, v, t, r1, u1, v1)
            a_s2 = AngleStat('', 0, 0, u, v, t, r1, u1, v1)
            a_s3 = AngleStat('', 0, 0, v, u, t, r1, u1, v1)

            self.assertTrue(a_s1 == a_s2)

            self.assertTrue(not (a_s1 == a_s3))


    def compare_models(self, bg1, bg2):
        for d in bg1.defines.keys():
            if d[0] == 's':
                self.assertTrue(allclose(bg1.coords[d], bg2.coords[d]))
                self.assertTrue(allclose(bg1.twists[d][0], bg2.twists[d][0]))
                self.assertTrue(allclose(bg1.twists[d][1], bg2.twists[d][1]))

    def test_spatial_model_construction(self):
        bg = self.bg

        sm = SpatialModel(bg)
        sm.traverse_and_build()
        sm.bg.output('this.coords')

        self.check_side_integrity(sm.bg)
        self.check_angle_integrity(sm)

    def test_identical_spatial_model_construction(self):
        bg = self.bg

        #self.check_angle_composition(bg, angle_stats)

        sm = SpatialModel(bg)
        sm.traverse_and_build()

        bg1 = copy.deepcopy(sm.bg)
        angle_defs = sm.angle_defs
        stem_defs = sm.stem_defs

        sm1 = SpatialModel(bg, angle_defs = angle_defs, stem_defs = stem_defs)
        sm1.traverse_and_build()
        self.compare_models(bg1, sm1.bg)

    def test_sampled_bulges(self):
        bg = self.bg
        sm = SpatialModel(copy.deepcopy(bg))

        sm.traverse_and_build()
        sb1 = sm.sampled_bulges

        sm.get_sampled_bulges()
        sb2 = sm.sampled_bulges

        self.assertEqual(sb1, sb2)

    def long_bulge_test(self, bg):
        sm = SpatialModel(bg)
        
        sm.traverse_and_build()
        for key in sm.sampled_bulges:

            if len(bg.edges[key]) != 2:
                continue

            if key not in bg.edges.keys():
                continue
            
            le = list(bg.edges[key])
            e1 = le[0]
            e2 = le[1]

            (s1b, s1e) = sm.bg.get_sides(e1, key)
            (s2b, s2e) = sm.bg.get_sides(e2, key)

            c1 = sm.bg.coords[e1][s1b]
            c2 = sm.bg.coords[e2][s2b]

            self.assertTrue(np.allclose(sm.angle_defs[key].r1, cuv.magnitude(np.array(c1) - np.array(c2))))
            #print 'key:', key, 'dist:', cuv.magnitude(np.array(c1) - np.array(c2))

        sm.bg.output(os.path.join(Configuration.test_output_dir, 'long_bulges.comp'))


    def test_long_bulges(self):
        bg1 = BulgeGraph(os.path.join(Configuration.test_input_dir, '1y26/graph/temp.comp'))
        bg2 = BulgeGraph(os.path.join(Configuration.test_input_dir, '1gid/graph/temp.comp'))

        self.long_bulge_test(bg1)
        self.long_bulge_test(bg2)
