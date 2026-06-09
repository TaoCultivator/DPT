# Windows 可执行程序打包说明

## 环境要求

- Windows 10/11（64 位）
- Python 3.10+（与开发环境一致）
- 建议在**与目标用户相同架构**的机器上打包（amd64）

## 一键打包

在项目根目录 `e:\DPT` 打开 PowerShell：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1
```

成功后生成：

```
dist\DPT_双脉冲参数提取工具_v2.0.5.exe
```

可将该 `.exe` 单独拷贝到其他 Windows 电脑运行，**无需安装 Python**。

## 手动打包

```powershell
cd e:\DPT
pip install -r requirements-build.txt
pyinstaller --noconfirm DPT.spec
```

## 版本规则

版本号统一使用 `vMAJOR.MINOR.PATCH`：

- 大版本更新：修改第一位，例如 `v1.0.0` → `v2.0.0`
- 小版本/功能迭代：修改后两位，例如 `v1.1.1` → `v1.1.2`
- `dpt_extractor/__init__.py` 的 `__version__`、exe 文件名、Git tag 和 GitHub Release 版本必须保持一致
- 固定授权海报位于 `assets/noncommercial_authorization_poster.png`；后续发布更新不得覆盖或替换该文件，只在 README、Release 说明和首次运行弹窗中继续引用它

## 打包产物说明

| 项目 | 说明 |
|------|------|
| 单文件 exe | 首次启动会解压到临时目录，略慢属正常 |
| 内置配置 | `default.yaml` 随 exe 打包 |
| 内置报告模板 | `默认报告模板.xlsx` 随 exe 打包，仅作为公开兜底模板 |
| 内置授权海报 | `assets/noncommercial_authorization_poster.png` 随 exe 打包，首次运行弹窗引用 |
| 用户配置 | 通道映射保存在 `%LOCALAPPDATA%\DPT\channel_maps_user.yaml` |
| 私有报告模板 | 通过 UI 加载，程序只记住本机路径，不随 exe 打包 |
| 最近路径 | 导出/打开目录、报告模板源和项目报告文件由 QSettings 记住（注册表） |

## 常见问题

1. **杀毒软件误报**：PyInstaller 单文件 exe 可能被启发式拦截，可加入白名单或对 `dist` 目录签名。
2. **体积较大**（约 150–250 MB）：含 PyQt6、SciPy、NumPy 等运行时。
3. **打包失败缺少模块**：编辑 `DPT.spec` 的 `hiddenimports` 后重新执行 `pyinstaller --noconfirm DPT.spec`。
4. **需要控制台调试**：将 `DPT.spec` 中 `console=False` 改为 `console=True` 查看报错。

## 目录模式（可选，启动更快）

若希望 `dist\DPT\` 文件夹形式而非单文件，可在 `DPT.spec` 中把末尾 `EXE(...)` 改为 `COLLECT` 模式，或运行：

```powershell
pyinstaller --noconfirm --windowed --name DPT_双脉冲参数提取工具_v2.0.5 --collect-all PyQt6 --collect-all pyqtgraph main.py
```

（体积与依赖收集方式不同，以 `DPT.spec` 为准。）
