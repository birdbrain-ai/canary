#!/usr/bin/env python3
"""
Analyze TSVC benchmark results to calculate speedup and verify checksums.
Compares base and optimized runs.
"""

import sys
import argparse
from typing import Dict, Tuple


def parse_log_file(filename: str) -> Dict[str, Tuple[float, float]]:
    """
    Parse a TSVC log file and extract loop names, times, and checksums.

    Returns:
        Dict mapping loop name to (time, checksum)
    """
    results = {}

    with open(filename, 'r') as f:
        for line in f:
            # Skip header and empty lines
            if 'Loop' in line or 'Time' in line or not line.strip():
                continue

            # Parse line format: "loop_name    time    checksum"
            parts = line.split()
            if len(parts) >= 3:
                loop_name = parts[0]
                try:
                    time = float(parts[1])
                    checksum = float(parts[2])
                    results[loop_name] = (time, checksum)
                except (ValueError, IndexError):
                    # Skip lines that don't parse correctly
                    continue

    return results


def analyze_speedup(base_file: str, opt_file: str, output_file: str = None):
    """
    Extract benchmark results and output to CSV format.
    """
    # Parse both files
    base_results = parse_log_file(base_file)
    opt_results = parse_log_file(opt_file)

    # Determine output destination
    if output_file:
        f = open(output_file, 'w')
    else:
        f = sys.stdout

    try:
        # Print CSV header
        print("Loop,Base_Time,Opt_Time,Base_Checksum,Opt_Checksum", file=f)

        # Process each loop in base results
        for loop_name in sorted(base_results.keys()):
            base_time, base_checksum = base_results[loop_name]

            if loop_name not in opt_results:
                print(f"{loop_name},{base_time},,{base_checksum},", file=f)
                continue

            opt_time, opt_checksum = opt_results[loop_name]
            print(f"{loop_name},{base_time},{opt_time},{base_checksum},{opt_checksum}", file=f)

    finally:
        if output_file:
            f.close()
            print(f"Results written to: {output_file}", file=sys.stderr)


def main():
    """Main entry point with argument parsing."""
    parser = argparse.ArgumentParser(
        description='Analyze TSVC benchmark results to calculate speedup and verify checksums.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  %(prog)s base.txt opt.txt                    # Output CSV to stdout
  %(prog)s base.txt opt.txt -o results.csv     # Save CSV to file
  %(prog)s base.txt opt.txt > results.csv      # Redirect output to file
        '''
    )

    parser.add_argument('base_file',
                        help='Path to base (unoptimized) benchmark results file')
    parser.add_argument('opt_file',
                        help='Path to optimized benchmark results file')
    parser.add_argument('-o', '--output',
                        metavar='FILE',
                        help='Output CSV file (default: stdout)')

    args = parser.parse_args()

    # Check if files exist
    import os
    for filepath in [args.base_file, args.opt_file]:
        if not os.path.exists(filepath):
            print(f"Error: File not found: {filepath}", file=sys.stderr)
            sys.exit(1)

    analyze_speedup(args.base_file, args.opt_file, args.output)


if __name__ == "__main__":
    main()
