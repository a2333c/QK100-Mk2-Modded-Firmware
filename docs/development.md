# 开发与离线核验

## 目录与依赖

`desktop-flasher/` 是 Electron 桌面外壳，`tools/flasher/index.html` 是刷写界面及协议实现。`firmware/` 保存固定版本的官方文件和修改版，构建脚本会核对其 SHA256，再复制进应用。`tools/` 还包含三个固件补丁生成器。

需要 Node.js、npm 和 Python 3.11。桌面依赖版本由 `desktop-flasher/package-lock.json` 锁定；固件重建依赖见根目录 `requirements.txt`。以下命令均在仓库根目录执行。

## 运行、测试和构建

```powershell
npm --prefix desktop-flasher ci
npm test
py -3.11 -m pip install -r requirements.txt
py -3.11 tests/rebuild_firmware.py
npm run desktop:start
```

`npm test` 运行 31 项协议与界面测试，以及 5 项桌面权限和资源测试。固件重建检查会核对 6 个文件的哈希，再从官方文件在内存中重建 3 个修改版，要求逐字节一致。两种离线检查都不连接或写入设备。

构建 Windows x64 便携应用：

```powershell
npm run desktop:build
npm --prefix desktop-flasher run verify-package
```

输出在 `desktop-flasher/release/`。打包检查核对 7 个内置资源及运行源码。构建产物、依赖目录和缓存已排除在 Git 之外。

Release 提供的是整理源码前已经验证过的应用 1.0.3，SHA256 为 `fe2c86d8eec99b3e489538bf629b2e897e7f6b9f6d6f902621537dd0724eb603`。公开源码仅调整了资源路径及开发脚本，运行源码和 7 个资源与发布应用一致。打包元数据会影响 EXE 哈希，本地重建的 EXE 不保证与 Release 文件逐字节一致。

## 补丁重建范围

`tests/rebuild_firmware.py` 给出了最终参数组合。屏幕生成器提供多个历史参数；使用默认参数并不等于发布的 v20。请以重建测试中的参数和发布哈希为准，避免把实验候选当成成品。

- 主控：`tools/patch_no_brightness_floor.py` 和 `tools/fw_repack.py`。
- 屏幕：`tools/build_screen_ui_candidate.py` 及其字模、汇编依赖。
- 可选图包：`tools/build_island_candidate.py`。

补丁行为、验证限制和刷写步骤分别见 [固件改动说明](firmware-changes.md) 和 [使用说明](../README.md)。
