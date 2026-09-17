import assert from "node:assert/strict";
import { join } from "node:path";
import test from "node:test";

import {
  assertSafeHttpUrl,
  createSafeRouteHandler,
  isBlockedAddress,
  redactUrlForOutput,
  sanitizeErrorMessage,
  toRelativeOutputDirectory,
} from "../scripts/fv-capture.mjs";

const publicLookup = async () => [{ address: "93.184.216.34", family: 4 }];

test("accepts an http or https URL that resolves only to public addresses", async () => {
  const parsed = await assertSafeHttpUrl("https://example.com/page", publicLookup);
  assert.equal(parsed.href, "https://example.com/page");
});

test("rejects non-http schemes and credentials in URLs", async () => {
  await assert.rejects(assertSafeHttpUrl("file:///etc/passwd", publicLookup), /http/);
  await assert.rejects(assertSafeHttpUrl("https://user:password@example.com/", publicLookup), /認証情報/);
});

test("rejects localhost, private, loopback, and link-local destinations", async () => {
  for (const url of [
    "http://localhost/",
    "http://service.localhost/",
    "http://127.0.0.1/",
    "http://10.0.0.1/",
    "http://169.254.169.254/latest/meta-data/",
    "http://172.16.0.1/",
    "http://192.168.0.1/",
    "http://[::1]/",
    "http://[fe80::1]/",
    "http://[fd00::1]/",
  ]) {
    await assert.rejects(assertSafeHttpUrl(url, publicLookup));
  }
});

test("rejects a hostname when DNS returns any private address", async () => {
  const mixedLookup = async () => [
    { address: "93.184.216.34", family: 4 },
    { address: "192.168.1.20", family: 4 },
  ];
  await assert.rejects(assertSafeHttpUrl("https://example.com/", mixedLookup), /非公開IP/);
});

test("recognizes private and public IP addresses", () => {
  assert.equal(isBlockedAddress("127.0.0.1"), true);
  assert.equal(isBlockedAddress("169.254.169.254"), true);
  assert.equal(isBlockedAddress("::1"), true);
  assert.equal(isBlockedAddress("93.184.216.34"), false);
});

test("removes query strings, fragments, and credentials from report URLs", () => {
  const secret = "do-not-log-this-token";
  const output = redactUrlForOutput(`https://user:pass@example.com/path?token=${secret}&email=a%40b.test#private`);
  assert.equal(output, "https://example.com/path");
  assert.equal(output.includes(secret), false);
});

test("removes query strings from browser error messages", () => {
  const secret = "do-not-log-this-token";
  const output = sanitizeErrorMessage(new Error(`net::ERR_FAILED at https://example.com/path?token=${secret}`));
  assert.equal(output.includes(secret), false);
  assert.match(output, /https:\/\/example\.com\/path/);
});

test("stores and logs output directories relative to the screenshot root", () => {
  const root = join(process.cwd(), "screenshots");
  const output = join(root, "example-com-abcd-2026-01-01");
  assert.equal(
    toRelativeOutputDirectory(root, output),
    "example-com-abcd-2026-01-01",
  );
  assert.throws(() => toRelativeOutputDirectory(root, join(root, "..", "outside")), /外/);
});

test("route guard aborts a redirect request to a private address", async () => {
  const calls = [];
  const route = {
    request: () => ({ url: () => "http://169.254.169.254/latest/meta-data/?token=secret" }),
    continue: async () => calls.push("continue"),
    abort: async () => calls.push("abort"),
  };
  let blocked;
  const handler = createSafeRouteHandler({
    lookupFn: publicLookup,
    onBlocked: (value) => { blocked = value; },
  });

  await handler(route);

  assert.deepEqual(calls, ["abort"]);
  assert.equal(blocked.url, "http://169.254.169.254/latest/meta-data/");
  assert.equal(blocked.url.includes("secret"), false);
});
