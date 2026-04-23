# Otome Portrait Compositor Ver1.0

A GUI compositing tool for portrait-difference resources from *Otome Sekai no Arukikata*. It reads layer spatial coordinates from **JSON**, infers clothing/expression relationships from **SINFO**, and then composites matching **PNG** layers into a final PNG image.

This repository package is organized based on Ver1.0. It keeps the current icon resources and also retains the sample images, test images, and analysis documents included in the repository.

## Main Features

- Load `JSON directory + SINFO directory + PNG directory`
- Automatically identify poses, body/clothing, expressions, and blush layers
- Real-time compositing preview on the right side
- Export the current PNG
- Batch export all combinations for the current pose
- Supports skipping the “no expression” combination
- Supports multi-threaded batch export with 2 / 4 / 6 / 8 / 12 / 16 threads
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
python batch_export.py --json-dir ./json --sinfo-dir ./sinfo --png-dir ./png_output --out-dir ./output --all-combos
```

Skipping the “no expression” combination is the default behavior. To include no-expression combinations:

```bash
python batch_export.py --json-dir ./json --sinfo-dir ./sinfo --png-dir ./png_output --out-dir ./output --all-combos --include-no-expression
```

Export using 8 threads:

```bash
python batch_export.py --json-dir ./json --sinfo-dir ./sinfo --png-dir ./png_output --out-dir ./output --all-combos --workers 8
```

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

## License

This repository is licensed under the [MIT License](LICENSE).
