const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const html = fs.readFileSync("index.html", "utf8");
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1].replace(/init\(\);\s*$/, "");
const elements = {};
const document = { getElementById(id) {
  return elements[id] ||= {textContent: "", innerHTML: "", classList: {toggle(name, value) {this[name] = value;}}};
}};
const context = vm.createContext({document, Intl, Date, fetch: async () => {
  throw new Error("fetch not configured");
}});
vm.runInContext(script, context);
const status = (date, instant) => context.menuDateStatus(date, new Date(instant));
assert.equal(status("2026-11-01", "2026-11-01T14:59:59Z").stale, false);
assert.equal(status("2026-11-01", "2026-11-01T15:00:00Z").stale, true);
assert.match(status("2026-11-01", "2026-11-01T15:00:00Z").text, /이전 메뉴/);
assert.equal(status("2026-11-02", "2026-11-01T16:00:00Z").stale, false);
assert.match(status("2026-11-03", "2026-11-01T16:00:00Z").text, /다른 날짜/);
for (const date of [undefined, null, "", "bad", "2026-02-30", "2026-13-01"]) {
  assert.match(status(date, "2026-11-01T16:00:00Z").text, /확인할 수 없습니다/);
}
assert.equal(status("2027-01-01", "2026-12-31T15:00:00Z").stale, false);
assert.equal(status("2028-02-29", "2028-02-28T15:00:00Z").stale, false);
(async () => {
  context.fetch = async (url, options) => {
    assert.equal(options.cache, "no-store");
    return {ok: true, json: async () => ({date: "2020-01-01", restaurants: {}, dorm: {}})};
  };
  await context.init();
  assert.match(elements["date-display"].textContent, /2020년 1월 1일/);
  assert.equal(elements["date-display"].classList.stale, true);
  assert.match(elements.lunch.innerHTML, /메뉴 정보가 없습니다/);
  context.fetch = async () => ({ok: false});
  await context.init();
  assert.match(elements["date-display"].textContent, /확인할 수 없습니다/);
  assert.match(elements.lunch.innerHTML, /불러올 수 없습니다/);
  console.log("Frontend date, stale/future/invalid, KST boundary, fetch/cache/error tests passed");
})().catch(error => { console.error(error); process.exitCode = 1; });
