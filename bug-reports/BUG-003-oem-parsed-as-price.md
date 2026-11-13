# BUG-003 · OEM reference read as a price

**Severity:** High · **Component:** `parse_algerian_currency_to_dzd` · **Status:** Fixed

## Steps to reproduce
1. `ديسك فران سيمبول` → bot quotes a brake disc.
2. Send the reference `58101-1GA00`.

## Expected
Exact search for that reference.

## Actual
"Booking confirmed — price: 58,101 DZD" for the previous part. The digits of the reference were parsed as a price and treated as an option selection.

## Root cause
The number regex accepted digits glued to letters or hyphens. A second issue (fixed with it): the remembered car model was appended to the reference (`58101-1GA00 SYMBOL`), which broke the exact-match search.

## Fix
Ignore numbers adjacent to Latin letters, digits or hyphens; don't append the vehicle context to a valid OEM reference.

## Regression test
`tests/live/test_live_agent.py::test_oem_reference_after_context_is_searched_exactly`
