# BUG-007 · Network outage reaches the visitor as HTTP 500

**Severity:** Medium (bad error handling, no data loss) · **Component:** Gemini calls in the invoice reader and RAG demos · **Status:** Fixed

## How it was found
The weekly `live-eval` run: the first invoice extraction returned `500 Internal Server Error`, and the six invoice tests that depend on it errored. The same file passed in the UI test a minute later, so the failure was intermittent.

## Root cause
Server log: `httpx2.ConnectError: [Errno 101] Network is unreachable` — the home server briefly lost its route to Google.
Recent versions of the Gemini SDK use `httpx2`; the code only caught `httpx.HTTPError`, so the network error was unhandled.

## Expected
A short retry, then a clear `503` with an Arabic message if the outage persists.

## Fix
One automatic retry for network errors and Gemini 5xx; network errors are caught generically instead of by the HTTP library's type; 429 and 4xx are not retried.

## Regression tests
`tests/unit/invoice/test_invoice_api.py` (4 tests) and `tests/unit/rag/test_providers_gemini.py`. Against the old code, 3 of the 4 invoice tests fail.
