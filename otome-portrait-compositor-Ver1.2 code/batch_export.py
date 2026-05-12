
from __future__ import annotations

import argparse
from pathlib import Path

from otome_tlg_compositor.core import DEFAULT_BLUSH_LABEL, DEFAULT_EXPRESSION_LABEL, DEFAULT_SPECIAL_LABEL, Project, detect_cpu_threads


def main() -> None:
    parser = argparse.ArgumentParser(description="批量导出 Otome JSON/PBD/SINFO/PNG/TLG 合成结果")
    parser.add_argument("--json-dir", required=True, help="JSON/PBD 目录，或单个 .json/.pbd 文件")
    parser.add_argument("--sinfo-dir", default="", help="SINFO 目录，可留空")
    parser.add_argument("--png-dir", required=True, help="PNG/TLG 图层目录")
    parser.add_argument("--pose", default="", help="姿势名；不填则默认第一个，或在 --all-combos 时导出全部姿势")
    parser.add_argument("--body", default="", help="身体/服装选项名")
    parser.add_argument("--expression", default="", help=f'表情名；填 "{DEFAULT_EXPRESSION_LABEL}" 表示不叠加表情')
    parser.add_argument("--blush", default="", help=f'红晕名；填 "{DEFAULT_BLUSH_LABEL}" 表示不叠加红晕')
    parser.add_argument("--special", default="", help=f'特殊效果名；填 "{DEFAULT_SPECIAL_LABEL}" 表示不叠加特殊效果')
    parser.add_argument("--out", default="", help="导出单张 PNG 的输出路径")
    parser.add_argument("--out-dir", default="", help="批量导出目录")
    parser.add_argument("--all-combos", action="store_true", help="导出全部组合；未指定 --pose 时会导出全部姿势")
    parser.add_argument("--include-no-expression", action="store_true", help='批量导出时包含“无表情”组合')
    parser.add_argument("--workers", type=int, default=detect_cpu_threads(), help="导出时使用的CPU线程数，默认使用本机全部逻辑线程")
    args = parser.parse_args()

    def pbd_progress(done: int, total_count: int) -> None:
        if total_count > 0:
            print(f"正在解析 PBD 为 JSON: {done}/{total_count}", end="\r", flush=True)

    project = Project.from_directories(
        json_dir=args.json_dir,
        sinfo_dir=args.sinfo_dir or None,
        png_dir=args.png_dir,
        pbd_workers=args.workers,
        pbd_progress_callback=pbd_progress,
    )
    print("", end="\n", flush=True)

    cached, total = project.tlg_cache_status()
    if total > 0 and cached < total:
        print(f"正在生成 TLG 磁盘缓存：已命中 {cached}/{total}，使用 {args.workers} 个 CPU 并行任务……")

        def cache_progress(done: int, total_count: int) -> None:
            print(f"  缓存进度: {done}/{total_count}", end="\r", flush=True)

        cached_count, converted_count, total_count = project.preload_tlg_images(cache_progress, max_workers=args.workers)
        print()
        print(f"TLG 磁盘缓存完成：命中 {cached_count}，新生成 {converted_count}，共 {total_count}。")

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
        special_name=args.special if args.special != "" else None,
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
