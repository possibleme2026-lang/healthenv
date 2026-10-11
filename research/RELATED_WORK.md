# Related work and reference-code ledger

Checked on **2026-10-11**. Numbers below are included only when they were recoverable from a first-party paper page or official repository. “Reference” means architectural study, not code reuse.

## Primary papers

| Work | Verified artifact | Relevant mechanism | Relationship to HealthEnv |
|---|---|---|---|
| LifeAgentBench | [arXiv:2601.13880](https://arxiv.org/abs/2601.13880), [repository](https://github.com/gdfwj/LifeAgentBench) | 22,573 longitudinal lifestyle-health QA items; executable query/program-derived answers | QA seed format and long-horizon reasoning source |
| HealthAdminBench | [arXiv:2604.09937](https://arxiv.org/abs/2604.09937), [repository](https://github.com/som-shahlab/health-admin-bench) | Four deterministic web environments; 135 tasks; 1,698 evaluation points | Target standard for medical workflow realism and subtask verification |
| MedCUA-Bench | [arXiv:2606.03203](https://arxiv.org/abs/2606.03203), [repository](https://github.com/Jia7878/MedCUA-BenchMark) | 18 scenarios across 10 medical domains; deterministic completion and five safety dimensions | Target standard for clinical GUI and safety evaluation |
| InfiniteWeb | [arXiv:2601.04126](https://arxiv.org/abs/2601.04126), [repository](https://github.com/microsoft/FIVE-UI-Evol) | Unified specification, task-centric TDD, evaluator generation | Specification-to-site compiler reference |
| AutoWebWorld | [arXiv:2602.14296](https://arxiv.org/abs/2602.14296), [repository](https://github.com/Evanwu1125/AutoWebWorld) | Explicit FSM states, actions, transitions, and goal-state verification | Programmatic transition and goal representation |
| GUI-GENESIS | [arXiv:2602.14093](https://arxiv.org/abs/2602.14093) | Efficient GUI environment synthesis with verifiable rewards | Lightweight generated application reference |
| CUA-Gym | [arXiv:2605.25624](https://arxiv.org/abs/2605.25624), [repository](https://github.com/xlang-ai/CUA-Gym) | Co-generation of instruction, state, and reward with generator/discriminator separation | Independent reward-authoring and adversarial filtering reference |
| Gym-Anything | [arXiv:2604.06126](https://arxiv.org/abs/2604.06126), [repository](https://github.com/cmu-l3/gym-anything) | Build agent plus independent audit agent; software-to-environment pipeline | Environment setup evidence and audit pattern |
| Fara-1.5 | [arXiv:2606.20785](https://arxiv.org/abs/2606.20785), [repository](https://github.com/microsoft/fara) | Environment, solver, and verifier modules with multiple verifier types | Modular trajectory-harvesting reference |

## License boundary

The LifeAgentBench repository returned no license through GitHub's license endpoint when checked. HealthEnv therefore ships an adapter but no copied upstream records. The public demo is synthetic. Other repositories remain external references under their own licenses; none are vendored into HealthEnv.

## Claims deliberately not made

- Similar architecture does not imply copied code.
- A public repository does not imply permission to redistribute its data.
- Passing the prototype verifier does not imply clinical correctness.
- Three demo tasks do not establish a scaling law or downstream training benefit.

A machine-readable clone ledger with commit hashes is generated in `artifacts/reference_repositories.json` after the shallow reference checkouts complete.
