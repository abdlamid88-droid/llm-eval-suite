# BUG-001 · In-stock part is found but never quoted

**Severity:** Critical (blocks the main sales path) · **Component:** `hybrid_search.perform_hybrid_part_search` · **Status:** Fixed

## Steps to reproduce
1. Send `بلاكيط فرامل أكسنت` ("brake pads Accent") — part and car model are both present.
2. The matching part is in stock.

## Expected
A reply with the part and its catalog price.

## Actual
The bot asks for the car model the customer has just given. No price is ever quoted for "part + model" questions while stock exists.

## Root cause
In the in-stock branch the best candidate was selected but never returned: the block that builds alternatives and `return {"found": True, ...}` sat after a `return` inside the `elif` (out-of-stock) branch, so it was unreachable. Execution fell through to the "part without model" guard.

## Fix
Moved the return block into the in-stock branch.

## Evidence
On the same 40-part catalog and the same 18 dialect questions: **0/18 → 16/18** correct parts (the remaining two are correct behaviour: an in-stock alternative is offered, and a question without a car model is answered with a request for the model).
Guarded by `tests/live/test_live_agent.py::test_dialect_query_returns_the_catalog_price` and `evals/agent` (promptfoo).
