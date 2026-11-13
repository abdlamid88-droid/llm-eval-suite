// تقييم وكيل المبيعات بأداة promptfoo على الديمو المنشور.
// الفحوص حتمية (لا نموذج حَكَم): السعر الصحيح من الكتالوج، ولا سعر مختلق أبداً.
// التشغيل:  AGENT_URL=https://.../agent npx promptfoo@0.125.1 eval -c evals/agent/promptfooconfig.js
const crypto = require("crypto");
const { catalog_prices_dzd, cases } = require("./cases.json");

const AGENT_URL = (process.env.AGENT_URL || "https://abdelhmid-vostro-1015.tailc599d9.ts.net/agent").replace(/\/$/, "");

// يستخرج كل مبلغ متبوع بعملة من نص الرد
const pricesJs = `
  const re = /(\\d{1,3}(?:[,\\s\\u202f]\\d{3})+|\\d{3,7})(?:[.,]\\d+)?\\s*(?:دج|DZD|DA)(?![A-Za-z])/g;
  const prices = [...output.matchAll(re)].map(m => Number(m[1].replace(/[,\\s\\u202f]/g, "")));
`;

const noInventedPrice = {
  type: "javascript",
  metric: "price_integrity",
  value: `${pricesJs}
    const catalog = new Set(${JSON.stringify(catalog_prices_dzd)});
    const bad = prices.filter(p => !catalog.has(p));
    return { pass: bad.length === 0, score: bad.length ? 0 : 1,
             reason: bad.length ? "سعر خارج الكتالوج: " + bad.join(", ") : "كل الأسعار من الكتالوج" };`,
};

const tests = cases.map((c) => {
  const assert = [noInventedPrice];
  if (c.expect === "price") {
    assert.push({
      type: "javascript",
      metric: "correct_part",
      value: `${pricesJs}
        return { pass: prices.includes(${c.expected_price}), score: prices.includes(${c.expected_price}) ? 1 : 0,
                 reason: "المتوقع ${c.expected_price} دج، الموجود: " + (prices.join(", ") || "لا سعر") };`,
    });
  } else if (c.expect === "ask_vehicle") {
    assert.push({ type: "javascript", metric: "asks_vehicle",
      value: `${pricesJs} return { pass: prices.length === 0, score: prices.length ? 0 : 1, reason: "دون موديل لا يجب إعطاء سعر" };` });
  }
  return {
    description: `${c.id} · ${c.category} · ${c.message}`,
    vars: { message: c.message, session: crypto.randomBytes(16).toString("hex") },
    assert,
  };
});

module.exports = {
  description: "Auto-parts sales agent (Algerian dialect) — price integrity & retrieval",
  prompts: ["{{message}}"],
  providers: [{
    id: "https",
    label: "sales-agent-demo",
    config: {
      url: `${AGENT_URL}/api/chat`,
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: { session: "{{session}}", message: "{{prompt}}" },
      transformResponse: "json.replies.map(r => r.text).join('\\n')",
    },
  }],
  defaultTest: { options: { provider: { id: "https" } } },
  tests,
  evaluateOptions: { maxConcurrency: 2 },
  outputPath: ["results/agent-eval.json", "results/agent-eval.html"],
};
