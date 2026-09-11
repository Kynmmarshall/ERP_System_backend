# Event Contracts

Versioned JSON Schemas for asynchronous events exchanged between services via RabbitMQ.
These schemas are the source of truth for producer/consumer contract tests in each
service. No service imports another service's code; only these schema files (and the
generated examples) are shared.

## Layout

- `events/envelope.schema.json` — the outer envelope every event is wrapped in.
- `events/enrollment-accepted.v1.schema.json` — payload for `EnrollmentAccepted.v1`.
- `events/examples/` — valid example payloads used by contract tests.

## Adding a new event version

1. Never mutate a published schema. Add `enrollment-accepted.v2.schema.json` instead.
2. Add a matching example under `events/examples/`.
3. Update both the producing and consuming service's contract tests.
4. Consumers must keep handling older versions until every producer/consumer pair has
   migrated (see `docs/architecture.md` in the repo root once written).
