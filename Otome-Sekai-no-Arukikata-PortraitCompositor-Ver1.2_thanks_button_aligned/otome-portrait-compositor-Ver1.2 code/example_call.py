
from pathlib import Path

from otome_tlg_compositor.core import Project

project = Project.from_directories(
    json_dir="./json",
    sinfo_dir="./sinfo",
    png_dir="./png_or_tlg",
)

scene = project.scenes[0]
selection = project.make_selection(
    scene_stem=scene.stem,
    body_label=None,
    expression_name=None,
    blush_name=None,
)

out_path = Path("./example_output.png")
warnings = project.export_current(out_path, selection)
print(f"导出完成: {out_path.resolve()}")
if warnings:
    print("警告：")
    for w in warnings:
        print("-", w)
