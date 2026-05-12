# PBDConverter 使用说明摘要

PBDConverter.exe 不是独立源码编译出来的文件，而是 krkrz 的 `tvpwin32.exe` 改名而来。

本包已经附带并自动放入“PBD文件解析配置”目录：

- `PBDConverter.cf`
- `data.xp3`
- `PBDConverter.exe`

解析 PBD 还需要游戏 `plugin` 文件夹中的：

- `json.dll`
- `PackinOne.dll`

从本版开始，用户不需要手动复制这两个 DLL。软件在检测到 JSON/PBD 目录中包含 `.pbd` 文件、且 DLL 尚未配置时，会弹窗让用户选择游戏的 `plugin` 文件夹，然后自动复制 `json.dll` 和 `PackinOne.dll` 到 `PBD文件解析配置`。
