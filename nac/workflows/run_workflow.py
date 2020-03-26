"""Comman line interface to run the workflows."""

import argparse
import logging
import os

import yaml

from nac.workflows import (workflow_crystal_orbital_overlap_population,
                           workflow_derivative_couplings,
                           workflow_single_points, workflow_stddft)
from nac.workflows.input_validation import process_input
from nac.workflows.workflow_ipr import workflow_ipr

logger = logging.getLogger(__name__)

msg = "namd.py -i input"

parser = argparse.ArgumentParser(description=msg)
parser.add_argument('-i', required=True,
                    help="Input file in YAML format")


dict_workflows = {
    'absorption_spectrum': workflow_stddft,
    'derivative_couplings': workflow_derivative_couplings,
    'single_points': workflow_single_points,
    'ipr_calculation': workflow_ipr,
    'coop_calculation': workflow_crystal_orbital_overlap_population}


def main():
    """Parse the command line arguments and run workflow."""
    args = parser.parse_args()
    input_file = args.i
    with open(input_file, 'r') as f:
        dict_input = yaml.load(f, Loader=yaml.FullLoader)
    if 'workflow' not in dict_input:
        raise RuntimeError(
            "The name of the workflow is required in the input file")
    else:
        workflow_name = dict_input['workflow']

    # Read and process input
    inp = process_input(input_file, workflow_name)

    # run workflow
    function = dict_workflows[workflow_name]

    logger.info(f"Running worflow using: {os.path.abspath(input_file)}")
    function(inp)


if __name__ == "__main__":
    main()
