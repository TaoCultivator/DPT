1. github cli发布由于沙箱权限问题需要提权，hosts.yml 里没有明文 token（正常情况）。在 Windows 上，gh 通常把 token 存在 Windows 凭据管理器里。
2. 参数数值的计算千万别改；涉及提取、测量、积分、斜率、时间窗等计算逻辑时，除非用户明确要求，否则只允许改展示层、交互层或样式。
3. 不要擅自新增弹窗提示、悬浮提示（ToolTip）或一次性提示；如确实需要，必须先说明用途并获得用户明确同意。
4. GitHub Release 资产命名必须沿用历史规则：上传的 Windows exe 统一命名为 `DPT_Windows_vX.Y.Z.exe`。本地 PyInstaller 可继续生成中文文件名的 exe，但发布前应复制/重命名为该资产名再上传；不要改成 `DPT_Extractor_*` 或其他临时命名，也不要上传中文名导致 GitHub 资产名乱码。
