#! /usr/bin/env python
import numpy as np
import os 
import matplotlib.pyplot as plt
import argparse

"""
This program plots the average electronic energy during a NAMD simulatons averaged over several initial conditions. 
It plots both the SH and SE population based energies. 

Example:

 plot_average_energy.py -p . -nstates 26 -nconds 6 

Note that the number of states is the same as given in the pyxaid output. It must include the ground state as well. 
"""

def plot_stuff(outs, pops):
    """
    energies - a vector of energy values that can be plotted 
    """
    dim_x = np.arange(outs.shape[0])

    plot = np.column_stack((outs, pops)) 
    plt.xlabel('Time (fs)')
    plt.ylabel('Energy (eV)')
    plt.plot(dim_x, plot[:,0:]) 

    fileName = "Average_Energy.png"
    plt.savefig(fileName, format='png', dpi=300)

    plt.show()

def read_energies(path, fn, nstates, nconds):
    inpfile = os.path.join(path, fn)
    cols = tuple(range(5,nstates*2+5,2))
    xs = np.stack(np.loadtxt('{}{}'.format(inpfile, j), usecols=cols) for j in range(nconds)).transpose()
    xs = xs.swapaxes(0,1) # Rows = timeframes ; Columns = states ; tensor = initial conditions   
    return xs 

def read_pops(path, fn, nstates, nconds):
    inpfile = os.path.join(path, fn)
    cols = tuple(range(3,nstates*2+3,2))
    xs = np.stack(np.loadtxt('{}{}'.format(inpfile, j), usecols=cols) for j in range(nconds)).transpose()
    xs = xs.swapaxes(0,1) # Rows = timeframes ; Columns = states ; tensor = initial conditions   
    return xs 

def main(path_output, nstates, nconds):
    outs = read_pops(path_output, 'out', nstates, nconds)  
    pops = read_pops(path_output, 'me_pop', nstates, nconds)  
    energies = read_energies(path_output, 'me_energies', nstates, nconds)

# Weighted state energy for a given SH or SH population at time t  
    eav_outs = energies * outs
    eav_pops = energies * pops 
# Ensamble average over initial conditions of the electronic energy as a function of time
    el_ene_outs = np.average(np.sum(eav_outs, axis=1), axis = 1)
    el_ene_pops = np.average(np.sum(eav_pops, axis=1), axis = 1)
  
    plot_stuff(el_ene_outs, el_ene_pops) 

def read_cmd_line(parser):
    """
    Parse Command line options.
    """
    args = parser.parse_args()

    attributes = ['p', 'nstates', 'nconds']

    return [getattr(args, p) for p in attributes]


# ============<>===============
if __name__ == "__main__":
    msg = " plot_states_pops -p <path/to/output> -nstates <number of states computed> -nconds <number of initial conditions>"

    parser = argparse.ArgumentParser(description=msg)
    parser.add_argument('-p', required=True, help='path to the Hamiltonian files in Pyxaid format')
    parser.add_argument('-nstates', type=int, required=True, help='Number of states')
    parser.add_argument('-nconds', type=int, required=True, help='Number of initial conditions')

