#!/bin/bash

for temp in "0.2" "0.8" "1.2"; do
	for config in "1" "2" "3" "4" "5" "6"; do
		python3 analysis/parse_vectorization_results.py canary/results/3-21-ablation-study/t${temp}/2026-03*t${temp}_ablation_config_${config}/TSVC_2_vec/ >> ../ai-pragmas-plots/data/3-21-ablation-study/t${temp}/config_${config}.csv
	done
done
