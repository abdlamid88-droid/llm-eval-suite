# LLM Eval Suite — testing Arabic AI products

[![unit-tests](https://github.com/abdlamid88-droid/llm-eval-suite/actions/workflows/ci.yml/badge.svg)](https://github.com/abdlamid88-droid/llm-eval-suite/actions/workflows/ci.yml)
[![live-eval](https://github.com/abdlamid88-droid/llm-eval-suite/actions/workflows/live-eval.yml/badge.svg)](https://github.com/abdlamid88-droid/llm-eval-suite/actions/workflows/live-eval.yml)

How I test LLM products that serve Arabic-speaking users: deterministic unit tests around the model,
black-box tests against live deployments, browser tests, and LLM evaluations with promptfoo — all in CI.

The suite runs against three live demos I built and self-host:

| Demo | What it does | Live |
|---|---|---|
| **Ask your document** (RAG) | Answers only from an uploaded PDF, cites the page, refuses when the answer isn't there | [/](https://abdelhmid-vostro-1015.tailc599d9.ts.net/) |
| **Invoice reader** | Image/PDF → fields → Algerian SCF journal entry → tax-ID checks → Excel / PC Compta | [/invoices](https://abdelhmid-vostro-1015.tailc599d9.ts.net/invoices) |
| **Auto-parts sales agent** | WhatsApp-style agent that understands Algerian dialect and French part names | [/agent](https://abdelhmid-vostro-1015.tailc599d9.ts.net/agent) |

The demos run on a home server, so they may occasionally be offline; the live tests skip instead of failing when that happens.

## What is tested

| Layer | Runs | Tools | What it checks |
|---|---|---|---|
| **Unit** — `tests/unit` | every push (CI) | Pytest, PostgreSQL + pgvector service, mocked LLM | Arabic PDF text extraction (visual-order text, lam-alef ligatures, Persian letter forms), retrieval and citation, refusal without sources, session isolation, rate limits, quota errors, OpenAI-compatible providers (Ollama/vLLM) via a mock transport, SCF journal balancing, Algerian tax-ID formats, cash thresholds, Excel / PC Compta exports |
| **Live API** — `tests/live` | weekly + on demand | Pytest, httpx | Real model on the deployed demos: grounded answers on the right page, refusal of out-of-document questions, exact invoice amounts, balanced journal, **every price the agent quotes exists in the catalog** |
| **UI** — `tests/live/test_live_ui.py` | weekly + on demand | Playwright | Desktop and phone viewports: the main flow of each demo, file download, no JS errors, no horizontal scroll |
| **LLM eval** — `evals/agent` | weekly + on demand | promptfoo | 21 cases: 18 dialect/French part questions, plus out-of-catalog, off-topic and prompt-injection cases. Deterministic assertions: correct part price, price integrity |

### Do the tests catch real bugs?

- **Mutation check:** I broke the code on purpose in three critical places (silently balancing a wrong journal entry, the old cash threshold, showing unrelated sources on a refusal). Each break made at least one unit test fail.
- **Before/after on the sales agent:** against the agent's original code, the live agent tests failed **8 of 11**; after the fixes they all pass. On the 18 dialect questions, correct parts went from **0/18 to 16/18** (the other two are correct behaviour).
- **Defects found:** six, written up in [`bug-reports/`](bug-reports/) with reproduction, root cause, fix and the test that guards each one.

## Run it

```bash
# Unit tests (each demo has its own app package, so run them separately)
pip install -r demos/invoice-demo/requirements.txt pytest
pytest tests/unit/invoice

pip install -r demos/rag-demo/requirements.txt pytest reportlab
docker run -d -p 5432:5432 -e POSTGRES_USER=rag_demo -e POSTGRES_PASSWORD=rag_demo -e POSTGRES_DB=rag_demo pgvector/pgvector:pg16
TEST_DATABASE_URL=postgresql://rag_demo:rag_demo@localhost:5432/rag_demo pytest tests/unit/rag

# Live tests and evals (consume the demos' Gemini quota)
pip install -r requirements-dev.txt && python -m playwright install chromium
BASE_URL=https://abdelhmid-vostro-1015.tailc599d9.ts.net pytest tests/live
AGENT_URL=https://abdelhmid-vostro-1015.tailc599d9.ts.net/agent npx promptfoo@0.125.1 eval -c evals/agent/promptfooconfig.js
```

Each demo URL can be overridden with `RAG_URL`, `INVOICES_URL` and `AGENT_URL`, for example to test a local or staging deployment.

## Repository layout

```
demos/rag-demo        FastAPI + pgvector RAG demo (Gemini, or any OpenAI-compatible server)
demos/invoice-demo    Stateless invoice reader demo (Gemini structured output)
tests/unit            Offline, deterministic tests — run in CI on every push
tests/live            Black-box API and Playwright tests against deployed demos
evals/agent           promptfoo evaluation of the sales agent
bug-reports           Structured reports of defects found
```

The sales agent's engine is private (client deployment); it is tested here only as a black box through its public demo, which uses a fictional 40-part catalog.

---

## بالعربية

مجموعة اختبارات لمنتجات ذكاء اصطناعي تخدم مستخدمين عرباً: اختبارات وحدة حتمية حول النموذج، واختبارات حية على الديموهات المنشورة، واختبارات واجهة بـ Playwright، وتقييم LLM بأداة promptfoo، وكلها تعمل تلقائياً عبر GitHub Actions.
أبرز ما تكشفه: استخراج النص العربي من ملفات PDF المقلوبة الترتيب، والإجابة من الوثيقة مع رقم الصفحة، والرفض الصريح عند غياب المعلومة، وتوازن القيد المحاسبي SCF، وأن كل سعر يذكره وكيل المبيعات موجود في الكتالوج فعلاً.
