# DPT 双脉冲测试参数提取工具

从 Tekscope 导出的双脉冲测试（Double Pulse Test）CSV 波形中，自动提取关断、开通、反向恢复参数，并提供与测试表格一致的分区 GUI 展示与 Excel 导出。

## 功能

- 解析 TekscopeSW 宽表 CSV（自动识别 CH1–CH6、MATH1… 等列）
- 多脉冲（最多 10 个门极脉冲）：参数表右上角可选「关断第 N 波 / 开通第 N 波」，默认第 1 波关断、第 2 波开通
- 支持 **U / V / W 三相**，每相 **上桥 (H)** / **下桥 (L)** 共 6 种组合（UH/UL/VH/VL/WH/WL）
- 自动识别双脉冲并分割：脉冲1关断、脉冲2开通、反向恢复
- 按 IEC 60747-9 / JEDEC 风格计算时间参数（10%/90% 阈值，可在配置中修改）
- Vdc 从关断前 Vce 稳态平台自动测量
- Eoff / Eon / Err：按 **IEC60747-9** 标准窗口对 **∫V×I dt** 积分（mJ）
- PyQt6 波形显示 + 三区彩色参数表 + Excel 导出

## 安装

```bash
cd e:\DPT
pip install -r requirements.txt
```

## 运行

```bash
python main.py
```

1. 点击 **打开 CSV**，选择对应相别文件（如 `UH_*.csv`、`VL_*.csv`、`WH_*.csv`）
2. 工具栏 **相别 (U/V/W)** + **桥臂 (上桥/下桥)** 可手动切换；文件名含 `UH/UL/VH/VL/WH/WL` 时会自动识别
3. **Vdc** 默认为「自动」（波形测量）；输入数值后点击 **重新计算** 可固定 Vdc
4. **通道映射**：将各逻辑量映射到 CSV 列；**上桥默认**总电流为 **Irr(CH3)+IL(CH4)** 软件相加，可不使用示波器 MATH1（下桥仍可映射单通道 Ic）
5. **导出 Excel** 按 MCU2506 列序**自动生成**工作簿（不复制外部模板）；默认文件名为 **与 CSV 同名**（`.xlsx`），测试数据写入第 5 行

### Excel 报告

导出文件包含单 Sheet「`*_双脉冲数据`」，表头 4 行（信息 / 关断 / 开通+反向恢复 / 列名+单位），**第 5 行**写入本次提取结果。列序 A–AK 与 MCU2506 规范一致（含关断/开通串扰、Eoff/Eon/Err 等）。

## 通道映射

加载 CSV 时会根据示波器 **Label 行**自动匹配通道，兼容 **IGBT**（Vge/Vce/Ic/IC_VL）与 **MOSFET**（Vgs/Vds/Id/IVL）命名。电流逻辑：上桥总电流 = 下桥支路电流 + IL；下桥反向恢复 = 总电流 − IL。可在「通道映射」中手动调整，或点 **按标签识别** 重新识别。

U/V/W 三相 **通道接线相同**，仅被测器件与文件命名不同：

| 逻辑量 | 上桥 (UH/VH/WH) | 下桥 (UL/VL/WL) |
|--------|-----------------|-----------------|
| Vge | CH1 | CH6 |
| Vce | CH2 | CH5 |
| Ic | **Irr+IL（软件）** / 可改单通道 | CH3 |
| IL | CH4 | CH4 |
| Irr | CH3（与 IL 相加得 Ic） | **Ic−IL（软件）** / 可改单通道 |
| V_diode | CH5 | CH2 |
| Vge_other | CH6 | CH1 |

## 配置

编辑 [`dpt_extractor/config/default.yaml`](dpt_extractor/config/default.yaml) 可调整：

- 阈值百分比、脉冲检测平滑宽度
- 关断/开通/反向恢复时间窗宽度
- 斜率分位数、能量校验容差

## 打包为 Windows exe

详见 [BUILD.md](BUILD.md)。在项目根目录执行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1
```

产物：`dist\DPT_双脉冲参数提取工具_v1.1.2.exe`（单文件，可拷贝到其他 Windows 电脑运行）。

## 版本规则

版本号统一使用 `vMAJOR.MINOR.PATCH`，例如 `v1.0.0`。

- 大版本更新：修改第一位，例如 `v1.0.0` → `v2.0.0`
- 小版本/功能迭代：修改后两位，例如 `v1.1.1` → `v1.1.2`
- Python 包内版本写在 [`dpt_extractor/__init__.py`](dpt_extractor/__init__.py)，Git tag 与 GitHub Release 使用同一个 `v` 前缀版本号

## 测试

```bash
python -m unittest dpt_extractor.tests.test_extract -v
```

## 项目结构

```
dpt_extractor/
  io/tek_parser.py       # CSV 解析
  models/                # 通道映射与结果结构
  detect/                # 脉冲检测与时间窗
  metrics/               # 参数算法
  pipeline/extract.py    # 提取编排
  gui/                   # PyQt6 界面
  export/                # Excel 导出
main.py
```

## 能量计算（IEC60747-9）

| 参数 | t₁ | t₂ |
|------|----|----|
| Eoff | Vge 降至 10% | Ic 降至 2%×Icm |
| Eon | Vge 升至 10% | Vce 降至 2%×Vdc |
| Err | Vd 升至 10%×Vdm | Irr 回落至 2%×Irm |

斜率：**关断** di/dt 阈值 = 关断前电流 **Top（100% Ic 平台）** 的百分比起止，在 Vge 下降窗内搜穿越；**关断** dv/dt 阈值 = 母线 **Vce Top** 的百分比起止（与工况 Top 一致）。开通斜率待规格书截图后再统一（当前仍为上一版逻辑）。

## 说明

- 界面为深色主题；损耗以 V×I 积分为准
- 下桥 CSV 表头 Label 与上桥相同，程序仅按 `BridgeProfile` 映射，不读 Label 行
