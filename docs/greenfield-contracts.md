# Contracts for greenfield tasks

A greenfield task starts without an application for the candidate to extend. Public contracts
describe the behavior to build; the private reference application and verifier let the task author
confirm that behavior is achievable.

## Public contract files

Put the contracts the candidate may read under `public/contracts/`:

```text
public/
├── contracts/
│   ├── openapi.contract.json
│   └── ui.contract.json
└── assets/
```

Use these fixed filenames and JSON formats. The API contract covers operations, inputs, outputs,
status codes, authentication, validation, and important state transitions. The UI contract covers
user flows, visible states, accessibility, and stable semantic hooks such as
`data-ui="consent.grant"`. Neither contract should prescribe framework components or database
tables.

A task does not need both contracts by default. Use the API contract for a backend task, the UI
contract for a browser task, and both when the browser and server must work together.

`assets/` contains public files the product needs at runtime, such as images, fonts, sample
documents, or other binary resources. Test fixtures belong in the private verifier, where the test
setup can create the exact state it needs. They are not part of the candidate-facing package.

## Application handoff

The completed application must include `app-setup/manifest.json`. This small lifecycle
description is consumed by the verifier; it is not a hidden test or another product contract. It
names the commands used to build, start, and reset the application; the frontend, API, and
readiness URLs; the contract artifacts; and the datastores actually used. Use the reference task's
[`app-setup/manifest.json`](../verifier/reference-solution/app-setup/manifest.json)
as the format reference, define task-specific values, and keep the referenced scripts beside it under
`app-setup/`.

The verifier invokes these commands from the application workspace, waits for the readiness URL to
return HTTP 200, and then runs its private tests through the public API and UI. It must not need the
candidate's source layout or database internals.

## Freezing the contracts

1. Describe the product outcome and user workflows in `instruction.md`.
2. Build the complete reference application privately.
3. Exercise the reference through its public API and browser UI.
4. Record the supported API paths, methods, inputs, outputs, errors, authentication, and state
   transitions in the API contract.
5. Add stable UI hooks to meaningful controls, regions, list items, statuses, and error messages.
   Record each hook's observable meaning in the UI contract.
6. Add deterministic fixtures to the private verifier for the states the tests need.
7. Write hidden tests against the contracts, then add plausible faulty implementations (mutants)
   that those tests catch.
8. Run the verifier and scorer using the shared harness, keeping the reference, hidden tests,
   mutants, fixtures, proof-of-work evidence, and scoring rules private.

The contracts are reviewed snapshots of working behavior, not guesses. If the reference changes,
review the affected contract and tests before freezing it again.

## How the verifier uses them

- Backend tests make real HTTP requests and check responses, authorization, persistence, and state
  transitions.
- UI tests use a browser and the stable hooks to perform real actions and check visible results,
  validation, accessibility, and navigation.
- When a behavior crosses both surfaces, cover it in the backend or UI suite as appropriate. The
  template does not require a separate test suite for this.

## Candidate and private material

The candidate receives `instruction.md`, the relevant frozen contracts, public assets, and setup
notes. The reference implementation, hidden tests, verifier fixtures, mutants, acceptance criteria,
scoring rules, and proof-of-work results remain under `verifier/`.

## Example package

```text
tasks/consent-console/
├── task.toml
├── instruction.md
├── public/
│   ├── contracts/
│   │   ├── openapi.contract.json
│   │   └── ui.contract.json
│   └── assets/
verifier/consent-console/
├── reference-solution/
├── hidden-tests/backend/
├── hidden-tests/frontend/
├── mutants/
├── acceptance-criteria.yml
├── scoring.yml
└── proof-of-work/
```
