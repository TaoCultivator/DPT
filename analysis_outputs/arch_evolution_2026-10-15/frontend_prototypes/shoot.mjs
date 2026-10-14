/* 用本机 Chrome/Edge 的无头模式给三个原型截图，作为可评审的视觉证据。
 *
 * 为什么用无头浏览器：前端方案的审美只能看图说服，文字描述不可替代。
 * 本机已装 Chrome 与 Edge，无需新增依赖（不装 playwright/puppeteer）。
 *
 * 用法：node prototypes/shoot.mjs
 */
import { execFileSync } from "node:child_process";
import { existsSync, mkdirSync, readdirSync, statSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const outDir = join(here, "shots");
if (!existsSync(outDir)) mkdirSync(outDir, { recursive: true });

const CANDIDATES = [
  "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
  "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
  "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
  "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
];

const browser = CANDIDATES.find((p) => existsSync(p));
if (!browser) {
  console.error("未找到 Chrome 或 Edge，无法截图");
  process.exit(1);
}
console.log("浏览器:", browser);

const protos = readdirSync(here)
  .filter((f) => /^proto_[a-c].*\.html$/.test(f) && !f.endsWith(".tpl.html"))
  .sort();
if (protos.length === 0) {
  console.error("未找到已构建的原型 HTML，请先运行 node build.mjs");
  process.exit(1);
}

let ok = 0;
for (const name of protos) {
  const src = join(here, name);
  const out = join(outDir, name.replace(/\.html$/, ".png"));
  try {
    execFileSync(
      browser,
      [
        "--headless=new",
        "--disable-gpu",
        "--hide-scrollbars",
        "--no-sandbox",
        "--force-device-scale-factor=1",
        "--window-size=1440,900",
        "--virtual-time-budget=2500",
        `--screenshot=${out}`,
        "file:///" + src.replace(/\\/g, "/"),
      ],
      { stdio: "pipe", timeout: 120000 }
    );
    const size = statSync(out).size;
    console.log(`OK   ${name}  ->  shots/${name.replace(/\.html$/, ".png")}  ${(size / 1024).toFixed(1)} KB`);
    ok++;
  } catch (err) {
    console.error(`FAIL ${name}: ${err.message.split("\n")[0]}`);
  }
}
console.log(`\n完成 ${ok}/${protos.length}`);
process.exit(ok === protos.length ? 0 : 1);
