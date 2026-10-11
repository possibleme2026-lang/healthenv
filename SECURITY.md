# Security Policy

## Reporting

Do not open a public issue for credential exposure, patient-data exposure, verifier bypass, or unsafe state mutation. Report privately through GitHub Security Advisories for this repository.

## In scope

- credentials committed to source or generated artifacts;
- exposure of hidden verifier state through the public HTTP surface;
- mutation of source health records through an unintended action;
- a verifier bypass that yields strict success without satisfying the intended task;
- unsafe handling of externally supplied dataset paths.

## Design behavior that is not a vulnerability by itself

- the public demo uses synthetic records;
- audit logs are append-only within a task episode;
- submission locks workflow state until reset;
- a failed subtask can still receive partial score while strict success remains false.

No real protected health information should ever be submitted to this project or sent to an external model endpoint.
