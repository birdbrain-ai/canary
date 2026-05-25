# import argparse

def main():
    # This is where the argparse logic goes
    # First argument: path to a CSV that has success counts for yes remarks configurations
    # Second argument: path to a CSV that has success counts for no remarks configuration

    # 1. Import both CSVs as pandas dataframes. Both CSVs follow a clear structure.
    # model,kernel_id,diagnostic,temperature,success_count

    # 1.1. Assert that every row in the No Remarks CSV has an empty diagnostic column.

    # 2. Reduce both DFs to the correct diagnostic configurations
    # Yes Remarks CSV should be filtered to rows with empty diagnostic values. This is only the experiments run with all the remarks.
    # No Remarks CSV should be filtered to rows with empty diagnostic values (so it stays the same as the above one).

    # 3. Compute vectorization success rate for each DF.

    # 4. Do a paired T-test.
    # 4.1. Group by diagnostic.
    # 4.1.1. Import coverage.csv from benchmarks/coverage.csv
    # 4.1.2. Use that to produce a DFs with the following schema.
    # diagnostic,success_rate_yes_remarks,success_rate_no_remarks
    # 4.2 Do a paired T-test on both DFs. 

    pass

if __name__ == "__main__":
    main()
