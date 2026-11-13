# Bug reports

Defects found while building the evaluation suite. Each one has a reproduction, the root cause, the fix, and the test that now guards it.

| ID | Component | Severity | Status |
|---|---|---|---|
| [BUG-001](BUG-001-in-stock-part-never-quoted.md) | Sales agent · hybrid search | Critical | Fixed |
| [BUG-002](BUG-002-customer-sets-price.md) | Sales agent · order flow | Critical | Fixed |
| [BUG-003](BUG-003-oem-parsed-as-price.md) | Sales agent · price parser | High | Fixed |
| [BUG-004](BUG-004-false-out-of-stock.md) | Sales agent · part matching | High | Fixed |
| [BUG-005](BUG-005-journal-silently-balanced.md) | Invoice reader · SCF journal | High | Fixed |
| [BUG-006](BUG-006-cash-threshold.md) | Invoice reader · tax alerts | Medium | Fixed |

The sales agent's source is private (client deployment); its reports reference the public demo, where every case can be reproduced.
