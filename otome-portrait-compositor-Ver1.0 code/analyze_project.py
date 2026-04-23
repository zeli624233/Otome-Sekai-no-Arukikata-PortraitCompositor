
from __future__ import annotations

import argparse
from pathlib import Path

from otome_tlg_compositor.core import Project


def main() -> None:
    parser = argparse.ArgumentParser(description="分析 Otome JSON/SINFO/PNG 项目")
    parser.add_argument("--json-dir", required=True, help="JSON 目录")
    parser.add_argument("--sinfo-dir", default="", help="SINFO 目录，可留空")
    parser.add_argument("--png-dir", default="", help="PNG 目录，可留空")
    parser.add_argument("--out", default="", help="可选：输出 Markdown 报告")
    args = parser.parse_args()

    project = Project.from_directories(
        json_dir=args.json_dir,
        sinfo_dir=args.sinfo_dir or None,
        png_dir=args.png_dir or None,
    )
    report = project.analysis_report()
    if args.out:
        Path(args.out).write_text(report, encoding="utf-8")
        print(f"已写出: {Path(args.out).resolve()}")
    else:
        print(report)


if __name__ == "__main__":
    main()
