# Contracts for brownfield tasks

A brownfield task starts with an existing application. Its current public behavior is the baseline;
the task adds or changes one focused capability without breaking unrelated behavior.

## When a contract is useful

Add a public contract when the changed boundary needs a precise, stable description for the
candidate and verifier. This might be a new or changed HTTP route, event, UI flow, or compatibility
interface. Do not add a contract just because the application has an API or a user interface.

## What to document

Document only the affected surface:

- inputs, outputs, and error behavior;
- authentication and authorization expectations;
- relevant state transitions and persistence-visible behavior;
- compatibility rules that existing callers must continue to rely on;
- stable UI hooks and observable states, when the task changes a browser flow.

Keep implementation choices open. Do not prescribe framework components, database tables, internal
module names, hidden test cases, or scoring rules.

## Candidate package layout

The existing application is placed under `public/codebase/`. Add only task-relevant contracts:

```text
tasks/<task-id>/
├── instruction.md
└── public/
    ├── codebase/
    └── contracts/
        └── affected-surface.contract.json
```

A task may omit `public/contracts/` when the existing code and instruction already define the
changed behavior clearly. The candidate still receives the complete existing codebase in either
case.

## Freezing the contract

Exercise the existing application and the completed reference through the affected public surface.
Record the contract only after the reference behavior is stable. Hidden tests should check the new
behavior and the important unchanged behavior around it; they must not depend on private source
layout or database details.
