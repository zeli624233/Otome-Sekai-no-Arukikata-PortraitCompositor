from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, Iterable, Optional


PBD_CONFIG_DIR_NAME = "PBD文件解析配置"
PBD_CACHE_DIR_NAME = "PBD转换缓存"
PBD_ASSET_DIR_NAME = "pbd_converter_assets"
PBD_DLL_FILES = ("json.dll", "PackinOne.dll")
PBD_CONVERTER_EXE_NAMES = ("PBDConverter.exe", "tvpwin32.exe")
PBD_BUNDLED_FILES = ("PBDConverter.cf", "data.xp3", "PBDConverter.exe")
PBD_CACHE_VERSION = "pbd-json-cache-v2"


class PbdConfigError(RuntimeError):
    """Raised when PBD files are used but the required converter files are missing."""


class PbdConversionError(RuntimeError):
    """Raised when a PBD file could not be converted to JSON."""


def program_base_dir() -> Path:
    """Return the writable program directory used by source runs and frozen EXE builds."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def pbd_config_dir() -> Path:
    """Program subfolder storing PBDConverter assets and copied plugin DLLs."""
    return program_base_dir() / PBD_CONFIG_DIR_NAME


def _resource_path(*parts: str) -> Path:
    if getattr(sys, "_MEIPASS", None):
        return Path(sys._MEIPASS).joinpath(*parts)  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent.parent.joinpath(*parts)


def _bundled_pbd_asset(name: str) -> Path:
    return _resource_path(PBD_ASSET_DIR_NAME, name)


def _is_probably_krkrz_source_root(path: Path) -> bool:
    """Return True for a krkrz source tree, not for a runnable KRKR executable."""
    try:
        return (path / "vcproj" / "tvpwin32.sln").exists() or (path / "HowToBulid.txt").exists()
    except Exception:
        return False


def _find_krkrz_source_roots() -> list[Path]:
    """Find nearby krkrz source folders so the error message can explain the required build step."""
    roots: list[Path] = []
    candidates = [program_base_dir(), pbd_config_dir(), _resource_path(PBD_ASSET_DIR_NAME), Path.cwd()]
    # Also check one and two levels down; users often extract krkrz-1.4.0r2 next to this program.
    expanded: list[Path] = []
    for base in candidates:
        expanded.append(base)
        try:
            for child in base.iterdir():
                if child.is_dir():
                    expanded.append(child)
                    for grand in child.iterdir():
                        if grand.is_dir():
                            expanded.append(grand)
        except Exception:
            pass
    seen: set[str] = set()
    for path in expanded:
        try:
            resolved = path.resolve()
        except Exception:
            resolved = path
        key = str(resolved).lower()
        if key not in seen and _is_probably_krkrz_source_root(resolved):
            seen.add(key)
            roots.append(resolved)
    return roots


def _candidate_converter_paths(config_dir: Path) -> list[Path]:
    """Return likely locations for a runnable PBDConverter.exe / tvpwin32.exe.

    PBDConverter-main's README says PBDConverter.exe is not a separate project:
    it is the KRKRZ runtime tvpwin32.exe renamed to PBDConverter.exe. The GitHub
    source archive of krkrz does not contain this exe; it must be built or taken
    from a binary release. This function therefore searches for either file name
    in explicit nearby locations, including common krkr release output folders.
    """
    bases: list[Path] = []
    for base in (
        config_dir,
        program_base_dir(),
        _resource_path(PBD_ASSET_DIR_NAME),
        Path.cwd(),
    ):
        try:
            base = base.resolve()
        except Exception:
            pass
        if base not in bases:
            bases.append(base)

    paths: list[Path] = []
    for base in bases:
        for name in PBD_CONVERTER_EXE_NAMES:
            paths.append(base / name)
            paths.append(base / "bin" / "win32" / name)
            paths.append(base / "Release" / name)
            paths.append(base / "Debug" / name)

    # Check one level of subfolders under the program directory and config dir.
    # This covers extracting krkrz_20171225r2.7z or a build output folder beside the program.
    for root in (program_base_dir(), config_dir, Path.cwd()):
        try:
            for child in root.iterdir():
                if not child.is_dir() or child.name in {PBD_CONFIG_DIR_NAME, PBD_CACHE_DIR_NAME}:
                    continue
                for name in PBD_CONVERTER_EXE_NAMES:
                    paths.extend(
                        [
                            child / name,
                            child / "bin" / "win32" / name,
                            child / "Release" / name,
                            child / "Debug" / name,
                            child / "vcproj" / "Release" / name,
                            child / "vcproj" / "Debug" / name,
                        ]
                    )
        except Exception:
            pass

    out: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path).lower()
        if key not in seen:
            seen.add(key)
            out.append(path)
    return out


def ensure_pbd_config_folder() -> Path:
    """Create the PBD config folder and copy the bundled TJS converter assets into it."""
    cfg = pbd_config_dir()
    cfg.mkdir(parents=True, exist_ok=True)

    for name in PBD_BUNDLED_FILES:
        src = _bundled_pbd_asset(name)
        dst = cfg / name
        try:
            if src.exists() and (not dst.exists() or dst.stat().st_size <= 0):
                shutil.copy2(src, dst)
        except Exception:
            # The folder may be read-only on some systems; the later conversion
            # error will give the user a clearer actionable message.
            pass

    readme = cfg / "请先阅读.txt"
    readme_text = (
        "这里是 PBD 文件解析配置目录。\n\n"
        "PBDConverter-main 的 README 说明如下：PBDConverter.exe 本质上就是 krkrz 的 tvpwin32.exe 改名而来。\n"
        "本版已经内置 PBDConverter.cf、data.xp3 和 PBDConverter.exe。\n\n"
        "使用 JSON/PBD 目录里的 .pbd 文件时，如果本目录还没有 json.dll 和 PackinOne.dll，\n"
        "软件会自动弹窗让你选择游戏的 plugin 文件夹。选择后，软件会把这两个 DLL 复制到本目录。\n\n"
        "通常需要选择的文件夹类似：游戏目录/plugin\n"
        "其中应包含：\n"
        "1. json.dll\n"
        "2. PackinOne.dll\n\n"
        "转换后的 JSON 会缓存在本目录下的 PBD转换缓存 文件夹中。\n"
    )
    try:
        if not readme.exists() or readme.read_text(encoding="utf-8", errors="ignore") != readme_text:
            readme.write_text(readme_text, encoding="utf-8")
    except Exception:
        pass
    return cfg


def find_pbd_converter_exe(config_dir: Optional[Path] = None) -> Optional[Path]:
    cfg = config_dir or ensure_pbd_config_folder()
    for path in _candidate_converter_paths(cfg):
        if path.exists() and path.is_file() and path.suffix.lower() == ".exe":
            return path
    return None


def missing_pbd_config_files(config_dir: Optional[Path] = None) -> list[str]:
    cfg = config_dir or ensure_pbd_config_folder()
    missing = [name for name in PBD_DLL_FILES if not (cfg / name).exists()]
    if find_pbd_converter_exe(cfg) is None:
        if _find_krkrz_source_roots():
            missing.append("可运行的 PBDConverter.exe/tvpwin32.exe（已检测到 krkrz 源码，但源码需要先编译）")
        else:
            missing.append("PBDConverter.exe 或 tvpwin32.exe")
    # The bundled files are copied automatically, but report them too if copying failed.
    for name in PBD_BUNDLED_FILES:
        path = cfg / name
        if not path.exists() or path.stat().st_size <= 0:
            missing.append(name)
    return missing


def missing_pbd_dll_files(config_dir: Optional[Path] = None) -> list[str]:
    """Return missing game plugin DLL names required by PBDConverter."""
    cfg = config_dir or ensure_pbd_config_folder()
    return [name for name in PBD_DLL_FILES if not (cfg / name).exists()]


def install_pbd_dlls_from_plugin_folder(plugin_dir: str | Path, config_dir: Optional[Path] = None) -> Path:
    """Copy json.dll and PackinOne.dll from a user-selected game plugin folder.

    The GUI calls this when it detects .pbd input and the DLLs have not been
    configured yet, so users no longer need to manually copy the files.
    """
    cfg = config_dir or ensure_pbd_config_folder()
    plugin = Path(plugin_dir).expanduser().resolve()
    if not plugin.exists() or not plugin.is_dir():
        raise PbdConfigError(f"请选择有效的游戏 plugin 文件夹：{plugin}")

    missing = [name for name in PBD_DLL_FILES if not (plugin / name).exists()]
    if missing:
        raise PbdConfigError(
            "选择的文件夹中没有找到 PBD 解析需要的 DLL："
            + "、".join(missing)
            + "\n\n请重新选择游戏目录下真正的 plugin 文件夹。"
        )

    cfg.mkdir(parents=True, exist_ok=True)
    for name in PBD_DLL_FILES:
        shutil.copy2(plugin / name, cfg / name)
    return cfg


def pbd_configuration_error_message(missing: Optional[Iterable[str]] = None) -> str:
    cfg = ensure_pbd_config_folder()
    missing_list = list(missing if missing is not None else missing_pbd_config_files(cfg))
    missing_text = "、".join(missing_list) if missing_list else "必要文件"
    source_roots = _find_krkrz_source_roots()
    source_note = ""
    if source_roots:
        source_note = (
            "\n\n已检测到 krkrz 源码目录，但源码目录不能直接当作 PBDConverter 使用。\n"
            "处理方法：在 Windows 上用 Visual Studio 2012 Update 4 或更新版本打开源码里的 vcproj/tvpwin32.sln，"
            "安装并配置 nasm 后编译 tvpwin32 项目；然后把生成的 bin/win32/tvpwin32.exe 复制到 PBD 文件解析配置目录，"
            "可保留文件名 tvpwin32.exe，也可重命名为 PBDConverter.exe。\n"
            "检测到的源码目录：\n- " + "\n- ".join(str(p) for p in source_roots[:3])
        )
    return (
        "检测到 JSON/PBD 目录中包含 .pbd 文件，但 PBD 文件解析配置未完成。\n\n"
        f"缺少：{missing_text}\n\n"
        "图形界面会在检测到 PBD 输入时自动弹窗，让你选择游戏的 plugin 文件夹；\n"
        "选择后会自动复制 json.dll 和 PackinOne.dll 到配置目录。\n"
        "PBDConverter.cf、data.xp3 和 PBDConverter.exe 已由程序自动放入。\n"
        f"{source_note}\n\n"
        f"配置目录：{cfg}"
    )


def ensure_pbd_configuration_ready() -> Path:
    cfg = ensure_pbd_config_folder()
    missing = missing_pbd_config_files(cfg)
    if missing:
        raise PbdConfigError(pbd_configuration_error_message(missing))
    return cfg


def _source_digest(path: Path) -> str:
    resolved = Path(path).resolve()
    try:
        stat = resolved.stat()
        size = stat.st_size
        mtime_ns = stat.st_mtime_ns
    except OSError:
        size = -1
        mtime_ns = -1
    key = "|".join(
        [
            PBD_CACHE_VERSION,
            str(resolved).lower(),
            str(size),
            str(mtime_ns),
        ]
    )
    return hashlib.sha256(key.encode("utf-8", "surrogatepass")).hexdigest()


def cached_json_path_for_pbd(path: str | Path) -> Path:
    source = Path(path).expanduser().resolve()
    digest = _source_digest(source)
    # A separate digest directory keeps the returned JSON stem identical to the
    # original PBD stem, so SINFO matching still works as expected.
    return pbd_config_dir() / PBD_CACHE_DIR_NAME / digest[:16] / f"{source.stem}.json"


def _copy_pbd_to_cache_input(source: Path, cache_json: Path) -> Path:
    cache_dir = cache_json.parent
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_pbd = cache_dir / f"{source.stem}.pbd"
    try:
        if not cache_pbd.exists() or cache_pbd.stat().st_size != source.stat().st_size:
            shutil.copy2(source, cache_pbd)
    except Exception:
        shutil.copy2(source, cache_pbd)
    try:
        (cache_dir / "来源.txt").write_text(str(source), encoding="utf-8")
    except Exception:
        pass
    return cache_pbd


def convert_pbd_to_json_cache(path: str | Path, force: bool = False, timeout: int = 180) -> Path:
    """Convert one .pbd file to a cached JSON file by invoking PBDConverter."""
    source = Path(path).expanduser().resolve()
    if not source.exists() or not source.is_file() or source.suffix.lower() != ".pbd":
        raise PbdConversionError(f"不是有效的 PBD 文件: {source}")

    cfg = ensure_pbd_configuration_ready()
    cache_json = cached_json_path_for_pbd(source)
    if cache_json.exists() and cache_json.stat().st_size > 0 and not force:
        return cache_json

    converter = find_pbd_converter_exe(cfg)
    if converter is None:
        raise PbdConfigError(pbd_configuration_error_message(["PBDConverter.exe 或 tvpwin32.exe"]))

    cache_pbd = _copy_pbd_to_cache_input(source, cache_json)
    if cache_json.exists():
        try:
            cache_json.unlink()
        except Exception:
            pass

    cmd = [str(converter), f"-input={str(cache_pbd)}"]
    creationflags = 0
    if sys.platform.startswith("win"):
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        result = subprocess.run(
            cmd,
            cwd=str(cfg),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=creationflags,
        )
    except FileNotFoundError as exc:
        raise PbdConfigError(pbd_configuration_error_message(["PBDConverter.exe 或 tvpwin32.exe"])) from exc
    except subprocess.TimeoutExpired as exc:
        raise PbdConversionError(f"PBD 转 JSON 超时: {source}") from exc
    except Exception as exc:
        raise PbdConversionError(f"PBD 转 JSON 启动失败: {source}\n{exc}") from exc

    if result.returncode != 0:
        details = "\n".join(x for x in [result.stdout.strip(), result.stderr.strip()] if x)
        raise PbdConversionError(f"PBD 转 JSON 失败: {source}\n{details}".strip())

    if not cache_json.exists() or cache_json.stat().st_size <= 0:
        details = "\n".join(x for x in [result.stdout.strip(), result.stderr.strip()] if x)
        raise PbdConversionError(
            f"PBD 转 JSON 后未生成结果文件: {cache_json}\n"
            f"源文件: {source}\n"
            f"输出信息: {details or '无'}"
        )

    return cache_json


def convert_pbd_files_to_json_cache(
    pbd_paths: list[Path],
    max_workers: Optional[int] = None,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> list[Path]:
    """Convert multiple PBD files, returning cached JSON paths in the original order."""
    if not pbd_paths:
        return []
    ensure_pbd_configuration_ready()
    total = len(pbd_paths)
    if progress_callback:
        progress_callback(0, total)

    workers = max(1, int(max_workers or min(total, os.cpu_count() or 1)))
    workers = min(workers, total)
    results: dict[Path, Path] = {}

    if workers <= 1:
        for idx, path in enumerate(pbd_paths, start=1):
            results[path] = convert_pbd_to_json_cache(path)
            if progress_callback:
                progress_callback(idx, total)
    else:
        done = 0
        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_map = {executor.submit(convert_pbd_to_json_cache, path): path for path in pbd_paths}
            for future in as_completed(future_map):
                src = future_map[future]
                results[src] = future.result()
                done += 1
                if progress_callback:
                    progress_callback(done, total)

    return [results[path] for path in pbd_paths]


def has_pbd_input(path: str | Path) -> bool:
    p = Path(path).expanduser()
    if p.is_file():
        return p.suffix.lower() == ".pbd"
    if p.is_dir():
        try:
            return any(child.is_file() and child.suffix.lower() == ".pbd" for child in p.iterdir())
        except OSError:
            return False
    return False
