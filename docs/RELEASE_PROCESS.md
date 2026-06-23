# 发布、打包与 GitHub Release 规则

本文记录 DPT 项目的发布和远端操作规则。

## GitHub CLI 提权

- GitHub CLI 发布、上传 Release、推送等涉及远端认证的操作，由于沙箱权限限制需要使用 `sandbox_permissions="require_escalated"` 提权执行。
- `hosts.yml` 没有明文 token 属正常情况。
- Windows 上 `gh` 的 token 通常存放在 Windows 凭据管理器里。
- 读取认证状态或执行 `gh release upload` 等操作时，应说明需要提权访问 Windows 凭据管理器和网络。

## Release 资产命名

- GitHub Release 资产命名必须沿用历史规则：上传的 Windows exe 统一命名为 `DPT_Windows_vX.Y.Z.exe`。
- 本地 PyInstaller 可继续生成中文文件名的 exe。
- 发布前应复制/重命名为 `DPT_Windows_vX.Y.Z.exe` 再上传。
- 不要改成 `DPT_Extractor_*` 或其他临时命名。
- 不要上传中文名导致 GitHub 资产名乱码。

## 发布前检查

- 确认 `dpt_extractor/__init__.py` 的 `__version__`、exe 文件名、Git tag 和 GitHub Release 版本一致。
- 确认固定授权海报 `assets/noncommercial_authorization_poster.png` 没有被常规发布更新覆盖或替换。
- 如果本次发布涉及 TSS 提取、脉冲分段、平台线、损耗窗口、光标落点、积分、斜率、Trr/Err 或任意会影响参数数值的逻辑，必须按 `REGRESSION_BASELINES.md` 跑全量验证。

## 远端操作说明模板

执行涉及 GitHub 远端认证的命令前，向用户说明：

```text
这个操作需要访问 GitHub 网络和 Windows 凭据管理器中的 gh 认证信息，因此需要提权执行。
```
