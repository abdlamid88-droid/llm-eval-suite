# BUG-002 · Customer can set the confirmed price

**Severity:** Critical (direct revenue loss) · **Component:** `multi_turn_manager` order confirmation · **Status:** Fixed

## Steps to reproduce
1. `امورتيسور قدام أتوس` → bot quotes 6,200 DZD.
2. `نديها ب 1000 دج` ("I'll take it for 1,000 DZD").

## Expected
Booking confirmed at the stock price, 6,200 DZD.

## Actual
"Booking confirmed — price: 1,000 DZD".

## Root cause
`price_val = float(chosen_price or p_dict.get("price"))` — the number parsed from the customer's message took precedence over the database price.

## Fix
`price_val = float(p_dict.get("price") or chosen_price or 0.0)` — the stock price always wins.

## Regression test
`tests/live/test_live_agent.py::test_customer_cannot_set_the_price`
