# HealthEnv: Compiling Longitudinal Health QA into Verifiable Computer-Use Environments

**Technical report · Draft v0.1 · 11 October 2026**

HealthEnv Contributors

## Abstract

Health question-answering benchmarks compress a domain problem into a prompt and a textual answer. Computer-use agents, by contrast, must recover evidence from an interface, maintain state across actions, produce an artifact, and satisfy workflow constraints. We introduce **HealthEnv**, a compiler and runtime that expands longitudinal health QA seeds into browser-based, stateful, and automatically verifiable computer-use tasks. A seed is compiled into (i) a synthetic longitudinal record state, (ii) an operational instruction, (iii) a constrained GUI action surface, and (iv) a hidden state-based verifier. The key design choice is a trust boundary: language models may plan or rewrite task instructions, but gold answers and reward predicates remain executable and deterministic. A dependency-free reference implementation includes a LifeAgentBench-format adapter, an OpenAI-compatible planner integration, three privacy-safe task families, and a browser workbench. In the current prototype, all 11 unit and regression tests pass; deterministic oracle states solve 3/3 compiled tasks, while evidence-omission mutations are rejected on 3/3 tasks. These experiments establish implementation correctness, not clinical validity or training benefit. We conclude with the experiments required to test whether QA-driven environment synthesis improves computer-use agents while preserving reward fidelity and medical safety.

## 1. Introduction

Longitudinal health QA and computer-use evaluation ask different questions. A QA benchmark asks whether a model can derive an answer from a record. A computer-use benchmark asks whether an agent can navigate a system, locate the right evidence, update the right state, produce the right artifact, and avoid unsafe side effects. The underlying domain relation may be shared, but the observable behavior and failure modes are not.

LifeAgentBench formalizes long-horizon and cross-dimensional reasoning over lifestyle signals and derives verifiable answers through executable queries and programs [1]. HealthAdminBench and MedCUA-Bench show that medical computer use adds another layer: cross-system coordination, document handling, interface grounding, workflow state, and safety constraints [2, 3]. Meanwhile, environment-synthesis systems such as InfiniteWeb, AutoWebWorld, GUI-GENESIS, CUA-Gym, and Gym-Anything suggest that environments—not only trajectories—are becoming a primary scaling axis [4–8].

This motivates a compiler view:

> A static QA item is a compressed specification of a world relation. Expanding it into an executable environment should make the relation observable through actions and verifiable through state.

HealthEnv is a first vertical slice of this idea. It accepts a question, answer, evidence relation, and record set; emits a task specification; serves a browser interface; and scores the resulting terminal state. The present release is intentionally narrow. It demonstrates longitudinal record review and care-note workflows, not a complete EHR, payer portal, or clinical decision-support system.

### Contributions

1. **QA-to-CUA compilation.** We define a concrete mapping from health QA seeds to stateful browser tasks with explicit actions and terminal conditions.
2. **Gold/planner separation.** Optional LLM planning can alter instruction wording but cannot create or modify the answer, evidence set, or verifier.
3. **A verifiable task IR.** The released schema separates public observations, mutable workflow state, hidden reward predicates, and generation provenance.
4. **An executable reference system.** The repository includes a dependency-free Python runtime, a longitudinal-health GUI, a LifeAgentBench-format adapter, and deterministic tests.
5. **An honest experimental boundary.** We report compiler and verifier validity checks while leaving agent-training gains, real-software transfer, and clinical validity as open empirical questions.

## 2. Problem formulation

Let a QA seed be

\[
x = (q, y, D, E, m),
\]

where \(q\) is a question, \(y\) is the answer, \(D\) is a set of longitudinal records, \(E \subseteq D\) is the evidence set, and \(m\) is task metadata. A compiler maps the seed to an interactive environment

\[
C(x) \rightarrow \mathcal{M} = (S, A, T, O, R),
\]

where \(S\) is workflow state, \(A\) is the action space, \(T\) is a deterministic transition function, \(O\) is the browser observation, and \(R\) is a state-based verifier.

The compilation is useful only if it satisfies four properties:

- **Semantic preservation:** success in the environment entails recovering the relation encoded by the QA item.
- **Action necessity:** the answer cannot be obtained by copying a visible gold label; the agent must interact with evidence and workflow state.
- **Verifier fidelity:** reward depends on the intended state, not on surface text alone.
- **Isolation:** generated tasks contain no real patient data and do not expose hidden gold state to the agent.

## 3. System design

### 3.1 Seed schema

A HealthEnv seed contains a stable id, synthetic participant id, question, answer, category, typed records, expected evidence ids, and metadata. The current compiler supports numeric comparisons, temporal aggregation, and cross-dimensional selection. Records are deliberately simple JSON objects so adapters can be written without importing a healthcare data model.

The public demo uses only synthetic records. The LifeAgentBench adapter reads a local upstream checkout and synthesizes a new record state that preserves the QA relation. This choice avoids redistributing upstream payloads from a repository for which a license was not detected during development.

### 3.2 Compiler

The deterministic compiler performs five steps:

1. validate identifiers, record uniqueness, evidence membership, and status values;
2. construct a stable task id from the benchmark and seed id;
3. create a workflow instruction that requires evidence selection, note writing, status assignment, and submission;
4. derive verifier terms from explicitly configured metadata or the answer type;
5. serialize source provenance and generation mode.

The optional planner receives only the participant id, question, category, record types, and record count. It never receives the answer or evidence ids. Its output must contain the selection, note, and submission operations; it is rejected if it includes the gold answer. Any API or validation failure falls back to the deterministic instruction.

### 3.3 Browser environment

The environment exposes a two-panel workbench. The left panel contains searchable, filterable longitudinal records. The right panel contains evidence count, care-note editor, workflow priority, and submission control. Source records are read-only. After submission, the runtime rejects all mutations until reset. Accepted actions append an audit event.

The interface is intentionally application-like rather than question-like. The instruction asks for a workflow outcome, while the answer exists only inside hidden verifier predicates.

### 3.4 Verifier

The terminal verifier contains five checks:

| Check | Weight | Current predicate |
|---|---:|---|
| Evidence selection | 0.30 | Exact equality with required record ids |
| Grounded note | 0.30 | All normalized gold terms occur in the note |
| Workflow status | 0.15 | Status equals the required value |
| Submission | 0.15 | Explicit submit action occurred |
| Safety | 0.10 | No forbidden source-state edit was recorded |

The weighted score provides process-level signal. Strict success requires every check. Exact evidence matching is the default because accepting arbitrary extra records would reward ungrounded collection. This is a starting point, not a complete semantic verifier: string containment must eventually be replaced by typed claims evaluated against executable record predicates.

### 3.5 Trust boundaries

HealthEnv separates three roles that environment-synthesis pipelines often blur:

- the **seed** defines domain truth;
- the **planner** defines how the task is communicated;
- the **verifier** defines success over state.

The planner cannot modify the verifier. The browser cannot read the verifier. The agent cannot mutate source records. The compiler logs whether an LLM was used and whether gold state remained deterministic.

## 4. Prototype evaluation

The current evaluation asks whether the released artifact is internally correct. It does not ask whether a trained CUA generalizes better.

### 4.1 Tasks

We construct three privacy-safe QA seeds:

1. a two-day oxygen-saturation comparison;
2. a three-night sleep-duration aggregation;
3. a joint activity-and-stress selection across dates.

Each seed includes distractors. Compilation produces one executable JSON task per seed.

### 4.2 Tests

We evaluate:

- schema rejection for unknown evidence;
- deterministic compilation and round-trip parsing;
- gold-answer non-leakage in default instructions;
- positive oracle execution;
- rejection of missing evidence, extra distractors, and forbidden edits;
- transactional runtime behavior after submission;
- end-to-end compilation of all three seeds.

### 4.3 Results

| Measure | Result |
|---|---:|
| Unit and regression tests | 11 / 11 pass |
| Seeds compiled | 3 / 3 |
| Oracle strict success | 3 / 3 |
| Missing-evidence mutations rejected | 3 / 3 |
| LifeAgentBench-format adapter smoke | strict success 1.0 |
| TierFlow `tierflow_pro` planner | 3 / 3; zero fallbacks; gold unchanged |
| Real headless-browser workflow | 100%; zero JS/network failures |
| Missing-evidence score | 0.70 |
| Runtime dependencies | 0 |

A score of 0.70 for an evidence-omission mutation is expected: note, status, submission, and safety checks still pass, while the 0.30 evidence check fails. This demonstrates decomposed progress scoring rather than successful task completion. The optional TierFlow path planned all three instructions with `tierflow_pro` without fallback; every artifact records `llm_used_for_gold: false`. A CDP-driven browser smoke also executes the visible checkbox, textarea, select, and submit controls, reaches 100% strict success, and records no JavaScript or network failures.

### 4.4 What these results do not show

The results do not establish that the UI resembles a deployed medical system, that the verifier captures clinical correctness, that a vision-language agent can solve the tasks, or that training on generated tasks transfers to HealthAdminBench, MedCUA-Bench, OpenEMR, or another real application. Those claims require separate experiments.

## 5. Relation to prior work

### Health reasoning benchmarks

LifeAgentBench contains 22,573 questions targeting long-horizon, cross-dimensional, and multi-user lifestyle reasoning, with answers derived through executable queries and programs [1]. HealthEnv uses the resulting QA relation as a seed for interaction rather than as the final evaluation surface.

### Medical computer-use benchmarks

HealthAdminBench provides four deterministic web environments and 135 expert-designed healthcare administration tasks, decomposed into 1,698 evaluation points [2]. MedCUA-Bench covers 18 clinical scenarios across 10 medical domains and evaluates task completion plus five clinical safety dimensions [3]. These works define the target standard for realistic workflows and safety-aware scoring. HealthEnv differs in source and purpose: it starts from existing QA relations and studies automatic expansion.

### Environment synthesis

InfiniteWeb combines unified specification and task-centric test-driven development to generate functional websites and evaluators [4]. AutoWebWorld represents websites as finite-state machines, making transitions and goal states programmatically verifiable [5]. GUI-GENESIS reconstructs efficient GUI environments with verifiable rewards [6]. CUA-Gym co-generates instructions, environment states, and reward functions, while separating generator and discriminator roles [7]. Gym-Anything treats software-environment creation as a multi-agent build-and-audit problem [8]. FaraGen1.5 organizes generation around environments, solvers, and complementary verifiers [9].

HealthEnv adopts their shared principle—environment generation must be coupled to verification—but introduces a domain-specific seed: executable health QA.

## 6. Research agenda

A full paper should test four hypotheses.

**H1: Expansion fidelity.** Independent domain experts should judge whether a generated workflow preserves the original QA relation and avoids introducing unsupported clinical implications.

**H2: Verifier validity.** Counterexample policies should fail. This includes selecting all records, copying distractor values, exploiting note substrings, mutating hidden state, and satisfying individual checks in an invalid order.

**H3: Environment diversity.** Holding trajectory count constant, training across more independently generated interfaces and state layouts should improve held-out GUI robustness more than replaying more trajectories in fewer environments.

**H4: Transfer.** Training on QA-expanded synthetic environments should improve performance on held-out medical CUA tasks without increasing clinically consequential errors.

A credible evaluation would use train/test separation by participant, question template, metric family, interface skin, and workflow; compare deterministic-only and LLM-assisted compilation; and report both strict success and safety violations.

## 7. Safety, ethics, and governance

HealthEnv can create high-stakes-looking interfaces. That makes scope control essential.

- The public artifact contains synthetic data only.
- The action space excludes diagnosis, treatment, prescription, and communication with real patients.
- Demonstrations should be labeled as simulations.
- Dataset licenses and data-use agreements must be checked before conversion.
- PHI must not be sent to external model APIs.
- Realistic environments need red-team evaluation for reward hacking, unsafe documentation, and automation bias.
- Human review remains necessary before any deployment-adjacent use.

The project should be evaluated as research infrastructure for agent learning, not as a healthcare automation product.

## 8. Limitations

The prototype has one browser application, a narrow record schema, handcrafted action primitives, and term-based note checking. It does not model authentication, role permissions, cross-application document transfer, asynchronous workflows, or clinical ontologies. Its LifeAgentBench adapter currently handles dated numeric comparison items and synthesizes evidence states rather than reconstructing the original database. The demo sample is too small for performance conclusions. No CUA model has yet been benchmarked in the released report.

These limitations are not cosmetic. They define the next implementation milestones and the difference between a working compiler prototype and a publishable empirical result.

## 9. Conclusion

HealthEnv demonstrates a concrete route from static health QA to executable computer-use environments. The central mechanism is not the UI generator alone; it is the separation of seed truth, planner language, runtime state, and verifier logic. The released vertical slice establishes that this separation can be implemented, tested, and audited with minimal infrastructure. The next question is empirical: whether scaling this compilation process yields environments that are diverse enough to train agents and faithful enough to trust.

## References

1. Ye Tian, Zihao Wang, Onat Gungor, Xiaoran Fan, and Tajana Rosing. “LifeAgentBench: Benchmarking LLMs for Long-Horizon, Cross-Dimensional Lifestyle Health Reasoning.” arXiv:2601.13880, 2026. <https://arxiv.org/abs/2601.13880>
2. Suhana Bedi et al. “HealthAdminBench: Evaluating Computer-Use Agents on Healthcare Administration Tasks.” arXiv:2604.09937, 2026. <https://arxiv.org/abs/2604.09937>
3. Jia Yu, Zilong Wang, Xinyang Jiang, Dongsheng Li, and Shuo Wang. “MedCUA-Bench: A Screenshot-Only Benchmark for Clinical Computer-Use Agents.” arXiv:2606.03203, 2026. <https://arxiv.org/abs/2606.03203>
4. Ziyun Zhang et al. “InfiniteWeb: Scalable Web Environment Synthesis for GUI Agent Training.” arXiv:2601.04126, 2026. <https://arxiv.org/abs/2601.04126>
5. Yifan Wu et al. “AutoWebWorld: Synthesizing Infinite Verifiable Web Environments via Finite State Machines.” arXiv:2602.14296, 2026. <https://arxiv.org/abs/2602.14296>
6. Yuan Cao et al. “GUI-GENESIS: Automated Synthesis of Efficient Environments with Verifiable Rewards for GUI Agent Post-Training.” arXiv:2602.14093, 2026. <https://arxiv.org/abs/2602.14093>
7. Bowen Wang et al. “CUA-Gym: Scaling Verifiable Training Environments and Tasks for Computer-Use Agents.” arXiv:2605.25624, 2026. <https://arxiv.org/abs/2605.25624>
8. Pranjal Aggarwal, Graham Neubig, and Sean Welleck. “Gym-Anything: Turn any Software into an Agent Environment.” arXiv:2604.06126, 2026. <https://arxiv.org/abs/2604.06126>
9. Ahmed Awadallah et al. “Fara-1.5: Scalable Learning Environments for Computer Use Agents.” arXiv:2606.20785, 2026. <https://arxiv.org/abs/2606.20785>
