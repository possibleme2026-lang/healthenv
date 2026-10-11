# Contributing

HealthEnv is an early research artifact. Contributions should preserve three invariants:

1. no real patient data or credentials in tests, examples, or issues;
2. LLM-generated content must not define hidden gold state;
3. every verifier change needs a positive control and at least one failing mutation.

## Local checks

```bash
python -m pip install -e ".[dev]"
python -m unittest discover -s tests -v
python tools/check_readme_i18n.py
python -m unittest discover -s tools -p "test_*.py" -v
python tools/check_secrets.py
ruff check .
mypy src/healthenv
```

Open a focused pull request with a summary, test evidence, and any data-license implications.
