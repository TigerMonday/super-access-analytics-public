// ②施策作成（対象ページ選定＋改善案）: 対象ページの「モバイル・ファーストビュー（FV）」を撮影・把握する。
// 有料流入はモバイル中心のため、モバイルで最初に何が見えているか（FVに入る見出し/CTA/テキスト）を取得し、
// どこを直すと良さそうかの当たりをつける材料にする。
//
// Usage:
//   npm install            # 初回のみ（playwright。ブラウザはキャッシュ済みなら追加DL不要）
//   node scripts/fv-capture.mjs <URL> [device]
//   device: "iPhone SE" | "iPhone 14 Pro"(default) | "Pixel 7"
//
// 出力: scripts/screenshots/<URL識別子>-<取得時刻>/<device>-fv.png（FVのみ）
//   + <device>-full.png（全体）+ report.json
//   report.json には FV内に見える見出し/CTA、ページ status・リダイレクト先、全体高さ等を記録。

import { chromium, devices } from "playwright";
import { createHash } from "node:crypto";
import { lookup } from "node:dns/promises";
import { mkdirSync, writeFileSync } from "node:fs";
import { BlockList, isIP } from "node:net";
import { dirname, isAbsolute, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const OUT_ROOT = join(__dirname, "screenshots");

const BLOCKED_ADDRESSES = new BlockList();
for (const [network, prefix] of [
  ["0.0.0.0", 8],
  ["10.0.0.0", 8],
  ["100.64.0.0", 10],
  ["127.0.0.0", 8],
  ["169.254.0.0", 16],
  ["172.16.0.0", 12],
  ["192.0.0.0", 24],
  ["192.168.0.0", 16],
  ["198.18.0.0", 15],
  ["224.0.0.0", 4],
  ["240.0.0.0", 4],
]) {
  BLOCKED_ADDRESSES.addSubnet(network, prefix, "ipv4");
}
for (const [network, prefix] of [
  ["::", 128],
  ["::1", 128],
  ["fc00::", 7],
  ["fe80::", 10],
  ["ff00::", 8],
]) {
  BLOCKED_ADDRESSES.addSubnet(network, prefix, "ipv6");
}

function hostnameWithoutBrackets(hostname) {
  return hostname.replace(/^\[|\]$/g, "").replace(/\.$/, "");
}

export function isBlockedAddress(address) {
  const normalized = hostnameWithoutBrackets(address).split("%")[0].toLowerCase();
  const family = isIP(normalized);
  if (!family) {
    throw new Error("接続先のIPアドレスを確認できません");
  }
  // IPv4-mapped IPv6 は表記の揺れによるすり抜けを避けるため一律拒否する。
  if (family === 6 && normalized.startsWith("::ffff:")) return true;
  return BLOCKED_ADDRESSES.check(normalized, family === 6 ? "ipv6" : "ipv4");
}

export async function assertSafeHttpUrl(rawUrl, lookupFn = lookup) {
  let parsed;
  try {
    parsed = rawUrl instanceof URL ? new URL(rawUrl.href) : new URL(rawUrl);
  } catch {
    throw new Error("URLの形式が正しくありません");
  }

  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    throw new Error("URLは http または https で指定してください");
  }
  if (parsed.username || parsed.password) {
    throw new Error("認証情報を含むURLは指定できません");
  }

  const hostname = hostnameWithoutBrackets(parsed.hostname).toLowerCase();
  if (hostname === "localhost" || hostname.endsWith(".localhost") || hostname.endsWith(".local")) {
    throw new Error("ローカルネットワークのURLは指定できません");
  }

  if (isIP(hostname)) {
    if (isBlockedAddress(hostname)) {
      throw new Error("ローカルまたは非公開IPアドレスには接続できません");
    }
    return parsed;
  }

  let records;
  try {
    records = await lookupFn(hostname, { all: true, verbatim: true });
  } catch {
    throw new Error("接続先の名前解決に失敗しました");
  }
  if (!Array.isArray(records) || records.length === 0) {
    throw new Error("接続先のIPアドレスを確認できません");
  }
  if (records.some((record) => isBlockedAddress(record.address))) {
    throw new Error("ローカルまたは非公開IPアドレスには接続できません");
  }
  return parsed;
}

export function redactUrlForOutput(rawUrl) {
  try {
    const parsed = rawUrl instanceof URL ? new URL(rawUrl.href) : new URL(rawUrl);
    parsed.username = "";
    parsed.password = "";
    parsed.search = "";
    parsed.hash = "";
    return parsed.href;
  } catch {
    return "[URL omitted]";
  }
}

export function sanitizeErrorMessage(error) {
  const message = error instanceof Error ? error.message : String(error);
  return message.replace(/https?:\/\/[^\s<>"']+/gi, (candidate) => {
    const trailing = candidate.match(/[),.;]+$/)?.[0] || "";
    const url = trailing ? candidate.slice(0, -trailing.length) : candidate;
    return `${redactUrlForOutput(url)}${trailing}`;
  });
}

export function toRelativeOutputDirectory(outputRoot, outputPath) {
  const rel = relative(resolve(outputRoot), resolve(outputPath));
  if (!rel || rel === ".." || rel.startsWith(`..${process.platform === "win32" ? "\\" : "/"}`) || isAbsolute(rel)) {
    throw new Error("出力先が screenshots ディレクトリの外です");
  }
  return rel.replaceAll("\\", "/");
}

export function createSafeRouteHandler({ lookupFn = lookup, onBlocked = () => {} } = {}) {
  return async (route) => {
    const requestUrl = route.request().url();
    let protocol;
    try {
      protocol = new URL(requestUrl).protocol;
    } catch {
      protocol = "";
    }

    if (["about:", "blob:", "data:"].includes(protocol)) {
      await route.continue();
      return;
    }

    try {
      await assertSafeHttpUrl(requestUrl, lookupFn);
      await route.continue();
    } catch (error) {
      onBlocked({
        url: redactUrlForOutput(requestUrl),
        reason: sanitizeErrorMessage(error),
      });
      await route.abort("blockedbyclient");
    }
  };
}

export async function main(argv = process.argv.slice(2)) {
  const targetUrl = argv[0];
  const deviceName = argv[1] || "iPhone 14 Pro";
  if (!targetUrl) {
    console.error("Usage: node scripts/fv-capture.mjs <URL> [device]");
    return 1;
  }

  let parsedUrl;
  try {
    parsedUrl = await assertSafeHttpUrl(targetUrl);
  } catch (error) {
    console.error(`エラー: ${sanitizeErrorMessage(error)}`);
    return 1;
  }

  const device = devices[deviceName];
  if (!device) {
    console.error(`Unknown device: ${deviceName}. Use one of: ${Object.keys(devices).filter((d) => /iPhone|Pixel/.test(d)).join(", ")}`);
    return 1;
  }

  const slug = deviceName.replace(/\s+/g, "-").toLowerCase();
  const readableUrlSlug = `${parsedUrl.hostname}${parsedUrl.pathname}`
    .replace(/[^a-zA-Z0-9]+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 80) || "page";
  const safeTargetUrl = redactUrlForOutput(parsedUrl);
  const urlHash = createHash("sha256").update(safeTargetUrl).digest("hex").slice(0, 8);
  const capturedAt = new Date();
  const timestamp = capturedAt.toISOString().replace(/[:.]/g, "-");
  const out = join(OUT_ROOT, `${readableUrlSlug}-${urlHash}-${timestamp}`);
  const outputDirectory = toRelativeOutputDirectory(OUT_ROOT, out);
  mkdirSync(out, { recursive: true });

  const report = {
    url: safeTargetUrl,
    capturedAt: capturedAt.toISOString(),
    outputDirectory,
    device: deviceName,
    viewport: device.viewport,
  };
  let browser;
  let blockedRequest = null;
  let returnCode = 0;

  try {
    browser = await chromium.launch();
    const context = await browser.newContext({ ...device, serviceWorkers: "block" });
    // 初回URLに加えて各リクエスト（リダイレクトを含む）でもDNSを確認する。
    // 検証後にChromiumが再度名前解決するまでのDNS rebinding競合を完全には排除できないが、
    // URL文字列だけを検査する場合より接続先のすり替え範囲を狭める。
    await context.route("**/*", createSafeRouteHandler({
      onBlocked: (blocked) => {
        blockedRequest ??= blocked;
      },
    }));
    const page = await context.newPage();
    const resp = await page.goto(parsedUrl.href, { waitUntil: "networkidle", timeout: 30000 });
    await page.waitForTimeout(600);
    if (blockedRequest) {
      throw new Error(`安全でない接続先を拒否しました: ${blockedRequest.url}`);
    }

    const finalUrl = await assertSafeHttpUrl(page.url());
    report.status = resp ? resp.status() : null;
    report.finalUrl = redactUrlForOutput(finalUrl);
    report.redirected = finalUrl.href !== parsedUrl.href;
    report.title = await page.title();

    const vh = device.viewport.height;
    report.fullHeight = await page.evaluate(() => document.body.scrollHeight);
    report.foldsToScroll = +(report.fullHeight / vh).toFixed(1);

    // FV（ビューポート）スクショ と 全体スクショ
    await page.screenshot({ path: join(out, `${slug}-fv.png`), fullPage: false });
    await page.screenshot({ path: join(out, `${slug}-full.png`), fullPage: true });

    // FV内に見える要素（見出し・CTA・主要テキスト）を抽出
    report.aboveFold = await page.evaluate((viewportHeight) => {
      const visible = (el) => {
        const r = el.getBoundingClientRect();
        const st = getComputedStyle(el);
        return r.width > 0 && r.height > 0 && st.visibility !== "hidden" && st.display !== "none" && r.top < viewportHeight && r.bottom > 0;
      };
      const text = (el) => (el.innerText || el.textContent || "").trim().replace(/\s+/g, " ").slice(0, 120);
      const pick = (sel) => Array.from(document.querySelectorAll(sel)).filter(visible)
        .map((el) => ({ tag: el.tagName.toLowerCase(), text: text(el), y: Math.round(el.getBoundingClientRect().top) }))
        .filter((x) => x.text);
      const ctaSel = 'a,button,[role="button"],input[type="submit"]';
      return {
        headings: pick("h1,h2,h3").slice(0, 8),
        ctas: pick(ctaSel).slice(0, 10),
      };
    }, vh);

    report.ctaInFold = report.aboveFold.ctas.length > 0;
  } catch (error) {
    report.error = sanitizeErrorMessage(error);
    returnCode = 1;
  } finally {
    if (browser) await browser.close();
  }

  writeFileSync(join(out, "report.json"), JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report, null, 2));
  console.log(`\nscreenshots: ${outputDirectory}/${slug}-fv.png (FV) / ${slug}-full.png (全体)`);
  return returnCode;
}

const isMainModule = process.argv[1]
  && resolve(process.argv[1]) === resolve(fileURLToPath(import.meta.url));
if (isMainModule) {
  process.exitCode = await main();
}
