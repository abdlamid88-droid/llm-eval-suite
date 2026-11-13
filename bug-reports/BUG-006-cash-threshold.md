# BUG-006 · Wrong cash-payment threshold for expense deductibility

**Severity:** Medium (misleading compliance alert) · **Component:** invoice reader tax alerts · **Status:** Fixed in the demo

## Actual
Every invoice above 100,000 DZD paid in cash was flagged as non-deductible.

## Expected
Per the 2018 Finance Law (art. 169 CIDTA) the threshold for expense deductibility is 300,000 DZD TTC; 100,000 DZD concerns TVA deduction (art. 30 CTCA).

## Fix
Two separate alerts (`CASH_TVA` above 100,000 DZD, `CASH_CHARGE` above 300,000 DZD), worded as guidance to check the latest Finance Law.

## Regression test
`tests/unit/invoice/test_accounting.py::test_cash_thresholds`
