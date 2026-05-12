# Otome Portrait Compositor Ver1.2

A GUI compositing tool for portrait-difference resources from *Otome Sekai no Arukikata*. It reads layer spatial coordinates from **JSON or PBD**, infers clothing/expression relationships from **SINFO**, and then composites matching **PNG or TLG** layers into a final PNG image.

This repository package is organized based on Ver1.2. It keeps the current icon resources and also retains the sample images, test images, and analysis documents included in the repository.

## Main Features

- Load `JSON/PBD directory + SINFO directory + PNG/TLG directory`
- Automatically identify poses, body/clothing, expressions, and blush layers
- Real-time compositing preview on the right side
- Export the current PNG
- Batch export all combinations for the current pose
- Supports skipping the “no expression” combination
- Batch export defaults to all available logical CPU threads and can also be adjusted manually
- Optionally open the output folder automatically after export
- Can be called by other scripts as a Python module
- Uses a custom application icon when packaged for Windows, applied to the window top-left icon, taskbar icon, and background process icon

## Requirements

- Python 3.10+
- Windows 10/11 recommended
- Dependency: `Pillow`

Install dependencies:

```bash
pip install -r requirements.txt
```

## Run from Source

```bash
python main.py
```

On Windows, you can also run:

```bat
run_from_source.bat
```

## Batch Export

Export all combinations for all poses:

```bash
python batch_export.py --json-dir ./json_or_pbd --sinfo-dir ./sinfo --png-dir ./png_or_tlg --out-dir ./output --all-combos
```

Skipping the “no expression” combination is the default behavior. To include no-expression combinations:

```bash
python batch_export.py --json-dir ./json_or_pbd --sinfo-dir ./sinfo --png-dir ./png_or_tlg --out-dir ./output --all-combos --include-no-expression
```

Export using 8 threads:

```bash
python batch_export.py --json-dir ./json_or_pbd --sinfo-dir ./sinfo --png-dir ./png_or_tlg --out-dir ./output --all-combos --workers 8
```


## PBD Input

The `JSON/PBD directory` can contain `.json` or `.pbd` files. If a `.pbd` file does not have a matching `.json` file with the same stem, the program invokes the bundled PBDConverter script and caches the converted JSON under `PBD文件解析配置/PBD转换缓存`.

Before using PBD files, the program creates a `PBD文件解析配置` folder in the program directory and places `PBDConverter.cf`, `data.xp3`, and `PBDConverter.exe` there. PBDConverter-main explains that `PBDConverter.exe` is the krkrz `tvpwin32.exe` renamed. This package already includes it. When you load a JSON/PBD directory that contains `.pbd` files, the GUI checks for `json.dll` and `PackinOne.dll`; if they are not configured yet, it asks you to select the game's `plugin` folder and automatically copies the two DLLs into `PBD文件解析配置`. Manual copying is no longer required in the GUI.

## TLG Input and Loading

The `PNG/TLG directory` can contain `.png` or `.tlg` layer files. The program matches files by `pose_layerId.png/.tlg`, decoded `pose_layerId.png/.tlg`, and `layerId.png/.tlg`; when both PNG and TLG exist for the same layer, PNG is preferred.

When TLG files are detected, clicking “Load Project” shows a loading progress bar. This version preloads TLG layers with multiple CPU worker processes instead of a Python thread pool, so CPU-bound TLG decoding can bypass the Python GIL and use multiple logical CPU threads more effectively. The UI is unlocked only after the preload finishes.

## Directory Structure

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

## License

This repository is licensed under the [MIT License](LICENSE).
