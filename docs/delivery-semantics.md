# Delivery semantics

The queue intentionally distinguishes **job idempotency** from **physical print delivery**.

## Application-level duplicate prevention

Every logical receipt should have a stable idempotency key, for example:

```text
order-57391
refund-57391-1
kitchen-ticket-99218
```

The SQLite table has a unique constraint on that key. Repeating an enqueue request returns the existing job instead of creating another row.

This solves duplicate job creation caused by repeated user actions or API retries.

## Delivery-level ambiguity

Raw TCP printers introduce a different problem.

Consider this sequence:

1. the client opens a socket
2. the client starts sending receipt bytes
3. the network drops
4. the client receives an exception

At step 4, the application cannot prove whether the printer received zero bytes, some bytes, or the complete receipt.

Blindly retrying may create a duplicate.

For that reason, `PrinterDeliveryError` carries a `may_have_printed` flag.

- `False`: delivery failed before sending started; automatic retry is allowed.
- `True`: delivery became ambiguous; the job is marked `uncertain` and automatic retry stops.

## Why not mark everything failed?

A failed connection before any bytes are sent is a recoverable infrastructure problem. Retrying that case improves reliability without increasing duplicate risk.

Treating both cases the same would either:

- lose printable jobs by never retrying, or
- create unnecessary duplicate risk by retrying ambiguous sends.

## Exactly-once is not claimed

This project does not claim exactly-once physical printing.

Exactly-once behavior would require a protocol where the printer or an intermediate print server can acknowledge a durable job identifier and reject duplicates itself.

The queue instead aims for a more practical property:

> do not automatically retry when the system cannot prove that retrying is safe.
