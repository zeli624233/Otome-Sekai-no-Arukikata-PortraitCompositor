# オトメ世界の歩き方 立绘合成器 Ver1.2 / Otome Portrait Compositor Ver1.2

用于《オトメ世界の歩き方》立绘差分资源的 GUI 合成工具。从 **JSON 或 PBD** 读取图层空间坐标，从 **SINFO** 推断衣服/表情关系，再将同名 **PNG 或 TLG** 图层合成为最终 PNG。

这份仓库包基于 Ver1.2 版本整理，保留了当前图标资源，并保留了仓库中的示例图、测试图和分析文档。

## 主要功能

- 加载 `JSON/PBD 目录 + SINFO 目录 + PNG/TLG 目录`
- 自动识别姿势、身体服装、表情、红晕
- 右侧实时预览合成结果
- 导出当前 PNG
- 批量导出当前姿势全部组合
- 支持跳过“无表情”组合
- 批量导出默认使用本机全部 CPU 逻辑线程，也可手动选择线程数
- 加载项目生成 TLG 缓存时可手动选择 CPU 线程数，默认使用本机 CPU 逻辑线程数的 50% + 1
- 可选择导出完成后自动打开文件夹
- 可作为 Python 模块被其他脚本调用
- Windows 打包时使用自定义程序图标，作用于窗口左上角、任务栏和后台进程图标

## 环境要求

- Python 3.10+
- Windows 10/11 推荐
- 依赖：`Pillow`

安装依赖：

```bash
pip install -r requirements.txt
```

## 运行源码

```bash
python main.py
```

Windows 也可以直接运行：

```bat
run_from_source.bat
```

## 批量导出

导出全部姿势的全部组合：

```bash
python batch_export.py --json-dir ./json_or_pbd --sinfo-dir ./sinfo --png-dir ./png_or_tlg --out-dir ./output --all-combos
```

跳过“无表情”是默认行为。若要包含无表情组合：

```bash
python batch_export.py --json-dir ./json_or_pbd --sinfo-dir ./sinfo --png-dir ./png_or_tlg --out-dir ./output --all-combos --include-no-expression
```

使用 8 线程导出：

```bash
python batch_export.py --json-dir ./json_or_pbd --sinfo-dir ./sinfo --png-dir ./png_or_tlg --out-dir ./output --all-combos --workers 8
```


## PBD 输入说明

`JSON/PBD 目录` 可以放 `.json`，也可以放 `.pbd`。如果目录中存在 `.pbd` 且没有同名 `.json`，程序会先调用 PBD 转换器把 PBD 转成 JSON 缓存，再继续按原来的 JSON 逻辑加载。转换后的 JSON 会缓存在程序子文件夹 `PBD文件解析配置/PBD转换缓存` 中。

首次使用 PBD 前，程序会自动在软件目录下创建 `PBD文件解析配置` 文件夹，并自动放入 `PBDConverter.cf`、`data.xp3` 和 `PBDConverter.exe`。PBDConverter-main 的 README 里说明：`PBDConverter.exe` 本质上就是 krkrz 的 `tvpwin32.exe` 改名而来。本版已经内置该 exe。加载包含 `.pbd` 的 JSON/PBD 目录时，如果还没有配置游戏 `plugin` 文件夹中的 `json.dll` 和 `PackinOne.dll`，软件会弹窗让用户选择游戏的 `plugin` 文件夹，并自动复制这两个 DLL 到 `PBD文件解析配置`，不需要再手动放入。

## TLG 输入说明

`PNG/TLG 目录` 可以直接选择包含 `.png` 或 `.tlg` 图层文件的文件夹。程序会按 `姿势名_图层ID.png/.tlg`、`解码后的姿势名_图层ID.png/.tlg`、`图层ID.png/.tlg` 的顺序匹配；同名 PNG 与 TLG 同时存在时优先使用 PNG。TLG 解码器内置支持 TLG0/TLG5/TLG6，无需先手动转换成 PNG。

## 目录结构

```text
otome-portrait-compositor-v13-full/
├─ assets/
│  ├─ app_icon.ico
│  ├─ app_icon.png
│  ├─ app_icon_preview.png
│  └─ brand_portrait.png
├─ otome_tlg_compositor/
│  ├─ __init__.py
│  ├─ __main__.py
│  ├─ core.py
│  ├─ gui.py
│  ├─ tlg_decoder.py
│  └─ pbd_converter.py
├─ PROJECT_ANALYSIS_マユミ.md
├─ PROJECT_ANALYSIS_ユイ.md
├─ PROJECT_ANALYSIS_サキ.md
├─ analyze_project.py
├─ batch_export.py
├─ build_release_zip.bat
├─ build_windows_exe.bat
├─ clean_build_artifacts.bat
├─ example_call.py
├─ LICENSE
├─ main.py
├─ pyproject.toml
├─ README.md
├─ README_中文.md
├─ requirements.txt
├─ run_from_source.bat
├─ run_windows.bat
├─ pbd_converter_assets/
│  ├─ PBDConverter.cf
│  ├─ data.xp3
│  └─ PBDConverter.exe
├─ otome_tlg_json_sinfo_compositor.spec
├─ sample_partial_preview.png
├─ test_out.png
└─ test_v6.png
```

## 本仓库源码采用 [MIT License](LICENSE)。

## TLG 缓存说明

- 在 PNG/TLG 目录中放入 `.tlg` 文件时，点击“加载项目”后会先显示“加载进度”。
- 程序不会把所有 TLG 图层长期预加载到内存，而是把解码后的 PNG 缓存在程序子文件夹 `缓存目录` 中。
- 再次选择同一个 PNG/TLG 目录时，程序会先检查 `缓存目录`；已缓存的 TLG 会直接读取缓存 PNG，不再重复解码。
- 未命中的 TLG 会按界面中“加载项目时使用的CPU线程数”设置，使用多进程并行写入缓存；默认值为本机 CPU 逻辑线程数的 50% + 1，完成后才允许选择组合选项。
- 同名 `.png` 和 `.tlg` 同时存在时，仍优先使用 `.png`。
- 如果源 `.tlg` 文件被修改，程序会按新的文件大小/修改时间生成新缓存；如果想强制全部重建，可以删除 `缓存目录`。
