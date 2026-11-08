import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.report import fmt
from src.testing.test_framework import AmmeterTestFramework


def main():
    with AmmeterTestFramework() as framework:
        results = {}
        for ammeter_type in ["greenlee", "entes", "circutor"]:
            print(f"Testing {ammeter_type} ammeter...")
            results[ammeter_type] = framework.run_test(ammeter_type)

        ranking = framework.compare_runs([run["run_id"] for run in results.values()])

    for ammeter_type, result in results.items():
        stats = result["statistics"]
        print(f"\nResults for {ammeter_type}: {result['status']} ({stats['count']} readings)")
        print(f"  mean {fmt(stats.get('mean'))} A, median {fmt(stats.get('median'))} A, "
              f"std {fmt(stats.get('std_dev'))} A, min {fmt(stats.get('min'))} A, max {fmt(stats.get('max'))} A")
        print(f"  saved as {result['run_id']}")
    print(f"\nMost reliable in this test: {ranking['most_reliable'] or 'no conclusion, ' + ranking['conclusion']}")


if __name__ == "__main__":
    main()
