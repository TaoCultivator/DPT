/* 三个前端原型共用的「数据层」。
 *
 * 目的：让「同一份波形 + 同一套参数」在三种渲染技术下横向可比，
 * 差异只来自技术栈与视觉语言，而不是数据不同。
 *
 * 由 prototypes/build.mjs 内联进各原型 HTML，因此原型产物是自包含单文件，
 * 既可以从 file:// 直接打开，也能被 Chrome headless 截图。
 */
export const N = 62500;              // 采样点数（与 示例文件 双脉冲样例量级一致）
export const T0 = 0.0;               // 视窗起点 (us)
export const T1 = 4.0;               // 视窗终点 (us)
export const DT = (T1 - T0) / (N - 1);
export const DISP_HALF = 4.0;        // 每格半高（pyqtgraph 默认 view 范围口径）

/** 确定性伪随机（mulberry32）：保证三个原型的噪声逐点相同。 */
export function rng(seed) {
  let a = seed >>> 0;
  return function () {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export function smoothstep(x, a, b) {
  if (x <= a) return 0;
  if (x >= b) return 1;
  const u = (x - a) / (b - a);
  return u * u * (3 - 2 * u);
}

/**
 * 生成与 DPT 双脉冲工况形状一致的三通道波形。
 * 关断脉冲在前、开通脉冲在后，开通处带反向恢复电流尖峰与 Vce 过冲。
 */
export function makeDPT() {
  const rand = rng(20261015);
  const vge = new Float64Array(N);
  const ic = new Float64Array(N);
  const vce = new Float64Array(N);

  const p1on = 0.10, p1off = 0.26, p2on = 0.50, p2off = 0.76;

  for (let i = 0; i < N; i++) {
    const p = i / (N - 1);
    const g1 = smoothstep(p, p1on, p1on + 0.04) * (1 - smoothstep(p, p1off, p1off + 0.03));
    const g2 = smoothstep(p, p2on, p2on + 0.034) * (1 - smoothstep(p, p2off, p2off + 0.03));
    const g = Math.max(g1, g2);
    vge[i] = -6.0 + g * 21.0 + Math.sin(p * 940) * 0.135 + (rand() - 0.5) * 0.085;

    const rr = Math.exp(-Math.pow((p - (p2on + 0.046)) / 0.011, 2)) * 1.55;
    const tail = (p > p2off ? 1 : 0) * Math.exp(-(p - p2off) / 0.052) * 0.33;
    const base = Math.exp(-Math.pow((p - (p1on + 0.10)) / 0.16, 2)) * 0.86;
    ic[i] = (base + g * 0.56 + rr + tail) * (1 + Math.sin(p * 660) * 0.02)
          + (rand() - 0.5) * 0.011;

    const drop = Math.exp(-Math.pow((p - (p1on + 0.09)) / 0.13, 2)) * 0.92
               + Math.exp(-Math.pow((p - (p2on + 0.12)) / 0.15, 2)) * 0.54;
    const spike = Math.exp(-Math.pow((p - p2on) / 0.0085, 2)) * 5.4;
    vce[i] = 486 * (1 - 0.63 * g1 - 0.69 * g2) + spike - drop * 12 + (rand() - 0.5) * 1.35;
  }
  return { vge, ic, vce };
}

/** 通道 → 显示值，与 DPT ``waveform_plot`` 的 vdiv / yPosition 口径同构。 */
export function toDisplay(arr, vdiv, ypos) {
  const o = new Float64Array(arr.length);
  for (let i = 0; i < arr.length; i++) o[i] = arr[i] / vdiv - ypos;
  return o;
}

export const TRACE_META = [
  { label: "Vge", color: "#3ee07f", vdiv: 5.0, ypos: 1.15, unit: "V" },
  { label: "Ic",  color: "#ffd23f", vdiv: 400.0, ypos: 0.0, unit: "A" },
  { label: "Vce", color: "#4aa8ff", vdiv: 200.0, ypos: -1.55, unit: "V" },
];

/** 参数表（三原型共用同一份数值，便于横向对照交互） */
export const PARAMS = [
  { section: "关断过程", name: "ΔVce", unit: "V", value: "402.6", range: "312.0~714.6" },
  { section: "关断过程", name: "Ic_off_max", unit: "A", value: "1053.2", range: "自动" },
  { section: "关断过程", name: "Vce_off_max", unit: "V", value: "714.6", range: "自动" },
  { section: "关断过程", name: "dv/dt", unit: "V/ns", value: "24.18", range: "20.0→80.0%" },
  { section: "关断过程", name: "di/dt", unit: "A/ns", value: "13.62", range: "20.0→80.0%" },
  { section: "关断过程", name: "Ls_off", unit: "nH", value: "18.40", range: "自动" },
  { section: "关断过程", name: "Toff", unit: "us", value: "1.8013", range: "自动" },
  { section: "关断过程", name: "Td_off", unit: "us", value: "0.8421", range: "自动" },
  { section: "关断过程", name: "Tf", unit: "us", value: "0.9592", range: "自动" },
  { section: "关断过程", name: "Eoff", unit: "mJ", value: "148.72", range: "自动", energy: true },
  { section: "开通", name: "Ic_on_max", unit: "A", value: "1132.5", range: "自动" },
  { section: "开通", name: "Vce_on_max", unit: "V", value: "8.42", range: "自动" },
  { section: "开通", name: "Ton", unit: "us", value: "2.1043", range: "自动" },
  { section: "开通", name: "Td_on", unit: "us", value: "0.5127", range: "自动" },
  { section: "反向恢复", name: "Vrr", unit: "V", value: "118.40", range: "自动" },
  { section: "反向恢复", name: "Err", unit: "mJ", value: "21.36", range: "自动", energy: true },
];

export const CURSORS = { a: 1.42, b: 1.83, window: [0.15, 2.35] };

/**
 * 每像素列 min/max 包络降采样。
 * 十万点级波形必须做这一步才能保证平移/缩放的帧率；
 * 三个原型共用同一实现，因此渲染成本差异只来自各技术的绘制路径。
 */
export function buildEnvelope(disp, t0, t1, cols, plotW) {
  const per = (t1 - t0) / cols;
  const edge = Math.max(1, Math.round(cols / plotW));
  const out = new Float32Array(cols * 2);
  for (let c = 0; c < cols; c++) {
    const ta = t0 + c * per;
    const tb = ta + per;
    let i0 = Math.floor((ta - T0) / DT);
    let i1 = Math.ceil((tb - T0) / DT);
    if (i1 <= i0) i1 = i0 + 1;
    if (i0 < 0) i0 = 0;
    if (i1 > N) i1 = N;
    let mn = Infinity, mx = -Infinity;
    for (let i = i0; i < i1; i++) {
      const v = disp[i];
      if (v < mn) mn = v;
      if (v > mx) mx = v;
    }
    if (!(mn <= mx)) { mn = 0; mx = 0; }
    out[c * 2] = mn;
    out[c * 2 + 1] = mx;
  }
  return { env: out, cols, edge };
}
