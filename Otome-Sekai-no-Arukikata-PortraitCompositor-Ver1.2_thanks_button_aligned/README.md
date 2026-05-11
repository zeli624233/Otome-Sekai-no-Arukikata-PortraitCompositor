# Otome-Sekai-no-Arukikata-PortraitCompositor
这个软件是用于合成オトメ世界の歩き 人物立绘的，该项目的诞生参考了很多大神的Github的库，在此一并感谢！Otome Sekai no Arukikata — Otome PortraitCompositor: this software is for composing character portraits of the work. Its development references numerous excellent open-source repos from great GitHub developers, and we offer our sincere thanks to them all!


## 本版新增

- 输入目录中的“JSON 目录”已改为“JSON/PBD 目录”。
- 支持在 JSON/PBD 目录中放入 `.pbd` 文件；程序会通过 `PBD文件解析配置` 调用 PBDConverter 转成 JSON 缓存后再加载。
- 软件目录下新增 `PBD文件解析配置`，程序已内置 `PBDConverter.cf`、`data.xp3` 和 `PBDConverter.exe`。检测到 `.pbd` 输入且缺少 `json.dll` / `PackinOne.dll` 时，会弹窗让用户选择游戏的 `plugin` 文件夹，并自动复制这两个 DLL，不再需要手动放入。
