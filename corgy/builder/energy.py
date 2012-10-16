#!/usr/bin/python

import pickle, os
import pandas as pa
import Bio.PDB as bpdb

import scipy.spatial as ss
import Bio.KDTree as kd
import sys
import numpy as np
import corgy.utilities.debug as cud

from copy import deepcopy

import corgy.utilities.vector as cuv
import corgy.graph.graph_pdb as cgg
import corgy.exp.kde as cek

from corgy.builder.models import SpatialModel

from corgy.utilities.data_structures import DefaultDict
import corgy.builder.reconstructor as rtor

from pylab import plot, savefig, clf, ylim

from numpy import mean

from scipy.stats import norm, linregress
from numpy import log, array, sqrt, linspace
from random import random, shuffle, uniform
from corgy.builder.sampling import GibbsBGSampler, SamplingStatistics

from corgy.utilities.statistics import interpolated_kde
from corgy.builder.config import Configuration

from sys import float_info, stderr


def my_log(x):
    return log(x + 1e-200)

class MissingTargetException(Exception):
    def __init__(self, message):
        Exception.__init__(self, message)

class EnergyFunction:
    '''
    The base class for energy functions.
    '''

    def __init__(self):
        pass

    def eval_energy(self, sm, background=True):
        '''
        The base energy function simply returns a random number.
        '''
        return random()

    def calc_fg_parameters(self, bg):
        '''
        Found out the parameters for the target distribution.

        In many cases these will be derived from the list of statistics.
        '''
        pass

    def calc_bg_parameters(self, energy_structs):
        '''
        Adjust the parameters based on the sampling statistics from
        a previous run.

        @param energy_structs: A list of tuples of the form (energy, bg)
        '''
        pass

    def calibrate(self, sm, iterations = 10, bg_energy = None):
        '''
        Calibrate this energy function.

        This is done by sampling structures given a background energy function.
        The sampled structures are used to normalize the energy of this
        function.
        '''
        self.calc_fg_parameters(sm.bg)

        stats = SamplingStatistics(sm)
        stats.silent = True

        # if not background energy function is provided, then the background
        # distribution is simply the proposal distribution implicit in 
        # GibbsBGSampler

        if bg_energy == None:
            bg_energy = EnergyFunction()
        
        gs = GibbsBGSampler(deepcopy(sm), bg_energy, stats)
        for i in range(iterations):
            gs.step()

        # Get the set of sampled structures
        ser_structs = sorted(stats.energy_rmsd_structs, key=lambda x: x[0])

        # I only want the top 2/3 of the sampled structures
        selected = ser_structs[:2 * (len(ser_structs) / 3)]
        selected_structs = [s[2] for s in selected]

        self.calc_bg_parameters(selected_structs)
             
        
class RandomEnergy(EnergyFunction):
    '''
    An energy function that always just returns a random value.
    '''
    def __init__(self):
        pass

    def eval_energy(self, sm, background=True):
        return uniform(-5, 3)

class DistanceIterator:
    '''
    A class for iterating over the elements that are a certain
    distance from each other.

    '''
    def __init__(self, min_distance=0., max_distance=float_info.max):
        '''
        @param min_distance: The minimum distance for an interaction.
        @param max_distance: The maximum distance for an interaction.
        '''
        self.min_distance = min_distance
        self.max_distance = max_distance

    def iterate_over_interactions(self, bg):
        '''
        Iterate over the list of elements in a structure that interact
        based on the distance criteria below.

        @param bg: The coarse grain representation of a structure.
        @return: (d1,d2) where d1 and d2 are two interacting elements.
        '''
        keys = bg.defines.keys()

        for i in range(len(keys)):
            for j in range(i+1, len(keys)):
                d1 = keys[i]
                d2 = keys[j]

                point1 = bg.get_point(d1)
                point2 = bg.get_point(d2)

                dist = cuv.vec_distance(point1, point2)

                #if dist > 6.0 and dist < 25.0:
                if dist > self.min_distance and dist < self.max_distance:
                    yield tuple(sorted([d1, d2]))

lri_iter = DistanceIterator(6., 25.)

class CombinedEnergy:
    def __init__(self, energies=[], uncalibrated_energies=[]):
        self.energies = energies
        self.uncalibrated_energies = uncalibrated_energies

    def save_energy(self, energy, directory):
        if not os.path.exists(directory):
            os.makedirs(directory)

        filename = os.path.join(directory, energy.__class__.__name__ + ".energy")
        print "saving filename:", filename
        pickle.dump(energy, open(filename, 'w'))

    def calibrate(self, sm, iterations=40, bg_energy=None, output_dir='/home/mescalin/pkerp/projects/ernwin/energies'):
        '''
        Calibrate each of the energies by taking into account the
        background distribution induced by non-energy directed 
        sampling.
        '''
        self.energies[0].calibrate(sm, iterations)
        filename = os.path.join(output_dir, str(sm.bg.name))
        filename = os.path.join(filename, str(iterations))

        self.save_energy(self.energies[0], filename)
        filename = os.path.join(filename, self.energies[0].__class__.__name__)

        for i in range(1, len(self.energies)):
            ce = CombinedEnergy(self.energies[:i])
            self.energies[i].calibrate(sm, iterations, ce)

            self.save_energy(self.energies[i], filename)
            filename = os.path.join(filename, self.energies[i].__class__.__name__)

        self.save_energy(self, filename)

    def eval_energy(self, sm, verbose=False, background=True):
        total_energy = 0.

        for energy in self.uncalibrated_energies:
            total_energy += energy.eval_energy(sm)
    
        for energy in self.energies:
            contrib = energy.eval_energy(sm, background)

            total_energy += contrib

            if verbose:
                print energy.__class__.__name__, contrib

        return total_energy

class SkewNormalInteractionEnergy(EnergyFunction):
    '''
    This energy will assume that all elements need to be a certain
    distance from each other to interact.

    This distance is centered at around 15 angstroms.

    The distribution of distances is modeled by a skew-normal-distribution and
    the total energy will be the sum of log probabilities for the interactions.
    '''
    def __init__(self):
        self.fg = None
        self.bgs = dict()

    def get_target_distribution(self, long_range_stats_fn='../fess/stats/temp.longrange.contact'):
        '''
        Get the target distribution of long range interaction
        lengths.
        '''
        f = open(long_range_stats_fn, 'r')
        lengths = []


        length = list(linspace(0, 200, 200))

        for line in f:
            parts = line.strip().split(' ')
            lengths += [float(parts[2])]

        print "len(lengths):", len(lengths)
        lengths = lengths[::len(lengths)/100]
        self.fg = interpolated_kde(lengths)

    def calc_fg_parameters(self, bg):
        self.get_target_distribution(Configuration.longrange_contact_stats_fn)

    def calc_bg_parameters(self, structs):
        '''
        Calculate the energy parameters of a given distribution.

        In this case, the structs parameter contains a list of structures. These structures
        will have a particular distribution of this energy function. The distribution of 
        energies of these structures will be the background distribution.
        
        @param structs: The structures to used to define the background energy distribution.
        '''
        interaction_distances = DefaultDict([])

        for bg in structs:

            defines = list(bg.defines.keys())
        
            for j in range(len(defines)):
                for k in range(j+1, len(defines)):
                    if defines[j] not in bg.edges[defines[k]]:
                        interaction = tuple(sorted([defines[j], defines[k]]))

                        distance = cuv.vec_distance(bg.get_point(interaction[0]), bg.get_point(interaction[1]))
                        interaction_distances[interaction] += [distance]

        for interaction in interaction_distances.keys():
            interaction_distances[interaction] += list(linspace(0, 200, 100))
            interactions = interaction_distances[interaction][::len(interaction_distances[interaction])/100]
            self.bgs[interaction] = interpolated_kde(interactions)

        #self.plot_energies()

    def plot_energies(self):
        '''
        Make plots of the foreground and background energies.
        '''
        for interaction in self.bgs.keys():
            bg = self.bgs[interaction]
            fg = self.fg

            clf()
            distance_range = linspace(0, 100., 300)

            ylim((-20, 10))
            plot(distance_range, fg(distance_range), 'ro')
            plot(distance_range, fg(distance_range) - bg(distance_range), 'go')
            plot(distance_range, bg(distance_range), 'bo')
            figname = 'figs/%s.png' % ("-".join(interaction))
            print >>stderr, "saving: %s..." % (figname)

            savefig(figname, bbox_inches=0)

    def get_energy_contribution(self, bg, interaction, background=True):
        '''
        Get the energy term for an interaction.
        '''

        fg = self.fg
        distance = cuv.vec_distance(bg.get_point(interaction[0]), bg.get_point(interaction[1]))

        bgf = self.bgs[interaction]
        bgp = 1.

        if background:
            #print >>stderr, "distance;", distance, "fg:", fg, "interaction:", interaction


            try:
                fgp = fg(distance)
                #print "distance: ", distance, "fgp:", fgp, "interaction:", interaction
            except FloatingPointError as fpe:
                fgp = 1e-200
            bgp = bgf(distance)
        else:
            fgp = fg(distance)
        
        #energy = my_log(fgp) - my_log(bgp)
        energy = fgp - bgp

        return energy

    def iterate_over_interactions(self, bg, background=True):
        defines = list(bg.defines.keys())

        for j in range(len(defines)):
            for k in range(j+1, len(defines)):
                if defines[j] not in bg.edges[defines[k]]:
                    # Ignore interactions with elements that are only length 1
                    if ((bg.defines[defines[j]][1] - bg.defines[defines[j]][0] == 1) or
                        (bg.defines[defines[k]][1] - bg.defines[defines[k]][0] == 1)):
                        continue

                    # Ignore interactions between extremely close elements
                    if bg.bp_distances == None:
                        bg.calc_bp_distances()
                    if  bg.bp_distances[defines[j]][defines[k]] < 10:
                        continue
                
                    interaction = tuple(sorted([defines[j], defines[k]]))

                    energy = self.get_energy_contribution(bg, interaction, background)

                    yield (interaction, energy)

    def prune_energies(self, energies):
        '''
        Take only the three most favorable energy contributions for any
        element.

        if s1 has four interactions ('s3':5, 'b3':4, 'x3':7, 'x4':8) then
        its total energy would be 8 + 7 + 5 = 20.

        @param energies: A dictionary with the interactions (e1, e2) as the key and an
            energy as the value.
        '''
        sorted_interactions_falling = sorted(energies, key=lambda key: -energies[key])
        sorted_interactions_rising = sorted(energies, key=lambda key: energies[key])

        energy_counts = DefaultDict(0)
        new_energies = dict()

        num_best = 1
        num_worst = 0

        for interaction in sorted_interactions_falling:
            if energy_counts[interaction[0]] < num_best and energy_counts[interaction[1]] < num_best:
                energy_counts[interaction[0]] += 1 
                energy_counts[interaction[1]] += 1
                new_energies[interaction] = energies[interaction]

        energy_counts = DefaultDict(0)
        for interaction in sorted_interactions_rising:
            if energy_counts[interaction[0]] < num_worst and energy_counts[interaction[1]] < num_worst:
                energy_counts[interaction[0]] += 1 
                energy_counts[interaction[1]] += 1
                new_energies[interaction] = energies[interaction]

        new_energies

        return new_energies

    def iterate_over_interaction_energies(self, bg, background):
        sm = SpatialModel(bg)

        self.eval_energy(sm, background)
        for key in self.interaction_energies.keys():
            yield (key, self.interaction_energies[key])
        
    def eval_energy(self, sm, background=True):
        energy_total = 0.
        interactions = 1.
        bg = sm.bg

        energies = dict()

        for (interaction, energy) in self.iterate_over_interactions(bg, background):
            energies[interaction] = energy

        new_energies = self.prune_energies(energies)
        self.interaction_energies = new_energies

        for energy in new_energies.values():
            energy_total += energy
            interactions += 1

        #return -(energy_total / (2. * interactions))
        return -energy_total

class JunctionClosureEnergy(EnergyFunction):
    def __init__(self):
        self.name = 'jce'
        self.fgs = dict()
        self.bgs = dict()

    def get_target_distributions(self, angle_stats, length):
        '''
        Fit a skew-normal distribution to the distribution of bulge
        lengths.

        @param angle_stats: The statistics file.
        '''

        # we only care about single stranded bulges
        angle_stats = angle_stats[0]

        k = length
        stats = [s.r1 for s in angle_stats[k]]

        if len(stats) < 4:
            fit = [mean(stats), 1.0, 0.0]
        else:
            fit = interpolated_kde(stats)

        return fit

    def calc_fg_parameters(self, bg):
        all_bulges = set([d for d in bg.defines.keys() if d[0] != 's' and len(bg.edges[d]) == 2])
        sm = SpatialModel(bg)

        # build the structure to see if there are any closed bulges
        sm.traverse_and_build()
        closed_bulges = all_bulges.difference(sm.sampled_bulges)

        for bulge in closed_bulges:
            fg_fit = self.get_target_distributions(sm.angle_stats, abs(bg.defines[bulge][1] - bg.defines[bulge][0]))
            self.fgs[abs(bg.defines[bulge][1] - bg.defines[bulge][0])] = fg_fit

    def calc_bg_parameters(self, structs):
        '''
        Calculate the energy parameters of a given distribution.

        In this case, the structs parameter contains a list of structures. These structures
        will have a particular distribution of this energy function. The distribution of 
        energies of these structures will be the background distribution.
        
        @param structs: The structures used to define the background energy distribution.
        '''
        bg = structs[0]
        sm = SpatialModel(deepcopy(bg))

        sm.traverse_and_build()

        distances = DefaultDict([])

        all_bulges = set([d for d in bg.defines.keys() if d[0] != 's' and len(bg.edges[d]) == 2])
        closed_bulges = all_bulges.difference(sm.sampled_bulges)

        for bg in structs:
            for bulge in closed_bulges:
                bl = abs(bg.defines[bulge][1] - bg.defines[bulge][0])
                distance = cuv.vec_distance(bg.coords[bulge][1], bg.coords[bulge][0])
                distances[bulge] += [distance]

        for bulge in closed_bulges:
            bg_fit = interpolated_kde(distances[bulge])

            self.bgs[abs(bg.defines[bulge][1] - bg.defines[bulge][0])] = bg_fit

            '''
            ds = array(distances[bulge])

            fg = fg_fit(ds)
            bg = bg_fit(ds)


            plot(ds, fg, 'bo')
            plot(ds, bg, 'ro')
            plot(ds, fg - bg, 'go')
            #show()
            '''

    def eval_energy(self, sm, background=True):
        #bulge = 'b5' 
        bg = sm.bg
        all_bulges = set([d for d in bg.defines.keys() if d[0] != 's' and len(bg.edges[d]) == 2])
        closed_bulges = all_bulges.difference(sm.sampled_bulges)

        energy = array([0.])

        for bulge in closed_bulges:
            bl = abs(bg.defines[bulge][1] - bg.defines[bulge][0])

            fgd = self.fgs[bl]
            bgd = self.bgs[bl]

            dist = cuv.vec_distance(bg.coords[bulge][1], bg.coords[bulge][0])
            #print "bl:", bl, "dist:", dist

            if background:
                energy += -(fgd(dist) - bgd(dist))
            else:
                energy += -fgd(dist)
        
        #print "energy:", energy
        #print "energy[0]:", energy[0]

        return energy[0]

class LongRangeInteractionCount(EnergyFunction):
    '''
    An energy function to keep track of how many elements are within
    a certain distance of each other.
    '''

    def __init__(self, di = lri_iter):
        self.distance_iterator = di
        self.target_interactions = None

    def get_target_interactions(self, bg, filename):
        '''
        Calculate the linear regression of interaction counts.

        @param bg: The BulgeGraph of the target structure
        @param filename: The filename of the statistics file
        '''

        f = open(filename, 'r')
        long_range = []
        all_range = []
        for line in f:
            parts = line.strip().split(' ')

            if float(parts[1]) < 400:
                long_range += [float(parts[0])]
                all_range += [sqrt(float(parts[1]))]

        gradient, intercept, r_value, p_value, std_err = linregress(all_range, long_range)

        di = self.distance_iterator
        self.distance_iterator = DistanceIterator()
        total_interactions = self.count_interactions(bg)
        target_interactions = gradient * sqrt(total_interactions) + intercept
        self.distance_iterator = di
        
        return target_interactions

    def calc_fg_parameters(self, bg):
        self.target_interactions = self.get_target_interactions(bg, Configuration.lric_stats_fn)

    def calc_bg_parameters(self, structs):
        '''
        Calculate the energy parameters of a given distribution.

        In this case, the structs parameter contains a list of structures. These structures
        will have a particular distribution of this energy function. The distribution of 
        energies of these structures will be the background distribution.
        
        @param structs: The structures to used to define the background energy distribution.
        '''
        interactions = [self.count_interactions(struct) for struct in structs]
        shuffle(interactions)
        self.bgf = interpolated_kde([float(interaction) for interaction in interactions])
            
    def count_interactions(self, bg):
        '''
        Count the number of long range interactions that occur in the structure.
        '''

        count = 0

        for inter in self.distance_iterator.iterate_over_interactions(bg):
            count += 1

        return count

    def eval_energy(self, sm, background=True):
        bg = sm.bg
        self.distance_iterator = lri_iter
        count = self.count_interactions(bg)

        if self.target_interactions == None:
            raise MissingTargetException("LongRangeInteractionEnergy target_interaction is not defined. This energy probably hasn't been calibrated")

        #return float(count)
        contrib = -(my_log(norm.pdf(float(count), self.target_interactions, 8.)) - self.bgf(float(count)))

        return contrib
        #return -(log(norm.pdf(float(count), 89., 8.)) - log(skew(count, self.skew_fit[0], self.skew_fit[1], self.skew_fit[2])))

class StemVirtualResClashEnergy(EnergyFunction):
    '''
    Determine if the virtual residues clash.
    '''

    def __init__(self):
        pass

    def eval_energy(self, sm, background=False):
        '''
        Cound how many clashes of virtual residues there are.

        @param sm: The SpatialModel containing the list of stems.
        @param background: Use a background distribution to normalize this one.
                           This should always be false since clashes are independent
                           of any other energies.
        '''
        l = []
        bg = sm.bg
        mult = 7

        for d in sm.bg.defines.keys():
            if d[0] == 's':
                s_len = bg.defines[d][1] - bg.defines[d][0]
                for i in range(s_len):
                    (p, v) = cgg.virtual_res_3d_pos(bg, d, i)
                    l += [p+ mult * v]

        #kk = ss.KDTree(array(l))
        kdt = kd.KDTree(3)
        kdt.set_coords(array(l))
        kdt.all_search(4.)
        #print len(kdt.all_get_indices())
        #print len(kk.query_pairs(7.))

        energy = 100000 * len(kdt.all_get_indices())

        #energy = 1000 * len(kdt.all_search(4.))
        #energy = 1000 * len(kd.query_pairs(4.))

        #print >>sys.stderr, "energy:", energy

        return energy

class StemClashEnergy(EnergyFunction):
    '''
    Determine if there's any atom clashes in the structures.
    '''

    def __init__(self):
        self.stem_library = dict()

        pass

    def eval_energy(self, sm, background=True):
        '''
        The base energy function simply returns a random number.
        '''
        #chain = rtor.reconstruct_stems(sm, self.stem_library)
        chain = sm.chain
        atoms = bpdb.Selection.unfold_entities(chain, 'A')

        ns = bpdb.NeighborSearch(atoms)
        contacts1 = len(ns.search_all(0.8))

        return contacts1 * 1000.

class DistanceEnergy(EnergyFunction):

    def __init__(self, distance_constraints, multiplier= 10):
        self.distance_constraints = distance_constraints
        self.multiplier = multiplier

        pass

    def eval_energy(self, sm, background=True):
        energy = 0.

        for constraint in self.distance_constraints:
            f = constraint[0]
            t = constraint[1]
            d = float(constraint[2])

            d1 = cuv.magnitude(sm.bg.get_point(f) - sm.bg.get_point(t))

            energy += abs(d1 - d)
        
        return energy

class HelixOrientationEnergy(EnergyFunction):
    def __init__(self):
        self.real_kde = self.load_stem_orientation_data('fess/stats/stem_nt.stats')
        self.fake_kde = self.load_stem_orientation_data('fess/stats/stem_nt_sampled.stats')
        pass

    def load_stem_orientation_data(self, filename):
        stats = pa.read_csv(filename,header=None, sep=' ')
        points = stats[['X.3', 'X.4', 'X.5']].as_matrix()
        
        return cek.gaussian_kde(points.T)


    def eval_energy(self, sm, background=True):
        bg = sm.bg
        stems = [d for d in bg.defines.keys() if d[0] == 's']
        score = 0

        for s1 in stems:
            s1_len = bg.defines[s1][1] - bg.defines[s1][0]
            for s2 in stems:
                if s1 != s2:
                    s2_len = bg.defines[s2][1] - bg.defines[s2][0]
                    for l in range(s1_len):
                        for k in range(s2_len):
                            r2_spos = cgg.pos_to_spos(bg, s1, k, s2, l)

                            score_incr = my_log(self.real_kde(r2_spos)) - my_log(self.fake_kde(r2_spos))
                            #print
                            #cud.pv('my_log(self.real_kde(r2_spos))')
                            #cud.pv('my_log(self.fake_kde(r2_spos))')

                            score += score_incr
        return -score

class RoughJunctionClosureEnergy(EnergyFunction):
    def __init__(self):
        pass

    def eval_energy(self, sm, background=True):
        bg = sm.bg
        all_bulges = set([d for d in bg.defines.keys() if d[0] != 's' and len(bg.edges[d]) == 2])
        #closed_bulges = all_bulges.difference(sm.sampled_bulges)

        energy = 0.

        #for bulge in closed_bulges:
        for bulge in all_bulges:
            bl = abs(bg.defines[bulge][1] - bg.defines[bulge][0])

            dist = cuv.vec_distance(bg.coords[bulge][1], bg.coords[bulge][0])
            #cud.pv('dist')

            if bl == 1:
                if dist > 4.0:
                    energy += 10000
            elif bl == 2:
                if dist > 10.0:
                    energy += 10000
            else:
                if dist > (bl-1) * 7.0:
                    energy += 10000

        return energy
