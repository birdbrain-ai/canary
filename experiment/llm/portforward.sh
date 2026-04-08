#!/bin/bash
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --mem=100M
#SBATCH --cpus-per-task=1
#SBATCH --output=%j-%x.out

# $1 = compute node hostname, $2 = port
ssh -N -R 0:$1:$2 slurm01.cs.northwestern.edu
