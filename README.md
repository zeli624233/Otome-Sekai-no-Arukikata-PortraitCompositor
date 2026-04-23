# Otome-Sekai-no-Arukikata-PortraitCompositor
# オトメ世界の歩き 人物立绘 合成工具
# 使用说明 How To Use

![image](https://github.com/zeli624233/Otome-Sekai-no-Arukikata-PortraitCompositor/blob/main/%E4%BD%BF%E7%94%A8%E8%AF%B4%E6%98%8E%20How%20To%20Use.png)


# 如果您没有PNG的图片，请使用这个仓库：https://github.com/vn-tools/tlg2png的工具来转换，JSON文件我已在

# オトメ世界の歩き方 立绘合成器 Ver1.0 / Otome Portrait Compositor Ver1.0

用于《オトメ世界の歩き方》立绘差分资源的 GUI 合成工具。从 **JSON** 读取图层空间坐标，从 **SINFO** 推断衣服/表情关系，再将同名 **PNG** 图层合成为最终 PNG。

这份仓库包基于 Ver1.0 版本整理，保留了当前图标资源，并保留了仓库中的示例图、测试图和分析文档。

## 主要功能

- 加载 `JSON 目录 + SINFO 目录 + PNG 目录`
- 自动识别姿势、身体服装、表情、红晕
- 右侧实时预览合成结果
- 导出当前 PNG
- 批量导出当前姿势全部组合
- 支持跳过“无表情”组合
- 支持 2 / 4 / 6 / 8 / 12 / 16 线程批量导出
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
python batch_export.py --json-dir ./json --sinfo-dir ./sinfo --png-dir ./png_output --out-dir ./output --all-combos
```

跳过“无表情”是默认行为。若要包含无表情组合：

```bash
python batch_export.py --json-dir ./json --sinfo-dir ./sinfo --png-dir ./png_output --out-dir ./output --all-combos --include-no-expression
```

使用 8 线程导出：

```bash
python batch_export.py --json-dir ./json --sinfo-dir ./sinfo --png-dir ./png_output --out-dir ./output --all-combos --workers 8
```

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
│  └─ gui.py
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
├─ otome_tlg_json_sinfo_compositor.spec
├─ sample_partial_preview.png
├─ test_out.png
└─ test_v6.png
   ```

# 感谢

这个软件是用于合成 オトメ世界の歩き 人物立绘的，该项目的诞生参考了很多大神的Github的库，在此一并感谢！

PSB 文件转换成 JSON 文件参考了Gitai大佬（ https://github.com/zhaomaoniu ）的代码，非常感谢，曾一度以为没办法转换呢，幸好有大佬的仓库！：（ https://github.com/zhaomaoniu/PBDConverter ）

TLG 文件转换成 PNG  文件参考了rr- 大佬（ https://github.com/rr- ）的代码，使用批处理脚本，真快！，不用手动复制了！：（ https://github.com/vn-tools/tlg2png ）

XP3 游戏资源的解包离不开YeLike大佬（ https://github.com/YeLikesss ）的KrkrExtractV2 (ForCxdecV2) 动态工具集，对付加密的 Cxdec V2游戏真有一手！：（ https://github.com/YeLikesss/KrkrExtractForCxdecV2 ）

游戏原文件文件名的还原离不开UlyssesWu大佬（ https://github.com/UlyssesWu ）的FreeMote工具，有文件的哈希值配合这个工具，游戏的文件原名轻松找到！：（ https://github.com/UlyssesWu/FreeMote ）

This software is designed for composing character stand sprites for Otome Sekai no Aruki. The development of this project drew on numerous excellent repositories from talented developers on GitHub, and we express our sincere gratitude to all of them!

The conversion of PSB files to JSON files references the code by Gitai (https://github.com/zhaomaoniu) — our heartfelt thanks! We once thought this conversion would be impossible, and we’re so grateful for their repository: （https://github.com/zhaomaoniu/PBDConverter）

The conversion of TLG files to PNG files references the code by rr- (https://github.com/rr-). Using the batch script is incredibly fast, no more manual copying! Repository link:（ https://github.com/vn-tools/tlg2png ）

The extraction of XP3 game resources would not be possible without the KrkrExtractV2 (ForCxdecV2) dynamic toolset by YeLike (https://github.com/YeLikesss) — this tool is truly masterful at handling games encrypted with Cxdec V2! Repository link: （https://github.com/YeLikesss/KrkrExtractForCxdecV2）

Restoring the original filenames of the game’s source files relies on the FreeMote tool by UlyssesWu (https://github.com/UlyssesWu). With file hash values paired with this tool, retrieving the original game filenames is a breeze! Repository link: （https://github.com/UlyssesWu/FreeMote）









