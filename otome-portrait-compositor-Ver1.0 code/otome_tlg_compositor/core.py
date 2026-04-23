from __future__ import annotations

import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Callable, Optional

from PIL import Image, ImageDraw


DEFAULT_EXPRESSION_LABEL = "无表情"
DEFAULT_BLUSH_LABEL = "无红晕"


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
    fixed_layers: list[LayerEntry] = field(default_factory=list)
    default_body_id: Optional[int] = None
    default_expression_id: Optional[int] = None
    default_blush_id: Optional[int] = None
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


class ImageProvider:
    def __init__(self, root_dirs: list[Path], png_dir: Optional[str | Path] = None) -> None:
        self.root_dirs = [Path(p).resolve() for p in root_dirs if p]
        self.png_dir = Path(png_dir).expanduser().resolve() if png_dir else None
        self._png_index: dict[str, Path] = {}

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
            self._index_png_dir(directory)

    def _index_png_dir(self, directory: Path) -> None:
        files: list[Path] = []
        try:
            with os.scandir(directory) as it:
                for entry in it:
                    if entry.is_file() and entry.name.lower().endswith(".png"):
                        files.append(Path(entry.path))
        except FileNotFoundError:
            return
        for path in sorted(files, key=lambda p: natural_sort_key(p.name)):
            decoded_name = decode_hashu(path.name)
            decoded_stem = decode_hashu(path.stem)
            for key in {
                path.name.lower(),
                path.stem.lower(),
                decoded_name.lower(),
                decoded_stem.lower(),
            }:
                self._png_index[key] = path.resolve()

    def _png_candidates(self, scene: Scene, layer: LayerEntry) -> list[str]:
        return [
            f"{scene.stem}_{layer.layer_id}.png",
            f"{scene.decoded_stem}_{layer.layer_id}.png",
            f"{layer.layer_id}.png",
            f"{layer.layer_id}",
        ]

    def resolve(self, scene: Scene, layer: LayerEntry) -> ResolvedImage:
        for key in self._png_candidates(scene, layer):
            hit = self._png_index.get(key.lower())
            if hit and hit.exists():
                return ResolvedImage(layer=layer, path=hit, status="PNG 命中")
        return ResolvedImage(layer=layer, path=None, status="未找到对应 PNG")

    @staticmethod
    @lru_cache(maxsize=192)
    def _open_rgba_cached(path_str: str, opacity: int) -> Image.Image:
        with Image.open(path_str) as im:
            out = im.convert("RGBA")
        if opacity < 255:
            alpha = out.getchannel("A").point(lambda p: int(p * opacity / 255.0))
            out.putalpha(alpha)
        return out

    @classmethod
    def open_rgba(cls, path: Path, opacity: int) -> Image.Image:
        return cls._open_rgba_cached(str(path.resolve()), int(opacity)).copy()


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
    ) -> "Project":
        json_path = Path(json_dir).expanduser().resolve()
        if not json_path.exists() or not json_path.is_dir():
            raise ProjectError("请选择有效的 JSON 目录。")

        sinfo_path = Path(sinfo_dir).expanduser().resolve() if sinfo_dir else None
        if sinfo_path and not sinfo_path.exists():
            raise ProjectError("SINFO 目录不存在。")
        if sinfo_path and not sinfo_path.is_dir():
            raise ProjectError("请选择有效的 SINFO 目录。")

        png_path = Path(png_dir).expanduser().resolve() if png_dir else None
        if png_path and (not png_path.exists() or not png_path.is_dir()):
            raise ProjectError("请选择有效的 PNG 目录。")

        json_paths = sorted(json_path.glob("*.json"), key=lambda p: natural_sort_key(p.name))
        if not json_paths:
            raise ProjectError("JSON 目录中没有找到 .json 文件。")

        sinfo_map: dict[str, Path] = {}
        if sinfo_path:
            sinfo_map = {p.stem: p for p in sinfo_path.glob("*.sinfo")}

        max_workers = min(8, max(2, (os.cpu_count() or 4)))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            scenes = list(executor.map(lambda p: parse_scene(p, sinfo_map.get(p.stem)), json_paths))
        scenes.sort(key=lambda s: natural_sort_key(s.json_path.name))

        provider = ImageProvider(root_dirs=[json_path, *( [sinfo_path] if sinfo_path else [] )], png_dir=png_path)
        return cls(scenes=scenes, image_provider=provider, json_dir=json_path, sinfo_dir=sinfo_path, png_dir=png_path)

    def close(self) -> None:
        return None

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

        return CompositionSelection(scene_index=idx, body_id=body_id, expression_id=expr_id, blush_id=blush_id)

    def _selected_layers(self, selection: CompositionSelection) -> list[LayerEntry]:
        scene = self.scenes[selection.scene_index]
        fixed_layers = sorted(scene.fixed_layers, key=lambda x: x.draw_index)
        body_layers: list[LayerEntry] = []
        expression_layers: list[LayerEntry] = []
        blush_layers: list[LayerEntry] = []

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

        return (
            fixed_layers
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
        jobs: list[tuple[CompositionSelection, Path]] = []
        for body_layer in scene.body_layers:
            for expr_name in expr_names:
                for blush_name in blush_names:
                    sel = self.make_selection(
                        scene_stem=scene.stem,
                        body_label=body_layer.label,
                        expression_name=expr_name,
                        blush_name=blush_name,
                    )
                    out_name = build_output_name(scene, body_layer.label, expr_name, blush_name)
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
        lines.append(f"共发现 {len(self.scenes)} 个姿势(JSON/SINFO 组合)。")
        lines.append(f"JSON 目录: {self.json_dir}")
        lines.append(f"SINFO 目录: {self.sinfo_dir if self.sinfo_dir else '无'}")
        lines.append(f"PNG 目录: {self.png_dir if self.png_dir else '无'}")
        lines.append("")
        for idx, scene in enumerate(self.scenes, start=1):
            lines.append(f"[姿势 {idx}] {scene.pose_label}")
            lines.append(f"- JSON: {scene.json_path.name}")
            lines.append(f"- SINFO: {scene.sinfo_path.name if scene.sinfo_path else '无'}")
            lines.append(f"- 画布: {scene.canvas_width} x {scene.canvas_height}")
            lines.append(f"- 身体服装选项: {', '.join(layer.label for layer in scene.body_layers)}")
            lines.append(f"- 表情选项: {', '.join(layer.name for layer in scene.expression_layers) if scene.expression_layers else '无'}")
            lines.append(f"- 红晕选项: {', '.join(layer.name for layer in scene.blush_layers) if scene.blush_layers else '无'}")
            lines.append("")
        lines.append("结论")
        lines.append("- 姿势及其图片分辨率选项由已加载的 JSON/SINFO 文件集合决定，每个 JSON 对应一个姿势。")
        lines.append("- 非“表情”顶层组里的图片层作为身体服装候选。")
        lines.append("- “表情”组中名称以“頬”开头的是红晕，其余归为表情。")
        lines.append("- 最终输出 = 1 张身体底图 + 0/1 张表情 + 0/1 张红晕，按 JSON 中 left/top 合成。")
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


def build_output_name(scene: Scene, body_label: str, expression_name: str, blush_name: str) -> str:
    return sanitize_filename(f"{scene.decoded_stem}__{body_label}__{expression_name}__{blush_name}.png")


EXPRESSION_GROUP_NAMES = {"表情", "差分", "顔", "颜", "フェイス", "face", "顔差分", "表情差分", "差分表情"}
EXPRESSION_NAME_HINTS = {"微笑", "にっこり", "薄ら笑い", "真剣", "怒り", "寂しい", "呆れ", "驚き", "すまし", "恍惚", "笑", "泣", "照れ", "赤面", "困", "怒", "悲", "喜"}


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

    fixed_layers = [layer for layer in layer_entries if layer.layer_id not in assigned and layer.visible]
    if not body_layers:
        visible_layers = [layer for layer in layer_entries if layer.visible]
        if visible_layers:
            body_layers = [max(visible_layers, key=lambda x: x.area)]

    body_layers = sorted(body_layers, key=lambda x: x.draw_index)
    expression_layers = sorted(expression_layers, key=lambda x: x.draw_index)
    blush_layers = sorted(blush_layers, key=lambda x: x.draw_index)

    visible_body_layers = [layer for layer in body_layers if layer.visible]
    if visible_body_layers:
        default_body_id = max(visible_body_layers, key=lambda x: x.area).layer_id
    else:
        default_body_id = body_layers[0].layer_id if body_layers else None
    default_expr_id = next((layer.layer_id for layer in expression_layers if layer.visible), None)
    default_blush_id = next((layer.layer_id for layer in blush_layers if layer.visible), None)

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
        fixed_layers=fixed_layers,
        default_body_id=default_body_id,
        default_expression_id=default_expr_id,
        default_blush_id=default_blush_id,
        pose_name=pose_name,
        sinfo_order=sinfo_lines,
    )


__all__ = [
    "DEFAULT_BLUSH_LABEL",
    "DEFAULT_EXPRESSION_LABEL",
    "Project",
    "ProjectError",
    "Scene",
    "CompositionSelection",
]
