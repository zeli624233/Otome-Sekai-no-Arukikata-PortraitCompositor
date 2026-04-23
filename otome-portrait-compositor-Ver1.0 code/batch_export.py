
from __future__ import annotations

import argparse
from pathlib import Path

from otome_tlg_compositor.core import DEFAULT_BLUSH_LABEL, DEFAULT_EXPRESSION_LABEL, Project


def main() -> None:
    parser = argparse.ArgumentParser(description="批量导出 Otome JSON/SINFO/PNG 合成结果")
    parser.add_argument("--json-dir", required=True, help="JSON 目录")
    parser.add_argument("--sinfo-dir", default="", help="SINFO 目录，可留空")
    parser.add_argument("--png-dir", required=True, help="PNG 目录")
    parser.add_argument("--pose", default="", help="姿势名；不填则默认第一个，或在 --all-combos 时导出全部姿势")
    parser.add_argument("--body", default="", help="身体/服装选项名")
    parser.add_argument("--expression", default="", help=f'表情名；填 "{DEFAULT_EXPRESSION_LABEL}" 表示不叠加表情')
    parser.add_argument("--blush", default="", help=f'红晕名；填 "{DEFAULT_BLUSH_LABEL}" 表示不叠加红晕')
    parser.add_argument("--out", default="", help="导出单张 PNG 的输出路径")
    parser.add_argument("--out-dir", default="", help="批量导出目录")
    parser.add_argument("--all-combos", action="store_true", help="导出全部组合；未指定 --pose 时会导出全部姿势")
    parser.add_argument("--include-no-expression", action="store_true", help='批量导出时包含“无表情”组合')
    parser.add_argument("--workers", type=int, default=2, choices=[1,2,4,6,8,12,16], help="导出时使用的CPU线程数，默认 2")
    args = parser.parse_args()

    project = Project.from_directories(
        json_dir=args.json_dir,
        sinfo_dir=args.sinfo_dir or None,
        png_dir=args.png_dir,
    )

    scene = project.find_scene(args.pose) if args.pose else project.scenes[0]
    if args.all_combos:
        if not args.out_dir:
            raise SystemExit("--all-combos 时必须提供 --out-dir")
        if args.pose:
            exported = project.export_scene_all_combinations(
                scene_stem=scene.stem,
                output_dir=args.out_dir,
                include_no_expression=args.include_no_expression,
                workers=args.workers,
            )
        else:
            exported = project.export_all_scenes_all_combinations(
                args.out_dir,
                include_no_expression=args.include_no_expression,
                workers=args.workers,
            )
        print(f"已导出 {len(exported)} 张 PNG 到: {Path(args.out_dir).resolve()}")
        return

    selection = project.make_selection(
        scene_stem=scene.stem,
        body_label=args.body or None,
        expression_name=args.expression if args.expression != "" else None,
        blush_name=args.blush if args.blush != "" else None,
    )
    out = args.out or f"{scene.stem}_export.png"
    warnings = project.export_current(out, selection)
    print(f"已导出: {Path(out).resolve()}")
    if warnings:
        print("\n警告：")
        for line in warnings:
            print(f"- {line}")


if __name__ == "__main__":
    main()
