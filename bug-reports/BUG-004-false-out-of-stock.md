# BUG-004 · Parts in stock reported as "out of stock"

**Severity:** High (lost sales, wrong information) · **Component:** generic part-matching branch · **Status:** Fixed

## Steps to reproduce
`ديمارور كيو كيو` ("starter motor QQ", eval case TC-08) — the part is in stock.

## Expected
The part and its price.

## Actual
"Unfortunately this part is out of stock."

## Root cause
Parts without a dedicated rule were matched by comparing the English dictionary term (`Starter Motor`) with French stock names (`DEMARREUR`) — never a match. The empty result was then phrased as "out of stock".

## Fix
Match against the part's synonyms from the project's own dictionary (Arabic, dialect, French). When nothing matches, the bot now says it could not confirm the part and asks for the reference or a photo — it no longer claims the part is out of stock.

## Regression test
`evals/agent` cases TC-08, TC-14, TC-15, TC-16, TC-17, TC-18.
