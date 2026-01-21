#!/bin/bash

echo "Running all three versions of TSVC"

compiler="intel"

tsvc_base="TSVC_2_intel_remarks"
tsvc_base_out_file="tsvc_intel_base_run.txt"

tsvc_no_remarks="TSVC_2_intel_no_remarks_opt"
tsvc_no_remarks_out_file="tsvc_intel_no_remarks_run.txt"

tsvc_remarks="TSVC_2_intel_remarks_opt"
tsvc_remarks_out_file="tsvc_intel_remarks_run.txt"

log_file="tsvc_intel_run_log.txt"

if [ $compiler = "intel" ]; then
	echo "Sourcing ICX"
	source ~/tank/intel/oneapi/compiler/latest/env/vars.sh &> $log_file
	pushd ./TSVC_2_intel_remarks/ &> $log_file
fi

echo "Cleaning TSVC+Base"
make clean &> $log_file
rm -r bin &> $log_file
echo "Compiling base"
make COMPILER=$compiler &> $log_file
echo "Running base"
./bin/intel/tsvc_vec_relaxed > $tsvc_base_out_file
popd &> $log_file

pushd ./TSVC_2_intel_no_remarks_opt/ &> $log_file
echo "Cleaning TSVC+NoRemarks"
make clean &> $log_file
rm -r bin &> $log_file
echo "Compiling Intel+NoRemarks"
make COMPILER=intel &> $log_file
echo "Running Intel+NoRemarks"
./bin/intel/tsvc_vec_relaxed > $tsvc_no_remarks_out_file
popd &> $log_file

pushd ./TSVC_2_intel_remarks_opt/ &> $log_file
echo "Cleaning TSVC+Remarks"
make clean &> $log_file
rm -r bin &> $log_file
echo "Compiling Intel+Remarks"
make COMPILER=intel &> $log_file
echo "Running Intel+Remarks"
./bin/intel/tsvc_vec_relaxed > $tsvc_remarks_out_file
popd &> $log_file

echo "Done"
