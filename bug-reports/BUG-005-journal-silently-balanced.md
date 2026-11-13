# BUG-005 · Unbalanced journal entry silently "balanced"

**Severity:** High (accounting integrity) · **Component:** invoice reader, `balance_journal_entries` · **Status:** Fixed in the demo

## Steps to reproduce
Model returns debit 125,000 + 22,800 and credit 142,800 (a 5,000 DZD error).

## Expected
The entry is flagged as unbalanced.

## Actual
The difference was added to the last line, whatever its size, so a wrong entry looked correct.

## Fix
Only rounding differences up to 1 DZD are absorbed, in the counterparty account (401 for purchases, 411 for sales). Anything larger raises a critical `UNBALANCED` alert and is left untouched.

## Regression test
`tests/unit/invoice/test_accounting.py::test_large_difference_is_reported_not_hidden` (verified by mutation: reverting the fix makes it fail).
