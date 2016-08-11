__author__ = "Felipe Zapata"

__all__ = ["calculate_mos", "create_dict_CGFs", "create_point_folder",
           "split_file_geometries"]

# ================> Python Standard  and third-party <==========
from collections import namedtuple
from noodles import gather
from os.path import join

import h5py
import os

# ==================> Internal modules <==========
from nac.basisSet.basisNormalization import createNormalizedCGFs
from nac.schedule.scheduleCp2k import prepare_job_cp2k
from qmworks.common import InputKey
from qmworks.hdf5.quantumHDF5 import (cp2k2hdf5, turbomole2hdf5)
from qmworks.utils import (chunksOf, flatten)


# ==============================<>=========================
# Tuple contanining file paths
JobFiles = namedtuple("JobFiles", ("get_xyz", "get_inp", "get_out", "get_MO"))

# ==============================> Tasks <=====================================


def calculate_mos(package_name, all_geometries, project_name, path_hdf5, folders,
                  package_args, guess_args=None,
                  calc_new_wf_guess_on_points=[0], enumerate_from=0,
                  nHOMOS=100, nLUMOS=100, package_config=None):
    """
    Look for the MO in the HDF5 file if they do not exists calculate them by
    splitting the jobs in batches given by the ``restart_chunk`` variables.
    Only the first job is calculated from scratch while the rest of the
    batch uses as guess the wave function of the first calculation in
    the batch.

    :param all_geometries: list of molecular geometries
    :type all_geometries: String list
    :param project_name: Name of the project used as root path for storing
    data in HDF5.
    :type project_name: String
    :param path_hdf5: Path to the HDF5 file that contains the
    numerical results.
    :type path_hdf5: String
    :param folders: path to the directories containing the MO outputs
    :type folders: String list
    :param package_args: Settings for the job to run.
    :type package_args: Settings
    :param calc_new_wf_guess_on_points: Calculate a new Wave function guess in
    each of the geometries indicated. By Default only an initial guess is
    computed.
    :type calc_new_wf_guess_on_points: [Int]
    :param enumerate_from: Number from where to start enumerating the folders
    create for each point in the MD
    :type enumerate_from: Int
    :returns: path to nodes in the HDF5 file to MO energies
    and MO coefficients.
    """
    def create_properties_path(i):
        """
        Path inside HDF5 where the data is stored
        """
        rs = join(project_name, 'point_{}'.format(i), package_name, 'mo')
        return [join(rs, 'eigenvalues'), join(rs, 'coefficients')]

    def search_data_in_hdf5(i):
        """
        Search if the node exists in the HDF5 file.
        """
        paths_to_prop = create_properties_path(i)

        with h5py.File(path_hdf5, 'r') as f5:
            if isinstance(paths_to_prop, list):
                pred = all(path in f5 for path in paths_to_prop)
            else:
                pred = paths_to_prop in f5

        return paths_to_prop if pred else None

    path_to_orbitals = []  # list to the nodes in the HDF5 containing the MOs

    # First calculation has no initial guess
    guess_job = None

    # calculate the rest of the job using the previous point as initial guess
    for j, gs in enumerate(all_geometries):
        k = j + enumerate_from
        paths_to_prop = search_data_in_hdf5(k)

        # If the MOs are already store in the HDF5 format return the path
        # to them and skip the calculation
        if paths_to_prop is not None:
            path_to_orbitals.append(paths_to_prop)
        else:
            point_dir = folders[j]
            job_files = create_file_names(point_dir, k)
            # Calculating initial guess
            if k in calc_new_wf_guess_on_points:
                guess_job = call_schedule_qm(package_name, guess_args, path_hdf5,
                                             point_dir, job_files, k, gs,
                                             nHOMOS, nLUMOS,
                                             project_name=project_name,
                                             guess_job=guess_job,
                                             store_in_hdf5=False,
                                             package_config=package_config)

            promise_qm = call_schedule_qm(package_name, package_args,
                                          path_hdf5, point_dir, job_files,
                                          k, gs, nHOMOS, nLUMOS,
                                          project_name=project_name,
                                          guess_job=guess_job,
                                          package_config=package_config)
            path_to_orbitals.append(promise_qm.orbitals)
            guess_job = promise_qm

    return gather(*path_to_orbitals)


def call_schedule_qm(packageName, package_args, path_hdf5, point_dir,
                     job_files, k, geometry, nHOMOS, nLUMOS,
                     project_name=None, guess_job=None,
                     store_in_hdf5=True, package_config=None):
    """
    Call an external computational chemistry software to do some calculations

    :param package_name: Name of the package to run the QM simulations.
    :type  package_name: String
    :param package_args: Specific settings for the package
    :type package_args: Settings
    :param path_hdf5: Path to the HDF5 file that contains the
    numerical results.
    type path_hdf5: String
    :param point_dir: path to the directory where the output is written.
    :type point_dir: String
    :param job_files: Tuple containing the absolute path to IO files.
    :type job_files: NamedTuple
    :param k: current point being calculate in the MD
    :type k: Int
    :param geometry: Molecular geometry
    :type geometry: String
    :param nHOMOS: number of HOMOS to store in HDF5.
    :type nHOMOS: Int
    :param nLUMOS: number of HOMOS to store in HDF5.
    :type nLUMOS: Int
    :param package_config: Parameters required by the Package.
    :type package_config: Dict
    :returns: promise QMWORK
    """
    prepare_and_schedule = {'cp2k': prepare_job_cp2k}

    job = prepare_and_schedule[packageName](geometry, job_files, package_args,
                                            k, point_dir,
                                            project_name=project_name,
                                            hdf5_file=path_hdf5,
                                            wfn_restart_job=guess_job,
                                            store_in_hdf5=store_in_hdf5,
                                            nHOMOS=nHOMOS, nLUMOS=nLUMOS,
                                            package_config=package_config)

    return job


def create_point_folder(work_dir, n, enumerate_from):
    """
    Create a new folder for each point in the MD trajectory.

    :returns: Paths lists.
    """
    folders = []
    for k in range(enumerate_from, n + enumerate_from):
        new_dir = join(work_dir, 'point_{}'.format(k))
        if not os.path.exists(new_dir):
            os.makedirs(new_dir)
        folders.append(new_dir)

    return folders


def split_file_geometries(pathXYZ):
    """
    Reads a set of molecular geometries in xyz format and returns
    a list of string, where is element a molecular geometry
    
    :returns: String list containing the molecular geometries.
    """
    # Read Cartesian Coordinates
    with open(pathXYZ) as f:
        xss = f.readlines()

    numat = int(xss[0].split()[0])
    return list(map(flatten, chunksOf(xss, numat + 2)))


def create_dict_CGFs(path_hdf5, basisname, xyz, package_name='cp2k',
                     package_config=None):
    """
    Try to read the basis from the HDF5 otherwise read it from a file and store
    it in the HDF5 file. Finally, it reads the basis Set from HDF5 and calculate
    the CGF for each atom.

    :param path_hdf5: Path to the HDF5 file that contains the
    numerical results.
    type path_hdf5: String
    :param basisname: Name of the Gaussian basis set.
    :type basisname: String
    :param xyz: List of Atoms.
    :type xyz: [nac.common.AtomXYZ]
    """
    functions = {'cp2k': cp2k2hdf5, 'turbomole': turbomole2hdf5}

    basis_location = join(package_name, 'basis')
    with h5py.File(path_hdf5, chunks=True) as f5:
        if basis_location not in f5:
            # Search Path to the file containing the basis set
            pathBasis = package_config["basis"]
            keyBasis = InputKey("basis", [pathBasis])
            # Store the basis sets
            functions[package_name](f5, [keyBasis])

        return createNormalizedCGFs(f5, basisname, package_name, xyz)


def create_file_names(work_dir, i):
    """
    Creates a namedTuple with the name of the 4 files used
    for each point in the trajectory
    
    :returns: Namedtuple containing the IO files
    """
    file_xyz = join(work_dir, 'coordinates_{}.xyz'.format(i))
    file_inp = join(work_dir, 'point_{}.inp'.format(i))
    file_out = join(work_dir, 'point_{}.out'.format(i))
    file_MO = join(work_dir, 'mo_coeff_{}.out'.format(i))

    return JobFiles(file_xyz, file_inp, file_out, file_MO)

# ============<>===============

