#!/bin/bash

# Arguments
SUITE="$1"
shift

EXTRA_ARGS=()
while [[ "$#" -gt 0 ]]
do
    case $1 in
        --) # marks the end of arguments and beginning of kernels
            shift
            break
            ;;
        *)
            EXTRA_ARGS+=("$1")
            shift
            ;;
    esac
done

KERNELS_DIR=${SUITE}/kernels

if [[ "$#" -gt 0 ]]
then
    # Collect the provided kernel arguments.
    KERNELS="$@"
    NKERNELS="$#"
else
    # If no kernels were provided, collect all of them from the suite.
    KERNELS="$(ls ${KERNELS_DIR}/)"
    NKERNELS="$(ls ${KERNELS_DIR}/ | wc -l)"
fi

# TODO: Check that the user is happy with this run config.
echo "Running ${NKERNELS} kernels in ${SUITE}"

# Set up the output directory
TIMESTAMP=$(date +"%Y-%m-%d_%H-%M-%S_%s")

OUT=out/${TIMESTAMP}
mkdir -p ${OUT}

RES=${OUT}/result.csv
echo "kernel,attempts,result,reason" > ${RES}

# Configure
export INCLUDES="-I${SUITE}/include"
export CFLAGS="-O3"
export CC="clang"
export REMARKS="${SUITE}/bin/clang-remarks"
export TV="/tank/tommy/alive2/install/Release/bin/alive-tv"

# Run all kernels
counter=1
for kernel in ${KERNELS}
do
    echo "[${counter}/${NKERNELS}] $(basename ${kernel})"
    
    uv run canary ${EXTRA_ARGS[@]} -v --kernel ${KERNELS_DIR}/${kernel}/kernel.c --model gemma4:latest --api-url http://localhost:11434/v1 >> ${RES} || { echo "FAILURE!" ; exit 1; }

    ((counter++))
done

echo "Done! Results in ${RES}"
