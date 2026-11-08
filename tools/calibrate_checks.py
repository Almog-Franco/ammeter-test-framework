"""Derives the expected values in config.yaml and measures how the model and drift checks behave.

It simulates the three emulators straight from the physics and input ranges in the README, not from their code,
so it is an independent reference. Needs numpy, which comes with matplotlib.

    python tools/calibrate_checks.py [--runs 200000]
"""
import argparse

import numpy as np

rng = np.random.default_rng(12345)


def greenlee(shape):
    return rng.uniform(1, 10, shape) / rng.uniform(0.1, 100, shape)


def entes(shape):
    return rng.uniform(0.01, 0.1, shape) * rng.uniform(500, 2000, shape)


def circutor(shape):
    return rng.uniform(0.001, 0.01, shape) * rng.uniform(0.1, 1.0, shape + (10,)).sum(axis=-1)


MODELS = {"greenlee": greenlee, "entes": entes, "circutor": circutor}


def model_z(x, log_mean, log_std):
    return (np.log(x).mean(axis=1) - log_mean) / (log_std / np.sqrt(x.shape[1]))


def drift_t(x):
    t = np.arange(x.shape[1], dtype=float) - (x.shape[1] - 1) / 2
    centred = x - x.mean(axis=1, keepdims=True)
    slope = centred @ t / (t @ t)
    residuals = centred - slope[:, None] * t
    return slope / np.sqrt((residuals ** 2).sum(axis=1) / (x.shape[1] - 2) / (t @ t))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=200_000, help="simulated runs per case")
    runs = parser.parse_args().runs

    print("Expected values (4,000,000 simulated readings each)")
    reference = {}
    for name, model in MODELS.items():
        x = model((4_000_000,))
        logs = np.log(x)
        reference[name] = (logs.mean(), logs.std(ddof=1))
        print(f"  {name:9} mean {x.mean():.5g}  cv {x.std(ddof=1) / x.mean():.4f}  "
              f"geo_mean {np.exp(logs.mean()):.5g}  log_std {logs.std(ddof=1):.4f}")

    print(f"\nFalse alarms on clean data ({runs} runs each): share of runs over the limit")
    for n in (10, 30, 50, 100):
        for name, model in MODELS.items():
            x = model((runs, n))
            z, t = np.abs(model_z(x, *reference[name])), np.abs(drift_t(x))
            print(f"  n={n:3} {name:9} model |z|>5: {np.mean(z > 5):.1e}   drift |t|>5: {np.mean(t > 5):.1e}")

    print(f"\nDetection with 50 readings ({runs // 10} runs each): share of runs caught")
    for name, model in MODELS.items():
        x = model((runs // 10, 50))
        for label, faulty in [("x0.5 calibration", x * 0.5), ("x0.8 calibration", x * 0.8),
                              ("+100% linear drift", x * (1 + np.linspace(0, 1, 50)))]:
            z, t = np.abs(model_z(faulty, *reference[name])), np.abs(drift_t(faulty))
            print(f"  {name:9} {label:20} model check {np.mean(z > 5):.3f}   drift check {np.mean(t > 5):.3f}")


if __name__ == "__main__":
    main()
