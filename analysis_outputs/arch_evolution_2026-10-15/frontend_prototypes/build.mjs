/* 把 data.mjs 内联进三个原型模板，产出「自包含单文件 HTML」。
 *
 * 为什么需要：原型要能从 file:// 直接打开、并被 Chrome headless 截图，
 * 而 file:// 下的 ESM import 会被 CORS 拦掉。内联后每个产物只有一个文件，
 * 不依赖本地服务器，也便于把截图与原型一起归档评审。
 *
 * 用法：node prototypes/build.mjs
 */
import { readFileSync, writeFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));

/** 去掉 ESM 语法糖：export const/function → 普通声明，import 行直接丢弃。 */
function toInlineModule(src) {
  return src
    .split(/\r?\n/)
    .filter((line) => !/^\s*import\s/.test(line))
    .map((line) => line.replace(/^export\s+(const|let|var|function|class)\s/, "$1 "))
    .join("\n");
}

const dataSrc = toInlineModule(readFileSync(join(here, "data.mjs"), "utf8"));

const templates = readdirSync(here).filter((f) => f.endsWith(".tpl.html"));
if (templates.length === 0) {
  console.error("未找到任何 *.tpl.html 模板");
  process.exit(1);
}

for (const tpl of templates) {
  const out = tpl.replace(/\.tpl\.html$/, ".html");
  const html = readFileSync(join(here, tpl), "utf8");
  const marker = "<!--INLINE_DATA-->";
  if (!html.includes(marker)) {
    console.error(`${tpl}: 缺少 ${marker} 占位符`);
    process.exit(1);
  }
  const built = html.replace(
    marker,
    "<script>\n/* ==== 内联数据层（生成自 data.mjs，请勿手改）==== */\n"
      + dataSrc
      + "\n</script>"
  );
  writeFileSync(join(here, out), built, "utf8");
  console.log(`生成 ${out}  (${(built.length / 1024).toFixed(1)} KB)`);
}
