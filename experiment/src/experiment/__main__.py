import sys

from experiment.experiment import Experiment


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: python -m experiment <config.json>", file=sys.stderr)
        sys.exit(1)
    experiment = Experiment(sys.argv[1])
    experiment.start_experiment()
    experiment.write_out_results()


if __name__ == "__main__":
    main()
