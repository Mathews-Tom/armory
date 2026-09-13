# Contributing

Transport adapters are frozen while the maintainers settle the transport protocol. Do not propose a new transport as a first contribution.

A permitted starter change is a focused title validator in `src/queuebox/validators.py` with behavior coverage in `tests/service_cases.yaml`. Preserve the current `ValueError` boundary used by callers.
