"""Molecular orbitals calculation using CP2K and `QMFlows <https://github.com/SCM-NV/qmflows>`.

API
---
.. autofunction:: calculate_mos

"""

__all__ = ["calculate_mos", "create_point_folder",
           "split_file_geometries"]

import fnmatch
import logging
import os
import shutil
from collections import defaultdict
from os.path import join
from typing import Any, DefaultDict, Dict, List, NamedTuple

from more_itertools import chunked
from noodles import gather, schedule

from qmflows.common import InfoMO
from qmflows.type_hints import PathLike, PromisedObject
from qmflows.warnings_qmflows import SCF_Convergence_Warning

from ..common import (DictConfig, Matrix, MolXYZ, is_data_in_hdf5,
                      read_cell_parameters_as_array, store_arrays_in_hdf5)
from .scheduleCP2K import prepare_job_cp2k

# Starting logger
logger = logging.getLogger(__name__)


class JobFiles(NamedTuple):
    """Contains the data to compute the molecular orbitals for a given geometry."""

    get_xyz: PathLike
    get_inp: PathLike
    get_out: PathLike
    get_MO: PathLike


def calculate_mos(config: DictConfig) -> List[str]:
    """Look for the MO in the HDF5 file and compute them if they are not present.

    The orbitals are computed  by splitting the jobs in batches given by
    the ``restart_chunk`` variables. Only the first job is calculated from scratch
    while the rest of the batch uses as guess the wave function of the first calculation
    inthe batch.

    The config dict contains:
        * geometries: list of molecular geometries
        * project_name: Name of the project used as root path for storing data in HDF5.
        * path_hdf5: Path to the HDF5 file that contains the numerical results.
        * folders: path to the directories containing the MO outputs
        * settings_main: Settings for the job to run.
        * calc_new_wf_guess_on_points: Calculate a new Wave function guess in each of the geometries indicated. By Default only an initial guess is computed.
        * enumerate_from: Number from where to start enumerating the folders create for each point in the MD

    Returns
    -------
    list
        path to nodes in the HDF5 file to MO energies and MO coefficients.

    """
    # Read Cell parameters file
    general = config['cp2k_general_settings']
    file_cell_parameters = general["file_cell_parameters"]
    if file_cell_parameters is not None:
        array_cell_parameters = read_cell_parameters_as_array(file_cell_parameters)[
            1]

    # First calculation has no initial guess
    # calculate the rest of the jobs using the previous point as initial guess
    orbitals = []  # list to the nodes in the HDF5 containing the MOs
    energies = []
    guess_job = None
    for j, gs in enumerate(config.geometries):

        # number of the point with respect to all the trajectory
        k = j + config.enumerate_from

        # dictionary containing the information of the j-th job
        dict_input = defaultdict(lambda _: None)
        dict_input["geometry"] = gs
        dict_input["k"] = k

        # Path where the MOs will be store in the HDF5
        root = join(config.project_name, f'point_{k}',
                    config.package_name, 'mo')
        dict_input["node_MOs"] = [
            join(
                root, 'eigenvalues'), join(
                root, 'coefficients')]
        dict_input["node_energy"] = join(root, 'energy')

        # If the MOs are already store in the HDF5 format return the path
        # to them and skip the calculation
        if config["compute_orbitals"]:
            predicate = dict_input["node_MOs"]
        else:
            predicate = dict_input["node_energy"]
        if is_data_in_hdf5(config.path_hdf5, predicate):
            logger.info(f"point_{k} has already been calculated")
            orbitals.append(dict_input["node_MOs"])
        else:
            logger.info(f"point_{k} has been scheduled")

            # Add cell parameters from file if given
            if file_cell_parameters is not None:
                adjust_cell_parameters(general, array_cell_parameters, j)
            # Path to I/O files
            dict_input["point_dir"] = config.folders[j]
            dict_input["job_files"] = create_file_names(
                dict_input["point_dir"], k)
            dict_input["job_name"] = f'point_{k}'

            # Compute the MOs and return a new guess
            promise_qm = compute_orbitals(config, dict_input, guess_job)

            # Check if the job finishes succesfully
            promise_qm = schedule_check(promise_qm, config, dict_input)

            # Store the computation
            if config["compute_orbitals"]:
                orbitals.append(store_MOs(config, dict_input, promise_qm))
            else:
                orbitals.append(None)
            energies.append(store_enery(config, dict_input, promise_qm))

            guess_job = promise_qm

    return gather(gather(*orbitals), gather(*energies))


@schedule
def store_MOs(
        config: DictConfig, dict_input: DefaultDict[str, Any], promise_qm: PromisedObject) -> str:
    """Store the MOs in the HDF5.

    Returns
    -------
    str
        Node path in the HDF5

    """
    # Molecular Orbitals
    mos = promise_qm.orbitals

    # Store in the HDF5
    try:
        dump_orbitals_to_hdf5(mos, config.path_hdf5, config.project_name,
                              dict_input["job_name"])
    # Remove the ascii MO file
    finally:
        work_dir = promise_qm.archive['work_dir']
        path_MOs = fnmatch.filter(os.listdir(work_dir), 'mo_*MOLog')[0]
        os.remove(join(work_dir, path_MOs))

    return dict_input["node_MOs"]


def dump_orbitals_to_hdf5(
        data: InfoMO, path_hdf5: str, project_name: str, job_name: str) -> None:
    """Store the result in HDF5 format.

    Parameters
    ----------
    data
        Tuple of energies and coefficients of the molecular orbitals
    path_hdf5
        Path to the HDF5 where the MOs are stored
    project_name
        Name of the current project
    job_name
        Name of the current job

    """
    es = "cp2k/mo/eigenvalues"
    css = "cp2k/mo/coefficients"
    path_eigenvalues = join(project_name, job_name, es)
    path_coefficients = join(project_name, job_name, css)

    store_arrays_in_hdf5(path_hdf5, path_eigenvalues, data.eigenVals)
    store_arrays_in_hdf5(path_hdf5, path_coefficients, data.coeffs)


@schedule
def store_enery(
        config: DictConfig, dict_input: Dict, promise_qm: PromisedObject) -> str:
    """Store the total energy in the HDF5 file.

    Returns
    -------
    str
        Node path to the energy in the HDF5

    """
    store_arrays_in_hdf5(
        config.path_hdf5, dict_input['node_energy'], promise_qm.energy)

    logger.info(
        f"Total energy of point {dict_input['k']} is: {promise_qm.energy}")

    return dict_input["node_energy"]


def compute_orbitals(
        config: DictConfig, dict_input: Dict, guess_job: PromisedObject) -> PromisedObject:
    """Call a Quantum chemisty package to compute the MOs.

    When finish store the MOs in the HdF5 and returns a new guess.
    """

    dict_input["job_files"] = create_file_names(
        dict_input["point_dir"], dict_input["k"])

    # Calculating initial guess
    compute_guess = config.calc_new_wf_guess_on_points is not None

    # A job  is a restart if guess_job is None and the list of
    # wf guesses are not empty
    is_restart = guess_job is None and compute_guess

    pred = (dict_input['k']
            in config.calc_new_wf_guess_on_points) or is_restart

    general = config.cp2k_general_settings

    if pred:
        guess_job = prepare_job_cp2k(
            general["cp2k_settings_guess"], dict_input, guess_job)

    promise_qm = prepare_job_cp2k(
        general["cp2k_settings_main"], dict_input, guess_job)

    return promise_qm


@schedule
def schedule_check(
        promise_qm: PromisedObject, config: DictConfig, dict_input: DictConfig) -> PromisedObject:
    """Check wether a calculation finishes succesfully otherwise run a new guess."""
    job_name = dict_input["job_name"]
    point_dir = dict_input["point_dir"]

    # Warnings of the computation
    warnings = promise_qm.warnings

    # Check for SCF convergence errors
    if not config.ignore_warnings and warnings is not None and any(
            w == SCF_Convergence_Warning for msg, w in warnings.items()):
        # Report the failure
        msg = f"Job: {job_name} Finished with Warnings: {warnings}"
        logger.warning(msg)

        # recompute a new guess
        msg1 = "Computing a new wave function guess for job: {job_name}"
        logger.warning(msg1)

        # Remove the previous ascii file containing the MOs
        msg2 = f"removing file containig the previous failed MOs of {job_name}"
        logger.warning(msg2)
        path = fnmatch.filter(os.listdir(point_dir), 'mo*MOLog')[0]
        os.remove(join(point_dir, path))

        # Compute new guess at point k
        config.calc_new_wf_guess_on_points.append(dict_input["k"])
        return compute_orbitals(config, dict_input, None)
    else:
        return promise_qm


def create_point_folder(
        work_dir: PathLike, n: int, enumerate_from: int) -> List[PathLike]:
    """Create a new folder for each point in the MD trajectory."""
    folders = []
    for k in range(enumerate_from, n + enumerate_from):
        new_dir = join(work_dir, f'point_{k}')
        if os.path.exists(new_dir):
            shutil.rmtree(new_dir)
        os.makedirs(new_dir)
        folders.append(new_dir)

    return folders


def split_file_geometries(pathXYZ: PathLike) -> List[MolXYZ]:
    """Read a set of molecular geometries in xyz format."""
    # Read Cartesian Coordinates
    with open(pathXYZ) as f:
        xss = f.readlines()

    numat = int(xss[0].split()[0])
    return list(map(''.join, chunked(xss, numat + 2)))


def create_file_names(work_dir: PathLike, i: int) -> JobFiles:
    """Create a namedTuple with the name of the 4 files used for each point in the trajectory."""
    file_xyz = join(work_dir, f'coordinates_{i}.xyz')
    file_inp = join(work_dir, f'point_{i}.inp')
    file_out = join(work_dir, f'point_{i}.out')
    file_MO = join(work_dir, f'mo_coeff_{i}.out')

    return JobFiles(file_xyz, file_inp, file_out, file_MO)


def adjust_cell_parameters(
        general: DictConfig,
        array_cell_parameters: Matrix,
        j: int) -> None:
    """Adjust the cell parameters on the fly.

    If the cell parameters change during the MD simulations, adjust them
    for the molecular orbitals computation.
    """
    for s in (
        general[p] for p in (
            'cp2k_settings_main',
            'cp2k_settings_guess')):
        s.cell_parameters = array_cell_parameters[j, 2:11].reshape(
            3, 3).tolist()
        s.cell_angles = None