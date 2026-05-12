from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import threading
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from PIL import Image, ImageDraw

from .tlg_decoder import read_tlg
from .pbd_converter import (
    PbdConfigError,
    PbdConversionError,
    convert_pbd_files_to_json_cache,
    ensure_pbd_config_folder,
)


DEFAULT_EXPRESSION_LABEL = "无表情"
DEFAULT_BLUSH_LABEL = "无红晕"
DEFAULT_SPECIAL_LABEL = "无特殊"


def detect_cpu_threads() -> int:
    """Return the number of logical CPU threads available to the program."""
    return max(1, os.cpu_count() or 1)


def program_base_dir() -> Path:
    """Return the writable program directory used for persistent caches."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def default_cache_root() -> Path:
    """Cache directory requested by the user: a program subfolder named 缓存目录."""
    return program_base_dir() / "缓存目录"


class ProjectError(Exception):
    pass


_HASHU_RE = re.compile(r"#U([0-9a-fA-F]{4,6})")


def decode_hashu(text: str) -> str:
    def repl(match: re.Match[str]) -> str:
        try:
            return chr(int(match.group(1), 16))
        except Exception:
            return match.group(0)

    return _HASHU_RE.sub(repl, text)


def natural_sort_key(text: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", text)]


_TEXT_ENCODINGS = ("utf-8", "utf-8-sig", "cp932", "shift_jis", "gbk", "utf-16")


def read_text_any(path: Path) -> str:
    raw = path.read_bytes()
    for enc in _TEXT_ENCODINGS:
        try:
            return raw.decode(enc)
        except Exception:
            continue
    return raw.decode("utf-8", errors="replace")


def read_json_any(path: Path):
    raw = path.read_bytes()
    for enc in _TEXT_ENCODINGS:
        try:
            return json.loads(raw.decode(enc))
        except Exception:
            continue
    return json.loads(raw.decode("utf-8", errors="replace"))


def read_sinfo_lines(path: Optional[Path]) -> list[str]:
    if not path or not path.exists():
        return []
    text = read_text_any(path)
    return [line.strip("\ufeff").strip() for line in text.splitlines() if line.strip()]


@dataclass(slots=True)
class LayerEntry:
    layer_id: int
    name: str
    group_id: Optional[int]
    top_group_name: str
    left: int
    top: int
    width: int
    height: int
    opacity: int
    visible: bool
    draw_index: int

    @property
    def label(self) -> str:
        if self.top_group_name and self.top_group_name != "表情":
            return f"{self.top_group_name} / {self.name}"
        return self.name

    @property
    def area(self) -> int:
        return max(self.width, 0) * max(self.height, 0)


@dataclass(slots=True)
class Scene:
    json_path: Path
    sinfo_path: Optional[Path]
    canvas_width: int
    canvas_height: int
    layers: list[LayerEntry]
    body_layers: list[LayerEntry]
    expression_layers: list[LayerEntry]
    blush_layers: list[LayerEntry]
    special_layers: list[LayerEntry] = field(default_factory=list)
    fixed_layers: list[LayerEntry] = field(default_factory=list)
    default_body_id: Optional[int] = None
    default_expression_id: Optional[int] = None
    default_blush_id: Optional[int] = None
    default_special_id: Optional[int] = None
    pose_name: str = ""
    sinfo_order: list[str] = field(default_factory=list)

    @property
    def stem(self) -> str:
        return self.json_path.stem

    @property
    def decoded_stem(self) -> str:
        return decode_hashu(self.json_path.stem)

    @property
    def pose_label(self) -> str:
        return f"{self.decoded_stem} ({self.canvas_width}x{self.canvas_height})"

    @property
    def label(self) -> str:
        pose = f" / {self.pose_name}" if self.pose_name else ""
        return f"{self.decoded_stem}{pose} ({self.canvas_width}x{self.canvas_height})"


@dataclass(slots=True)
class CompositionSelection:
    scene_index: int
    body_id: Optional[int]
    expression_id: Optional[int]
    blush_id: Optional[int]
    special_id: Optional[int]


@dataclass(slots=True)
class ResolvedImage:
    layer: LayerEntry
    path: Optional[Path]
    status: str


@dataclass(slots=True)
class ComposeResult:
    image: Image.Image
    warnings: list[str]
    matched: list[ResolvedImage]



def _load_rgba_image_uncached(path: Path, opacity: int) -> Image.Image:
    """Open PNG/TLG and return a standalone RGBA Pillow image.

    This helper is intentionally module-level so it can be reused by the
    multiprocessing preload workers on Windows/PyInstaller builds.
    """
    if path.suffix.lower() == ".tlg":
        out = read_tlg(path).convert("RGBA")
    else:
        with Image.open(path) as im:
            out = im.convert("RGBA")

    opacity = int(opacity)
    if opacity < 255:
        alpha = out.getchannel("A").point(lambda p: int(p * opacity / 255.0))
        out.putalpha(alpha)
    return out


def _decode_tlg_to_cache_worker(path_str: str, cache_path_str: str) -> tuple[str, str]:
    """Decode one TLG file in a separate process and save it as cached PNG.

    The worker writes the decoded image directly to disk instead of returning raw
    RGBA bytes to the parent process.  This avoids the big IPC/memory copy that
    made the previous preload-to-RAM design slow and memory-hungry.
    """
    source = Path(path_str)
    cache_path = Path(cache_path_str)
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    if cache_path.exists() and cache_path.stat().st_size > 0:
        return str(source.resolve()), str(cache_path.resolve())

    tmp_path = cache_path.with_name(f"{cache_path.name}.tmp.{os.getpid()}")
    img = read_tlg(source).convert("RGBA")
    try:
        # compress_level=1 keeps cache writing fast.  The cache is for speed,
        # not for long-term archival compression.
        img.save(tmp_path, format="PNG", compress_level=1)
        os.replace(tmp_path, cache_path)
        return str(source.resolve()), str(cache_path.resolve())
    finally:
        try:
            img.close()
        except Exception:
            pass
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except Exception:
            pass


class TlgDiskCache:
    """Persistent TLG decode cache stored under the program's 缓存目录 folder."""

    CACHE_VERSION = "tlg-disk-cache-v1"

    def __init__(self, source_root: Optional[str | Path] = None, cache_root: Optional[str | Path] = None) -> None:
        self.source_root = Path(source_root).expanduser().resolve() if source_root else None
        self.cache_root = Path(cache_root).expanduser().resolve() if cache_root else default_cache_root()
        source_id = str(self.source_root).lower() if self.source_root else "default"
        self.directory_key = hashlib.sha256(source_id.encode("utf-8", "surrogatepass")).hexdigest()[:16]
        self.directory = self.cache_root / self.directory_key

    def _source_digest(self, path: Path) -> str:
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
                self.CACHE_VERSION,
                str(self.source_root or resolved.parent).lower(),
                str(resolved).lower(),
                str(size),
                str(mtime_ns),
            ]
        )
        return hashlib.sha256(key.encode("utf-8", "surrogatepass")).hexdigest()

    def cache_path_for(self, path: Path) -> Path:
        return self.directory / f"{self._source_digest(path)}.png"

    def is_cached(self, path: Path) -> bool:
        cache_path = self.cache_path_for(path)
        try:
            return cache_path.exists() and cache_path.stat().st_size > 0
        except OSError:
            return False

    def cached_path_if_ready(self, path: Path) -> Optional[Path]:
        cache_path = self.cache_path_for(path)
        try:
            if cache_path.exists() and cache_path.stat().st_size > 0:
                return cache_path
        except OSError:
            return None
        return None

    def write_readme(self) -> None:
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            readme = self.directory / "缓存说明.txt"
            if not readme.exists():
                src = str(self.source_root) if self.source_root else "未指定"
                readme.write_text(
                    "这里是程序自动生成的 TLG 解码缓存。\n"
                    "同一个 PNG/TLG 目录再次加载时，程序会优先读取这里已经缓存好的 PNG，"
                    "不再重复解码对应的 TLG。\n\n"
                    f"源目录: {src}\n"
                    "如源 TLG 文件被修改，程序会自动生成新的缓存文件。\n"
                    "如果想强制重建缓存，可以删除本文件夹。\n",
                    encoding="utf-8",
                )
        except Exception:
            pass


class ImageProvider:
    SUPPORTED_EXTENSIONS = (".png", ".tlg")

    def __init__(self, root_dirs: list[Path], png_dir: Optional[str | Path] = None) -> None:
        self.root_dirs = [Path(p).resolve() for p in root_dirs if p]
        # 保留 png_dir 这个参数名，兼容旧脚本；现在它代表“图层图片目录”，可放 PNG 或 TLG。
        self.png_dir = Path(png_dir).expanduser().resolve() if png_dir else None
        self.tlg_cache = TlgDiskCache(self.png_dir)
        self._image_index: dict[str, Path] = {}

        search_dirs: list[Path] = []
        if self.png_dir and self.png_dir.exists():
            search_dirs.append(self.png_dir)
        for root in self.root_dirs:
            if root.exists():
                search_dirs.append(root)

        seen: set[Path] = set()
        for directory in search_dirs:
            if directory in seen or not directory.exists():
                continue
            seen.add(directory)
            self._index_image_dir(directory)

    def _prefer_new_path(self, old: Optional[Path], new: Path) -> bool:
        if old is None:
            return True
        # 同名 PNG 与 TLG 同时存在时，优先使用已经转好的 PNG。
        if old.suffix.lower() == ".tlg" and new.suffix.lower() == ".png":
            return True
        return False

    def _add_index_key(self, key: str, path: Path) -> None:
        key = key.lower()
        old = self._image_index.get(key)
        if self._prefer_new_path(old, path):
            self._image_index[key] = path.resolve()

    def _index_image_dir(self, directory: Path) -> None:
        files: list[Path] = []
        try:
            with os.scandir(directory) as it:
                for entry in it:
                    if entry.is_file() and Path(entry.name).suffix.lower() in self.SUPPORTED_EXTENSIONS:
                        files.append(Path(entry.path))
        except FileNotFoundError:
            return
        for path in sorted(files, key=lambda p: natural_sort_key(p.name)):
            decoded_name = decode_hashu(path.name)
            decoded_stem = decode_hashu(path.stem)
            for key in {
                path.name,
                path.stem,
                decoded_name,
                decoded_stem,
            }:
                self._add_index_key(key, path)

    def _image_candidates(self, scene: Scene, layer: LayerEntry) -> list[str]:
        bases = [
            f"{scene.stem}_{layer.layer_id}",
            f"{scene.decoded_stem}_{layer.layer_id}",
            f"{layer.layer_id}",
        ]
        candidates: list[str] = []
        for base in bases:
            for ext in self.SUPPORTED_EXTENSIONS:
                candidates.append(f"{base}{ext}")
            candidates.append(base)
        return candidates

    def resolve(self, scene: Scene, layer: LayerEntry) -> ResolvedImage:
        for key in self._image_candidates(scene, layer):
            hit = self._image_index.get(key.lower())
            if hit and hit.exists():
                suffix = hit.suffix.lower()
                if suffix == ".tlg":
                    status = "TLG 缓存命中" if self.tlg_cache.is_cached(hit) else "TLG 命中"
                else:
                    status = "PNG 命中"
                return ResolvedImage(layer=layer, path=hit, status=status)
        return ResolvedImage(layer=layer, path=None, status="未找到对应 PNG/TLG")

    # Kept for compatibility with Project.close(); persistent TLG cache is now
    # disk based, so loading a project no longer fills this RAM cache.
    _cache_lock = threading.RLock()
    _rgba_cache: dict[tuple[str, int], Image.Image] = {}

    def open_rgba(self, path: Path, opacity: int) -> Image.Image:
        """Open PNG/TLG as RGBA, preferring the persistent TLG disk cache.

        For TLG, the cache stores the decoded image without layer opacity.  The
        opacity is applied after opening the cached PNG, so a single cache file
        can be reused by any JSON layer that references the same TLG.
        """
        load_path = Path(path)
        if load_path.suffix.lower() == ".tlg":
            cached = self.tlg_cache.cached_path_if_ready(load_path)
            if cached is not None:
                load_path = cached
        return _load_rgba_image_uncached(load_path, int(opacity))

    @classmethod
    def clear_cache(cls) -> None:
        with cls._cache_lock:
            for image in cls._rgba_cache.values():
                try:
                    image.close()
                except Exception:
                    pass
            cls._rgba_cache.clear()

    def ensure_tlg_disk_cache(
        self,
        items: list[Path],
        progress_callback: Optional[Callable[[int, int], None]] = None,
        max_workers: Optional[int] = None,
    ) -> tuple[int, int, int]:
        """Ensure TLG files are decoded into the persistent 缓存目录 cache.

        Returns (cached_count, newly_converted_count, total_count).
        """
        unique_items: list[Path] = []
        seen: set[str] = set()
        for path in items:
            resolved = str(Path(path).resolve())
            if resolved in seen:
                continue
            seen.add(resolved)
            unique_items.append(Path(path).resolve())

        total = len(unique_items)
        if total <= 0:
            if progress_callback:
                try:
                    progress_callback(0, 0)
                except Exception:
                    pass
            return 0, 0, 0

        self.tlg_cache.write_readme()
        cached = [path for path in unique_items if self.tlg_cache.is_cached(path)]
        missing = [path for path in unique_items if not self.tlg_cache.is_cached(path)]
        cached_count = len(cached)

        if progress_callback:
            try:
                progress_callback(cached_count, total)
            except Exception:
                pass

        if not missing:
            return cached_count, 0, total

        worker_count = max(1, int(max_workers or detect_cpu_threads()))
        worker_count = min(worker_count, len(missing))

        converted = 0
        first_error: Optional[BaseException] = None

        def mark_progress(done_missing: int) -> None:
            if progress_callback:
                try:
                    progress_callback(cached_count + done_missing, total)
                except Exception:
                    pass

        # Single task: avoid process startup overhead.
        if worker_count <= 1:
            for done, path in enumerate(missing, start=1):
                try:
                    _decode_tlg_to_cache_worker(str(path), str(self.tlg_cache.cache_path_for(path)))
                    converted += 1
                except BaseException as exc:
                    if first_error is None:
                        first_error = exc
                finally:
                    mark_progress(done)
        else:
            with ProcessPoolExecutor(max_workers=worker_count) as executor:
                future_map = {
                    executor.submit(_decode_tlg_to_cache_worker, str(path), str(self.tlg_cache.cache_path_for(path))): path
                    for path in missing
                }
                done = 0
                for future in as_completed(future_map):
                    done += 1
                    try:
                        future.result()
                        converted += 1
                    except BaseException as exc:
                        if first_error is None:
                            first_error = exc
                    finally:
                        mark_progress(done)

        if first_error is not None:
            raise first_error
        return cached_count, converted, total


def collect_json_or_pbd_paths(
    input_path: str | Path,
    pbd_workers: Optional[int] = None,
    pbd_progress_callback: Optional[Callable[[int, int], None]] = None,
) -> tuple[list[Path], Path]:
    """Collect JSON files from a JSON/PBD directory or convert PBD files to cached JSON.

    Returns (json_paths, source_root).  source_root is the user's original JSON/PBD
    directory (or the parent folder if a single JSON/PBD file was typed manually).
    """
    ensure_pbd_config_folder()
    path = Path(input_path).expanduser().resolve()
    if not path.exists():
        raise ProjectError("请选择有效的 JSON/PBD 目录或文件。")

    if path.is_file():
        suffix = path.suffix.lower()
        if suffix == ".json":
            return [path], path.parent
        if suffix == ".pbd":
            try:
                return convert_pbd_files_to_json_cache([path], max_workers=1, progress_callback=pbd_progress_callback), path.parent
            except (PbdConfigError, PbdConversionError) as exc:
                raise ProjectError(str(exc)) from exc
        raise ProjectError("请选择有效的 JSON/PBD 目录，或单个 .json/.pbd 文件。")

    if not path.is_dir():
        raise ProjectError("请选择有效的 JSON/PBD 目录或文件。")

    json_paths = sorted(path.glob("*.json"), key=lambda p: natural_sort_key(p.name))
    pbd_paths = sorted(path.glob("*.pbd"), key=lambda p: natural_sort_key(p.name))

    if pbd_paths:
        # If a JSON with the same stem already exists, prefer the user's JSON and
        # avoid requiring PBD configuration for that duplicate PBD.
        existing_json_stems = {p.stem.lower() for p in json_paths}
        pbd_to_convert = [p for p in pbd_paths if p.stem.lower() not in existing_json_stems]
        if pbd_to_convert:
            try:
                converted = convert_pbd_files_to_json_cache(
                    pbd_to_convert,
                    max_workers=pbd_workers,
                    progress_callback=pbd_progress_callback,
                )
            except (PbdConfigError, PbdConversionError) as exc:
                raise ProjectError(str(exc)) from exc
            json_paths.extend(converted)

    json_paths = sorted(json_paths, key=lambda p: natural_sort_key(p.name))
    if not json_paths:
        raise ProjectError("JSON/PBD 目录中没有找到 .json 或 .pbd 文件。")
    return json_paths, path


class Project:
    def __init__(self, scenes: list[Scene], image_provider: ImageProvider, json_dir: Path, sinfo_dir: Optional[Path], png_dir: Optional[Path]) -> None:
        self.scenes = scenes
        self.image_provider = image_provider
        self.json_dir = json_dir
        self.sinfo_dir = sinfo_dir
        self.png_dir = png_dir

    @classmethod
    def from_directories(
        cls,
        json_dir: str | Path,
        sinfo_dir: Optional[str | Path] = None,
        png_dir: Optional[str | Path] = None,
        pbd_workers: Optional[int] = None,
        pbd_progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> "Project":
        json_input_path = Path(json_dir).expanduser().resolve()
        json_paths, json_source_root = collect_json_or_pbd_paths(
            json_input_path,
            pbd_workers=pbd_workers,
            pbd_progress_callback=pbd_progress_callback,
        )

        sinfo_path = Path(sinfo_dir).expanduser().resolve() if sinfo_dir else None
        if sinfo_path and not sinfo_path.exists():
            raise ProjectError("SINFO 目录不存在。")
        if sinfo_path and not sinfo_path.is_dir():
            raise ProjectError("请选择有效的 SINFO 目录。")

        png_path = Path(png_dir).expanduser().resolve() if png_dir else None
        if png_path and (not png_path.exists() or not png_path.is_dir()):
            raise ProjectError("请选择有效的 PNG/TLG 目录。")

        sinfo_map: dict[str, Path] = {}
        if sinfo_path:
            sinfo_map = {p.stem: p for p in sinfo_path.glob("*.sinfo")}

        max_workers = min(8, max(2, detect_cpu_threads()))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            scenes = list(executor.map(lambda p: parse_scene(p, sinfo_map.get(p.stem)), json_paths))
        scenes.sort(key=lambda s: natural_sort_key(s.json_path.name))

        provider = ImageProvider(root_dirs=[json_source_root, *( [sinfo_path] if sinfo_path else [] )], png_dir=png_path)
        return cls(scenes=scenes, image_provider=provider, json_dir=json_source_root, sinfo_dir=sinfo_path, png_dir=png_path)

    def close(self) -> None:
        ImageProvider.clear_cache()

    def _all_selectable_layers(self) -> list[tuple[Scene, LayerEntry]]:
        result: list[tuple[Scene, LayerEntry]] = []
        for scene in self.scenes:
            seen_ids: set[int] = set()
            ordered_layers = (
                sorted(scene.fixed_layers, key=lambda x: x.draw_index)
                + sorted(scene.body_layers, key=lambda x: x.draw_index)
                + sorted(scene.expression_layers, key=lambda x: x.draw_index)
                + sorted(scene.blush_layers, key=lambda x: x.draw_index)
                + sorted(scene.special_layers, key=lambda x: x.draw_index)
            )
            for layer in ordered_layers:
                if layer.layer_id in seen_ids:
                    continue
                seen_ids.add(layer.layer_id)
                result.append((scene, layer))
        return result

    def tlg_preload_items(self) -> list[Path]:
        """Unique TLG source files referenced by selectable project layers.

        The historical method name is kept so the GUI/batch script remains
        compatible, but it now means "files that should exist in disk cache".
        """
        items: list[Path] = []
        seen: set[str] = set()
        for scene, layer in self._all_selectable_layers():
            resolved = self.image_provider.resolve(scene, layer)
            if not resolved.path or resolved.path.suffix.lower() != ".tlg":
                continue
            key = str(resolved.path.resolve())
            if key in seen:
                continue
            seen.add(key)
            items.append(resolved.path)
        return items

    def tlg_preload_count(self) -> int:
        return len(self.tlg_preload_items())

    def tlg_cache_status(self) -> tuple[int, int]:
        items = self.tlg_preload_items()
        cached = sum(1 for path in items if self.image_provider.tlg_cache.is_cached(path))
        return cached, len(items)

    def preload_tlg_images(
        self,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        max_workers: Optional[int] = None,
    ) -> tuple[int, int, int]:
        return self.image_provider.ensure_tlg_disk_cache(self.tlg_preload_items(), progress_callback, max_workers=max_workers)

    def find_scene(self, scene_stem: str) -> Scene:
        for scene in self.scenes:
            if scene.stem == scene_stem or scene.decoded_stem == scene_stem or scene.pose_label == scene_stem:
                return scene
        raise ProjectError(f"未找到姿势: {scene_stem}")

    def scene_index(self, scene_stem: str) -> int:
        for i, scene in enumerate(self.scenes):
            if scene.stem == scene_stem or scene.decoded_stem == scene_stem or scene.pose_label == scene_stem:
                return i
        raise ProjectError(f"未找到姿势: {scene_stem}")

    def make_selection(
        self,
        scene_stem: str,
        body_label: Optional[str] = None,
        expression_name: Optional[str] = None,
        blush_name: Optional[str] = None,
        special_name: Optional[str] = None,
    ) -> CompositionSelection:
        idx = self.scene_index(scene_stem)
        scene = self.scenes[idx]

        body_id = scene.default_body_id
        if body_label:
            body_map = {layer.label: layer.layer_id for layer in scene.body_layers}
            if body_label in body_map:
                body_id = body_map[body_label]
            else:
                for layer in scene.body_layers:
                    if layer.top_group_name == body_label or layer.name == body_label:
                        body_id = layer.layer_id
                        break

        if expression_name is None:
            expr_id = scene.default_expression_id
        elif expression_name == DEFAULT_EXPRESSION_LABEL:
            expr_id = None
        else:
            expr_id = next((layer.layer_id for layer in scene.expression_layers if layer.name == expression_name), None)

        if blush_name is None:
            blush_id = scene.default_blush_id
        elif blush_name == DEFAULT_BLUSH_LABEL:
            blush_id = None
        else:
            blush_id = next((layer.layer_id for layer in scene.blush_layers if layer.name == blush_name), None)

        if special_name is None:
            special_id = scene.default_special_id
        elif special_name == DEFAULT_SPECIAL_LABEL:
            special_id = None
        else:
            special_id = next((layer.layer_id for layer in scene.special_layers if layer.name == special_name or layer.label == special_name), None)

        return CompositionSelection(
            scene_index=idx,
            body_id=body_id,
            expression_id=expr_id,
            blush_id=blush_id,
            special_id=special_id,
        )

    def _selected_layers(self, selection: CompositionSelection) -> list[LayerEntry]:
        scene = self.scenes[selection.scene_index]
        fixed_layers = sorted(scene.fixed_layers, key=lambda x: x.draw_index)
        body_layers: list[LayerEntry] = []
        expression_layers: list[LayerEntry] = []
        blush_layers: list[LayerEntry] = []
        special_layers: list[LayerEntry] = []

        body_layer = next((x for x in scene.body_layers if x.layer_id == selection.body_id), None)
        if body_layer is None and scene.body_layers:
            body_layer = next((x for x in scene.body_layers if x.layer_id == scene.default_body_id), scene.body_layers[0])
        if body_layer:
            body_layers.append(body_layer)

        expr_layer = next((x for x in scene.expression_layers if x.layer_id == selection.expression_id), None)
        if expr_layer:
            expression_layers.append(expr_layer)

        blush_layer = next((x for x in scene.blush_layers if x.layer_id == selection.blush_id), None)
        if blush_layer:
            blush_layers.append(blush_layer)

        special_layer = next((x for x in scene.special_layers if x.layer_id == selection.special_id), None)
        if special_layer:
            special_layers.append(special_layer)

        return (
            fixed_layers
            + sorted(special_layers, key=lambda x: x.draw_index)
            + sorted(body_layers, key=lambda x: x.draw_index)
            + sorted(expression_layers, key=lambda x: x.draw_index)
            + sorted(blush_layers, key=lambda x: x.draw_index)
        )

    def compose(self, selection: CompositionSelection) -> ComposeResult:
        scene = self.scenes[selection.scene_index]
        canvas = Image.new("RGBA", (scene.canvas_width, scene.canvas_height), (0, 0, 0, 0))
        warnings: list[str] = []
        matched: list[ResolvedImage] = []

        for layer in self._selected_layers(selection):
            resolved = self.image_provider.resolve(scene, layer)
            matched.append(resolved)
            if not resolved.path:
                warnings.append(f"{layer.label} [{layer.layer_id}]：{resolved.status}")
                continue
            try:
                part = self.image_provider.open_rgba(resolved.path, layer.opacity)
                canvas.alpha_composite(part, (layer.left, layer.top))
            except Exception as exc:
                warnings.append(f"{layer.label} [{layer.layer_id}] 打开失败: {exc}")

        return ComposeResult(image=canvas, warnings=warnings, matched=matched)

    def make_preview(self, selection: CompositionSelection, max_size: tuple[int, int]) -> tuple[Image.Image, float, ComposeResult]:
        scene = self.scenes[selection.scene_index]
        result = self.compose(selection)
        bg = create_checkerboard((scene.canvas_width, scene.canvas_height))
        bg.alpha_composite(result.image, (0, 0))
        scale = min(max_size[0] / max(scene.canvas_width, 1), max_size[1] / max(scene.canvas_height, 1), 1.0)
        preview_size = (max(1, int(scene.canvas_width * scale)), max(1, int(scene.canvas_height * scale)))
        resample = getattr(Image, "Resampling", Image).LANCZOS
        preview = bg.resize(preview_size, resample)
        return preview, scale, result

    def export_current(self, output_path: str | Path, selection: CompositionSelection) -> list[str]:
        result = self.compose(selection)
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        result.image.save(output_path)
        result.image.close()
        return result.warnings

    def _build_scene_export_jobs(
        self,
        scene: Scene,
        out_dir: Path,
        include_no_expression: bool,
    ) -> list[tuple[CompositionSelection, Path]]:
        if scene.expression_layers:
            expr_names = [x.name for x in scene.expression_layers]
            if include_no_expression:
                expr_names = [DEFAULT_EXPRESSION_LABEL] + expr_names
        else:
            expr_names = [DEFAULT_EXPRESSION_LABEL]

        blush_names = [DEFAULT_BLUSH_LABEL] + [x.name for x in scene.blush_layers]
        special_names = [DEFAULT_SPECIAL_LABEL] + [x.name for x in scene.special_layers]
        jobs: list[tuple[CompositionSelection, Path]] = []
        for body_layer in scene.body_layers:
            for expr_name in expr_names:
                for blush_name in blush_names:
                    for special_name in special_names:
                        sel = self.make_selection(
                            scene_stem=scene.stem,
                            body_label=body_layer.label,
                            expression_name=expr_name,
                            blush_name=blush_name,
                            special_name=special_name,
                        )
                        out_name = build_output_name(scene, body_layer.label, expr_name, blush_name, special_name)
                        jobs.append((sel, out_dir / out_name))
        return jobs

    def _render_and_save_job(self, selection: CompositionSelection, out_path: Path) -> Path:
        result = self.compose(selection)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        result.image.save(out_path)
        result.image.close()
        return out_path

    def export_scene_all_combinations(
        self,
        scene_stem: str,
        output_dir: str | Path,
        include_no_expression: bool = False,
        workers: int = 2,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> list[Path]:
        scene = self.find_scene(scene_stem)
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        jobs = self._build_scene_export_jobs(scene, out_dir, include_no_expression)
        total_jobs = len(jobs)
        if progress_callback:
            try:
                progress_callback(0, total_jobs)
            except Exception:
                pass
        if not jobs:
            return []

        worker_count = max(1, int(workers or 2))
        if worker_count <= 1:
            exported: list[Path] = []
            for idx, (selection, out_path) in enumerate(jobs, start=1):
                exported.append(self._render_and_save_job(selection, out_path))
                if progress_callback:
                    try:
                        progress_callback(idx, total_jobs)
                    except Exception:
                        pass
            return exported

        exported: list[Path] = []
        completed = 0
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            future_map = {executor.submit(self._render_and_save_job, selection, out_path): out_path for selection, out_path in jobs}
            for future in as_completed(future_map):
                exported.append(future.result())
                completed += 1
                if progress_callback:
                    try:
                        progress_callback(completed, total_jobs)
                    except Exception:
                        pass
        exported.sort(key=lambda p: natural_sort_key(p.name))
        return exported

    def export_all_scenes_all_combinations(
        self,
        output_dir: str | Path,
        include_no_expression: bool = False,
        workers: int = 2,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> list[Path]:
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        jobs: list[tuple[CompositionSelection, Path]] = []
        for scene in self.scenes:
            scene_dir = out_dir / sanitize_filename(scene.decoded_stem)
            scene_dir.mkdir(parents=True, exist_ok=True)
            jobs.extend(self._build_scene_export_jobs(scene, scene_dir, include_no_expression))
        total_jobs = len(jobs)
        if progress_callback:
            try:
                progress_callback(0, total_jobs)
            except Exception:
                pass
        if not jobs:
            return []

        worker_count = max(1, int(workers or 2))
        if worker_count <= 1:
            exported: list[Path] = []
            for idx, (selection, out_path) in enumerate(jobs, start=1):
                exported.append(self._render_and_save_job(selection, out_path))
                if progress_callback:
                    try:
                        progress_callback(idx, total_jobs)
                    except Exception:
                        pass
        else:
            exported = []
            completed = 0
            with ThreadPoolExecutor(max_workers=worker_count) as executor:
                future_map = {executor.submit(self._render_and_save_job, selection, out_path): out_path for selection, out_path in jobs}
                for future in as_completed(future_map):
                    exported.append(future.result())
                    completed += 1
                    if progress_callback:
                        try:
                            progress_callback(completed, total_jobs)
                        except Exception:
                            pass
        exported.sort(key=lambda p: (natural_sort_key(p.parent.name), natural_sort_key(p.name)))
        return exported

    def analysis_report(self) -> str:
        lines: list[str] = []
        lines.append("差分合成规律分析")
        lines.append("=" * 24)
        lines.append("")
        lines.append(f"共发现 {len(self.scenes)} 个姿势(JSON/PBD/SINFO 组合)。")
        lines.append(f"JSON/PBD 目录: {self.json_dir}")
        lines.append(f"SINFO 目录: {self.sinfo_dir if self.sinfo_dir else '无'}")
        lines.append(f"PNG/TLG 目录: {self.png_dir if self.png_dir else '无'}")
        lines.append("")
        for idx, scene in enumerate(self.scenes, start=1):
            lines.append(f"[姿势 {idx}] {scene.pose_label}")
            lines.append(f"- JSON: {scene.json_path.name}")
            lines.append(f"- SINFO: {scene.sinfo_path.name if scene.sinfo_path else '无'}")
            lines.append(f"- 画布: {scene.canvas_width} x {scene.canvas_height}")
            lines.append(f"- 身体服装选项: {', '.join(layer.label for layer in scene.body_layers)}")
            lines.append(f"- 表情选项: {', '.join(layer.name for layer in scene.expression_layers) if scene.expression_layers else '无'}")
            lines.append(f"- 红晕选项: {', '.join(layer.name for layer in scene.blush_layers) if scene.blush_layers else '无'}")
            lines.append(f"- 特殊选项: {', '.join(layer.name for layer in scene.special_layers) if scene.special_layers else '无'}")
            lines.append("")
        lines.append("结论")
        lines.append("- 姿势及其图片分辨率选项由已加载的 JSON/SINFO 文件集合决定，每个 JSON 对应一个姿势。")
        lines.append("- 非“表情”顶层组里的图片层作为身体服装候选。")
        lines.append("- “表情”组中名称以“頬”开头的是红晕，其余归为表情。")
        lines.append("- 名称类似“規制マスク / mask / マスク”的独立可见或可选图层会归入“特殊”选项，例如白色遮罩效果。")
        lines.append("- 最终输出 = 1 张身体底图 + 0/1 张表情 + 0/1 张红晕 + 0/1 张特殊效果，按 JSON 中 left/top 合成。")
        return "\n".join(lines)


def create_checkerboard(size: tuple[int, int], cell: int = 20) -> Image.Image:
    w, h = size
    img = Image.new("RGBA", size, (235, 235, 235, 255))
    draw = ImageDraw.Draw(img)
    c1 = (235, 235, 235, 255)
    c2 = (210, 210, 210, 255)
    for y in range(0, h, cell):
        for x in range(0, w, cell):
            draw.rectangle([x, y, x + cell - 1, y + cell - 1], fill=c1 if ((x // cell) + (y // cell)) % 2 == 0 else c2)
    return img


def sanitize_filename(text: str) -> str:
    text = text.strip().replace("/", "_").replace("\\", "_")
    text = re.sub(r"[<>:\"|?*]", "_", text)
    text = re.sub(r"\s+", " ", text)
    return text or "unnamed"


def build_output_name(scene: Scene, body_label: str, expression_name: str, blush_name: str, special_name: str = DEFAULT_SPECIAL_LABEL) -> str:
    return sanitize_filename(f"{scene.decoded_stem}__{body_label}__{expression_name}__{blush_name}__{special_name}.png")


EXPRESSION_GROUP_NAMES = {"表情", "差分", "顔", "颜", "フェイス", "face", "顔差分", "表情差分", "差分表情"}
EXPRESSION_NAME_HINTS = {"微笑", "にっこり", "薄ら笑い", "真剣", "怒り", "寂しい", "呆れ", "驚き", "すまし", "恍惚", "笑", "泣", "照れ", "赤面", "困", "怒", "悲", "喜"}
SPECIAL_NAME_HINTS = {"規制", "マスク", "mask", "遮罩", "特殊", "モザイク", "mosaic", "censor", "censorship"}


def _is_special_layer(layer: LayerEntry) -> bool:
    low = layer.name.lower()
    return any(h.lower() in low for h in SPECIAL_NAME_HINTS)


def _is_expression_group(group_name: str, children: list[LayerEntry], canvas_w: int, canvas_h: int) -> bool:
    name = group_name.strip()
    low = name.lower()
    if name in EXPRESSION_GROUP_NAMES or low in EXPRESSION_GROUP_NAMES:
        return True
    if not children:
        return False
    child_names = [c.name for c in children]
    if any(n.startswith("頬") for n in child_names):
        return True
    if sum(any(h in n for h in EXPRESSION_NAME_HINTS) for n in child_names) >= max(2, len(child_names) // 2):
        return True
    canvas_area = max(canvas_w * canvas_h, 1)
    avg_area = sum(c.area for c in children) / max(len(children), 1)
    lefts = [c.left for c in children]
    tops = [c.top for c in children]
    rights = [c.left + c.width for c in children]
    bottoms = [c.top + c.height for c in children]
    bbox_area = max((max(rights) - min(lefts)) * (max(bottoms) - min(tops)), 1)
    if len(children) >= 3 and avg_area < canvas_area * 0.08 and bbox_area < canvas_area * 0.12:
        return True
    return False


def parse_scene(json_path: Path, sinfo_path: Optional[Path]) -> Scene:
    data = read_json_any(json_path)
    if not isinstance(data, list) or not data or not isinstance(data[0], dict):
        raise ProjectError(f"JSON 结构不符合预期: {json_path}")
    canvas = data[0]
    canvas_w = int(canvas.get("width", 0))
    canvas_h = int(canvas.get("height", 0))
    entries = [x for x in data[1:] if isinstance(x, dict)]
    top_groups = [x for x in entries if x.get("layer_type") == 2 or x.get("group_layer_id") is None]
    image_entries = [x for x in entries if x.get("layer_type") == 0]

    top_group_by_id = {int(x["layer_id"]): x for x in top_groups if "layer_id" in x}
    images_by_gid: dict[int, list[dict]] = {}
    for entry in image_entries:
        gid = entry.get("group_layer_id")
        if gid is None:
            continue
        images_by_gid.setdefault(int(gid), []).append(entry)

    sinfo_lines = read_sinfo_lines(sinfo_path)
    path_order = {line: i for i, line in enumerate(sinfo_lines)}
    top_name_by_gid = {gid: str(group.get("name", "")) for gid, group in top_group_by_id.items()}
    fallback_map = {id(entry): i for i, entry in enumerate(image_entries)}

    def sort_key(entry: dict) -> tuple[int, int]:
        top_name = top_name_by_gid.get(int(entry.get("group_layer_id", -1)), "")
        name = str(entry.get("name", ""))
        path_name = f"{top_name}/{name}"
        fallback_index = fallback_map[id(entry)]
        return (path_order.get(path_name, 10_000 + fallback_index), fallback_index)

    ordered_images = sorted(image_entries, key=sort_key)

    layer_entries: list[LayerEntry] = []
    for draw_index, entry in enumerate(ordered_images):
        gid = entry.get("group_layer_id")
        top_name = top_name_by_gid.get(int(gid), "") if gid is not None else ""
        layer_entries.append(
            LayerEntry(
                layer_id=int(entry["layer_id"]),
                name=str(entry.get("name", f"Layer {entry['layer_id']}")),
                group_id=int(gid) if gid is not None else None,
                top_group_name=top_name,
                left=int(entry.get("left", 0)),
                top=int(entry.get("top", 0)),
                width=int(entry.get("width", 0)),
                height=int(entry.get("height", 0)),
                opacity=int(entry.get("opacity", 255)),
                visible=bool(entry.get("visible", 0)),
                draw_index=draw_index,
            )
        )

    layer_map = {layer.layer_id: layer for layer in layer_entries}
    body_layers: list[LayerEntry] = []
    expression_layers: list[LayerEntry] = []
    blush_layers: list[LayerEntry] = []
    special_layers: list[LayerEntry] = []
    assigned: set[int] = set()

    sorted_groups = sorted(top_groups, key=lambda g: path_order.get(f"{g.get('name','')}/", 10000))
    for group in sorted_groups:
        gid = int(group["layer_id"])
        name = str(group.get("name", ""))
        children = sorted(
            [layer_map[int(ch["layer_id"])] for ch in images_by_gid.get(gid, []) if int(ch["layer_id"]) in layer_map],
            key=lambda layer: layer.draw_index,
        )
        if not children:
            continue
        if _is_expression_group(name, children, canvas_w, canvas_h):
            for child in children:
                if child.name.startswith("頬"):
                    blush_layers.append(child)
                else:
                    expression_layers.append(child)
                assigned.add(child.layer_id)
        else:
            for child in children:
                body_layers.append(child)
                assigned.add(child.layer_id)

    for layer in layer_entries:
        if layer.layer_id in assigned:
            continue
        if _is_special_layer(layer):
            special_layers.append(layer)
            assigned.add(layer.layer_id)

    fixed_layers = [layer for layer in layer_entries if layer.layer_id not in assigned and layer.visible]
    if not body_layers:
        visible_layers = [layer for layer in layer_entries if layer.visible]
        if visible_layers:
            body_layers = [max(visible_layers, key=lambda x: x.area)]

    body_layers = sorted(body_layers, key=lambda x: x.draw_index)
    expression_layers = sorted(expression_layers, key=lambda x: x.draw_index)
    blush_layers = sorted(blush_layers, key=lambda x: x.draw_index)
    special_layers = sorted(special_layers, key=lambda x: x.draw_index)

    visible_body_layers = [layer for layer in body_layers if layer.visible]
    if visible_body_layers:
        default_body_id = max(visible_body_layers, key=lambda x: x.area).layer_id
    else:
        default_body_id = body_layers[0].layer_id if body_layers else None
    default_expr_id = next((layer.layer_id for layer in expression_layers if layer.visible), None)
    default_blush_id = next((layer.layer_id for layer in blush_layers if layer.visible), None)
    default_special_id = next((layer.layer_id for layer in special_layers if layer.visible), None)

    pose_name = ""
    pose_names = {layer.name for layer in body_layers}
    if len(pose_names) == 1:
        pose_name = next(iter(pose_names))

    return Scene(
        json_path=json_path,
        sinfo_path=sinfo_path,
        canvas_width=canvas_w,
        canvas_height=canvas_h,
        layers=layer_entries,
        body_layers=body_layers,
        expression_layers=expression_layers,
        blush_layers=blush_layers,
        special_layers=special_layers,
        fixed_layers=fixed_layers,
        default_body_id=default_body_id,
        default_expression_id=default_expr_id,
        default_blush_id=default_blush_id,
        default_special_id=default_special_id,
        pose_name=pose_name,
        sinfo_order=sinfo_lines,
    )


__all__ = [
    "DEFAULT_BLUSH_LABEL",
    "DEFAULT_EXPRESSION_LABEL",
    "DEFAULT_SPECIAL_LABEL",
    "Project",
    "ProjectError",
    "Scene",
    "CompositionSelection",
    "collect_json_or_pbd_paths",
]
