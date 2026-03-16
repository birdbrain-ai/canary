#!/bin/bash

TEMP="0.8"

CLANG_NO_REMARKS_DIR="TSVC_2_0306_afternoon_temp_${TEMP}_trials_10_clang_no_remarks"
# CLANG_REMARKS_DIR="TSVC_2_0305_afternoon_temp_${TEMP}_trials_10_clang_baseremarks"
# INTEL_NO_REMARKS_DIR="TSVC_2_0202_afternoon_temp_${TEMP}_trials_10_intel_no_remarks"
# INTEL_REMARKS_DIR="TSVC_2_0202_afternoon_temp_${TEMP}_trials_10_intel_remarks"

cp -r TSVC_2_default_clang_no_remarks_0305/ /pool/akash/"$CLANG_NO_REMARKS_DIR"
# cp -r TSVC_2_default_clang_remarks_0305/ /pool/akash/"$CLANG_REMARKS_DIR"
# cp -r TSVC_2_default_0202/ /pool/akash/"$INTEL_NO_REMARKS_DIR"
# cp -r TSVC_2_default_0202/ /pool/akash/"$INTEL_REMARKS_DIR"

./ai-pragmas/codaim_vectorizer.sh -a /pool/akash/ai-pragmas -cn /pool/akash/"$CLANG_NO_REMARKS_DIR" -cr /pool/akash/"$CLANG_REMARKS_DIR" -in /pool/akash/"$INTEL_NO_REMARKS_DIR" -ir /pool/akash/"$INTEL_REMARKS_DIR" -t "$TEMP" -n 10








# TEMP="0.8"

# CLANG_REMARKS_DIR="TSVC_2_0204_afternoon_temp_${TEMP}_trials_10_clang_remarks"

# cp -r TSVC_2_default_0202/ /pool/akash/"$CLANG_REMARKS_DIR"

# ./ai-pragmas/codaim_vectorizer.sh -a /pool/akash/ai-pragmas -cn /pool/akash/"$CLANG_NO_REMARKS_DIR" -cr /pool/akash/"$CLANG_REMARKS_DIR" -in /pool/akash/"$INTEL_NO_REMARKS_DIR" -ir /pool/akash/"$INTEL_REMARKS_DIR" -t "$TEMP" -n 10
