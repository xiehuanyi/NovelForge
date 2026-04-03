#!/usr/bin/env python3
"""NovelForge — Multi-Agent Collaborative Novel Writing System.

Usage:
    python main.py                  # Interactive TUI mode (default)
    python main.py --headless       # Headless mode (API/script use)
    python main.py --resume <name>  # Resume an existing project

Environment:
    DASHSCOPE_API_KEY   API key for qwen3.5-flash (optional, has default)
"""

import argparse
import os
import sys

def main():
    parser = argparse.ArgumentParser(
        description="NovelForge: Multi-Agent Collaborative Novel Writing",
    )
    parser.add_argument(
        "--headless", action="store_true",
        help="Run in headless mode (no TUI, for scripting/API use)",
    )
    parser.add_argument(
        "--resume", type=str, default="",
        help="Resume an existing project by name",
    )
    parser.add_argument(
        "--api-key", type=str, default="",
        help="DashScope API key (overrides env var)",
    )
    args = parser.parse_args()

    # Set API key if provided via CLI
    if args.api_key:
        os.environ["DASHSCOPE_API_KEY"] = args.api_key

    if args.headless:
        _run_headless(args.resume)
    else:
        _run_tui()


def _run_tui():
    """Launch the interactive terminal UI."""
    try:
        from novelforge.tui.app import NovelForgeTUI
        app = NovelForgeTUI()
        app.run()
    except KeyboardInterrupt:
        print("\n再见！")
        sys.exit(0)


def _run_headless(resume_project: str = ""):
    """Run in headless mode — useful for batch/scripting."""
    from novelforge.core.config import Config, LLMConfig, NovelSpec
    from novelforge.agents.orchestrator import Orchestrator
    from pathlib import Path

    if resume_project:
        config_path = Path("output") / resume_project / "config.json"
        if not config_path.exists():
            print(f"Error: Project '{resume_project}' not found.")
            sys.exit(1)
        config = Config.load(config_path)
    else:
        # Minimal headless config — typically you'd load from a file
        config = Config(
            llm=LLMConfig(
                api_key=os.getenv("DASHSCOPE_API_KEY", "sk-34c66ad47f9d4db3b9b2525116194d53"),
            ),
            novel=NovelSpec(idea="请在配置文件中设置创意"),
        )

    def on_progress(agent: str, message: str, fraction: float):
        pct = f"{fraction * 100:.0f}%" if fraction > 0 else ""
        print(f"[{agent}] {message} {pct}")

    orch = Orchestrator(config, on_progress=on_progress)
    result = orch.run()

    print("\n=== 生成完毕 ===")
    print(f"章节数: {result['chapters_written']}")
    print(f"总字数: {result['total_words']:,}")
    print(f"耗时: {result['elapsed_seconds']:.0f}秒")
    print(f"Token: {result['total_tokens']:,}")


if __name__ == "__main__":
    main()
