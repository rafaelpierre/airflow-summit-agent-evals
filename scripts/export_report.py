#!/usr/bin/env python3
import argparse
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from include.text2sql_eval.phoenix_adapter import PhoenixStore
from include.text2sql_eval.reporting import build_report, export


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--experiment-id', required=True)
    p.add_argument('--output-dir', required=True)
    p.add_argument('--evaluation-config-id')
    p.add_argument('--baseline-experiment-id')
    p.add_argument('--baseline-evaluation-config-id')
    a = p.parse_args()
    report = build_report(PhoenixStore(), a.experiment_id, a.evaluation_config_id,
                          a.baseline_experiment_id, a.baseline_evaluation_config_id)
    export(report, a.output_dir)
    print('Exported report.html, summary.json and failures.json; complete:', report['summary']['complete'])


if __name__ == '__main__':
    main()
