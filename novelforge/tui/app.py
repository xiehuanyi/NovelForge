"""Rich-based Terminal UI for NovelForge.

Inspired by Claude Code's TUI design:
- Clean, focused interface
- Real-time streaming output
- Agent activity visualization with colors
- Progress tracking for long operations

Uses only the `rich` library — no curses, no textual, keeping it simple.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskID
from rich.prompt import Prompt, IntPrompt, Confirm
from rich.table import Table
from rich.text import Text
from rich.rule import Rule
from rich import box

from novelforge.core.config import Config, LLMConfig, NovelSpec, PipelineConfig
from novelforge.core.message import Message, MessageType
from novelforge.agents.orchestrator import Orchestrator
from novelforge.evaluation.consistency import ConsistencyChecker

# Agent colors for display
AGENT_COLORS = {
    "orchestrator": "bright_yellow",
    "worldbuilder": "bright_green",
    "character": "bright_cyan",
    "outliner": "bright_blue",
    "writer": "bright_red",
    "editor": "bright_magenta",
    "memory": "dim",
    "system": "white",
}

AGENT_ICONS = {
    "orchestrator": "[yellow]⚡[/]",
    "worldbuilder": "[green]🌍[/]",
    "character": "[cyan]👤[/]",
    "outliner": "[blue]📋[/]",
    "writer": "[red]✍️[/]",
    "editor": "[magenta]📝[/]",
    "memory": "[dim]🧠[/]",
}


class NovelForgeTUI:
    """Main TUI application."""

    def __init__(self):
        self.console = Console()
        self.config: Optional[Config] = None
        self.orchestrator: Optional[Orchestrator] = None

    def run(self) -> None:
        """Main entry point — show welcome and enter command loop."""
        self._show_banner()
        self._setup_project()
        self._command_loop()

    # -- Setup -----------------------------------------------------------------

    def _show_banner(self) -> None:
        banner = Text()
        banner.append("╔══════════════════════════════════════════╗\n", style="bright_blue")
        banner.append("║         ", style="bright_blue")
        banner.append("NovelForge", style="bold bright_white")
        banner.append(" v0.2.0             ║\n", style="bright_blue")
        banner.append("║   Multi-Agent Novel Writing System      ║\n", style="bright_blue")
        banner.append("╚══════════════════════════════════════════╝", style="bright_blue")
        self.console.print(banner)
        self.console.print()

    def _setup_project(self) -> None:
        """Interactive project setup."""
        self.console.print("[bold]项目配置[/bold]", style="bright_yellow")
        self.console.print(Rule(style="dim"))

        # Check for existing projects
        output_dir = Path("output")
        existing = []
        if output_dir.exists():
            existing = [d.name for d in output_dir.iterdir()
                        if d.is_dir() and (d / "config.json").exists()]

        if existing:
            self.console.print(f"发现 {len(existing)} 个已有项目:")
            for i, name in enumerate(existing, 1):
                self.console.print(f"  {i}. {name}")
            self.console.print(f"  {len(existing) + 1}. 创建新项目")
            choice = IntPrompt.ask(
                "选择",
                default=len(existing) + 1,
                show_default=True,
            )
            if 1 <= choice <= len(existing):
                project_name = existing[choice - 1]
                self.config = Config.load(output_dir / project_name / "config.json")
                self.console.print(f"[green]已加载项目: {project_name}[/green]")
                self._init_orchestrator()
                return

        # New project setup
        self.console.print("\n[bold]创建新项目[/bold]")

        idea = Prompt.ask("[bright_cyan]你的创作灵感[/bright_cyan]")
        title = Prompt.ask("书名", default="")
        genre = Prompt.ask("题材 (如: 玄幻/科幻/推理/都市)", default="")
        chapters = IntPrompt.ask("总章数", default=10)
        chapter_words = IntPrompt.ask("每章字数", default=3000)

        project_name = title or f"novel_{int(time.time())}"
        # Sanitize project name
        project_name = "".join(c for c in project_name if c.isalnum() or c in "-_ ").strip()
        project_name = project_name.replace(" ", "_") or "novel"

        self.config = Config(
            llm=LLMConfig(
                model="qwen3.5-flash",
                api_key="sk-34c66ad47f9d4db3b9b2525116194d53",
                base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                max_tokens=16384,
                context_window=131072,
                enable_thinking=True,
            ),
            novel=NovelSpec(
                title=title,
                idea=idea,
                genre=genre,
                chapters=chapters,
                chapter_words=chapter_words,
            ),
            pipeline=PipelineConfig(),
            project_name=project_name,
        )
        self.config.save()
        self.console.print(f"\n[green]项目已创建: {project_name}[/green]")
        self._init_orchestrator()

    def _init_orchestrator(self) -> None:
        """Initialize the orchestrator with progress callback."""
        self.orchestrator = Orchestrator(
            self.config,
            on_progress=self._on_progress,
        )
        # Subscribe to message bus for TUI display
        self.orchestrator.bus.subscribe_all(self._on_message)

    # -- Command Loop ----------------------------------------------------------

    def _command_loop(self) -> None:
        """Main interactive command loop."""
        self.console.print()
        self._show_help()

        while True:
            try:
                cmd = Prompt.ask("\n[bold bright_blue]NovelForge>[/bold bright_blue]").strip()
            except (EOFError, KeyboardInterrupt):
                self.console.print("\n[dim]再见！[/dim]")
                break

            if not cmd:
                continue

            parts = cmd.split(maxsplit=1)
            command = parts[0].lower()
            args = parts[1] if len(parts) > 1 else ""

            try:
                if command in ("quit", "exit", "q"):
                    self.console.print("[dim]再见！[/dim]")
                    break
                elif command in ("help", "h", "?"):
                    self._show_help()
                elif command in ("run", "start", "开始"):
                    self._cmd_run()
                elif command in ("status", "stats", "状态"):
                    self._cmd_status()
                elif command in ("chapter", "ch", "章节"):
                    self._cmd_chapter(args)
                elif command in ("bible", "世界观"):
                    self._cmd_show_bible()
                elif command in ("characters", "chars", "角色"):
                    self._cmd_show_characters()
                elif command in ("outline", "大纲"):
                    self._cmd_show_outline()
                elif command in ("review", "审查"):
                    self._cmd_review(args)
                elif command in ("consistency", "一致性"):
                    self._cmd_consistency(args)
                elif command in ("export", "导出"):
                    self._cmd_export()
                elif command in ("config", "配置"):
                    self._cmd_config()
                elif command in ("memory", "记忆"):
                    self._cmd_memory()
                else:
                    self.console.print(f"[yellow]未知命令: {command}[/yellow] (输入 help 查看帮助)")
            except KeyboardInterrupt:
                self.console.print("\n[yellow]已中断[/yellow]")
            except Exception as e:
                self.console.print(f"[red]错误: {e}[/red]")

    def _show_help(self) -> None:
        table = Table(title="可用命令", box=box.SIMPLE, show_header=True)
        table.add_column("命令", style="bright_cyan", width=20)
        table.add_column("说明", style="white")

        commands = [
            ("run / 开始", "运行完整的小说生成流程"),
            ("status / 状态", "查看当前项目状态和统计"),
            ("chapter <N> / 章节 <N>", "查看或重新生成指定章节"),
            ("bible / 世界观", "查看 Series Bible"),
            ("characters / 角色", "查看角色档案"),
            ("outline / 大纲", "查看章节大纲"),
            ("review <N> / 审查 <N>", "查看指定章节的编辑评审"),
            ("consistency <N> / 一致性 <N>", "对指定章节运行一致性检查"),
            ("memory / 记忆", "查看当前记忆状态"),
            ("export / 导出", "导出完整小说为单文件"),
            ("config / 配置", "查看/修改配置"),
            ("help / h", "显示此帮助"),
            ("quit / q", "退出"),
        ]
        for cmd, desc in commands:
            table.add_row(cmd, desc)

        self.console.print(table)

    # -- Commands Implementation -----------------------------------------------

    def _cmd_run(self) -> None:
        """Run the full pipeline."""
        stats = self.orchestrator.get_stats()

        if stats["chapters_done"]:
            remaining = stats["chapters_total"] - len(stats["chapters_done"])
            if remaining <= 0:
                self.console.print("[green]所有章节已生成完毕！[/green]")
                if not Confirm.ask("要重新生成吗？"):
                    return
            else:
                self.console.print(f"已完成 {len(stats['chapters_done'])}/{stats['chapters_total']} 章")
                if not Confirm.ask("继续生成剩余章节？"):
                    return

        self.console.print()
        self.console.print(Rule("[bold]开始生成[/bold]", style="bright_green"))

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            console=self.console,
        ) as progress:
            self._progress_bar = progress
            self._progress_task = progress.add_task("生成中...", total=100)

            result = self.orchestrator.run()

        self.console.print()
        self.console.print(Rule("[bold]生成完毕[/bold]", style="bright_green"))

        # Show summary
        summary = Table(box=box.ROUNDED, show_header=False)
        summary.add_column("指标", style="bright_cyan")
        summary.add_column("值", style="white")
        summary.add_row("章节数", str(result["chapters_written"]))
        summary.add_row("总字数", f"{result['total_words']:,}")
        summary.add_row("耗时", f"{result['elapsed_seconds']:.0f}秒")
        summary.add_row("Token用量", f"{result['total_tokens']:,}")
        self.console.print(summary)

    def _cmd_status(self) -> None:
        stats = self.orchestrator.get_stats()
        table = Table(title="项目状态", box=box.ROUNDED, show_header=False)
        table.add_column("项目", style="bright_cyan")
        table.add_column("状态", style="white")

        table.add_row("书名", self.config.novel.title or "待定")
        table.add_row("Series Bible", "[green]✓[/green]" if stats["has_bible"] else "[red]✗[/red]")
        table.add_row("角色档案", "[green]✓[/green]" if stats["has_characters"] else "[red]✗[/red]")
        table.add_row("章节大纲", "[green]✓[/green]" if stats["has_outline"] else "[red]✗[/red]")

        done = len(stats["chapters_done"])
        total = stats["chapters_total"]
        ch_display = f"{done}/{total}"
        if done == total:
            ch_display = f"[green]{ch_display} ✓[/green]"
        elif done > 0:
            ch_display = f"[yellow]{ch_display}[/yellow]"
        table.add_row("章节进度", ch_display)
        table.add_row("总字数", f"{stats['total_words']:,}")
        table.add_row("Token用量", f"{stats['total_tokens']:,}")

        self.console.print(table)

    def _cmd_chapter(self, args: str) -> None:
        if not args:
            # List all chapters
            chapters = self.orchestrator.chapters
            if not chapters:
                self.console.print("[yellow]尚未生成任何章节[/yellow]")
                return
            for num in sorted(chapters.keys()):
                text = chapters[num]
                preview = text[:80].replace("\n", " ")
                self.console.print(f"  [bright_cyan]CH{num:03d}[/bright_cyan] {preview}...")
            return

        try:
            ch_num = int(args)
        except ValueError:
            self.console.print("[red]请输入章节编号[/red]")
            return

        chapters = self.orchestrator.chapters
        if ch_num in chapters:
            self.console.print(Panel(
                chapters[ch_num][:3000],
                title=f"第{ch_num}章",
                border_style="bright_cyan",
            ))
            if len(chapters[ch_num]) > 3000:
                self.console.print("[dim]（已截断显示，完整内容请查看文件）[/dim]")
        else:
            self.console.print(f"[yellow]第{ch_num}章尚未生成[/yellow]")
            if Confirm.ask("要现在生成吗？"):
                self.orchestrator.run_chapter(ch_num)

    def _cmd_show_bible(self) -> None:
        bible = self.orchestrator.world_bible
        if not bible:
            self.console.print("[yellow]Series Bible 尚未生成[/yellow]")
            return
        self.console.print(Panel(
            Markdown(bible),
            title="Series Bible",
            border_style="bright_green",
        ))

    def _cmd_show_characters(self) -> None:
        chars = self.orchestrator.characters
        if not chars:
            self.console.print("[yellow]角色档案尚未生成[/yellow]")
            return
        self.console.print(Panel(
            Markdown(chars),
            title="角色档案",
            border_style="bright_cyan",
        ))

    def _cmd_show_outline(self) -> None:
        outline = self.orchestrator.outline
        if not outline:
            self.console.print("[yellow]大纲尚未生成[/yellow]")
            return
        # Pretty-print JSONL outline
        for line in outline.strip().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = __import__("json").loads(line)
                ch = obj.get("chapter", "?")
                title = obj.get("title", "")
                summary = obj.get("summary", "")
                phase = obj.get("phase", "")
                self.console.print(
                    f"  [bright_cyan]CH{ch:03d}[/bright_cyan] "
                    f"[bold]{title}[/bold] "
                    f"[dim]({phase})[/dim] "
                    f"{summary}"
                )
            except Exception:
                self.console.print(f"  {line[:100]}")

    def _cmd_review(self, args: str) -> None:
        if not args:
            reviews = self.orchestrator.reviews
            if not reviews:
                self.console.print("[yellow]尚无评审记录[/yellow]")
                return
            for ch_num, review in sorted(reviews.items()):
                score = review.get("total_score", "?")
                verdict = review.get("verdict", "?")
                color = "green" if verdict == "pass" else "yellow"
                self.console.print(
                    f"  [bright_cyan]CH{ch_num:03d}[/bright_cyan] "
                    f"[{color}]{score}分 ({verdict})[/{color}]"
                )
            return

        try:
            ch_num = int(args)
        except ValueError:
            self.console.print("[red]请输入章节编号[/red]")
            return

        reviews = self.orchestrator.reviews
        if ch_num not in reviews:
            self.console.print(f"[yellow]第{ch_num}章无评审记录[/yellow]")
            return

        review = reviews[ch_num]
        self.console.print(Panel(
            __import__("json").dumps(review, ensure_ascii=False, indent=2),
            title=f"第{ch_num}章 评审报告",
            border_style="bright_magenta",
        ))

    def _cmd_consistency(self, args: str) -> None:
        """Run consistency check on a chapter or globally."""
        checker = ConsistencyChecker(
            self.orchestrator.llm,
            self.orchestrator.memory,
        )

        if not args or args.lower() in ("all", "全局"):
            self.console.print("[bold]运行全局一致性检查...[/bold]")
            report = checker.check_global(
                self.orchestrator.chapters,
                self.orchestrator.characters,
                self.orchestrator.world_bible,
            )
        else:
            try:
                ch_num = int(args)
            except ValueError:
                self.console.print("[red]请输入章节编号或 'all'[/red]")
                return
            chapters = self.orchestrator.chapters
            if ch_num not in chapters:
                self.console.print(f"[yellow]第{ch_num}章尚未生成[/yellow]")
                return
            self.console.print(f"[bold]检查第{ch_num}章一致性...[/bold]")
            report = checker.check_chapter(
                ch_num,
                chapters[ch_num],
                self.orchestrator.characters,
                self.orchestrator.world_bible,
            )

        # Display report
        table = Table(title="一致性评估报告", box=box.ROUNDED)
        table.add_column("维度", style="bright_cyan")
        table.add_column("得分", justify="center")
        table.add_column("状态", justify="center")

        for name, score in [
            ("角色一致性", report.character_score),
            ("剧情一致性", report.plot_score),
            ("世界观一致性", report.world_score),
        ]:
            color = "green" if score >= 80 else "yellow" if score >= 60 else "red"
            status = "✓" if score >= 70 else "⚠"
            table.add_row(name, f"[{color}]{score:.0f}[/{color}]", status)

        table.add_row(
            "[bold]总分[/bold]",
            f"[bold]{report.overall_score:.0f}[/bold]",
            "[green]通过[/green]" if report.passed else "[red]需改进[/red]",
        )
        self.console.print(table)

        if report.issues:
            self.console.print("\n[bold yellow]发现的问题:[/bold yellow]")
            for issue in report.issues:
                self.console.print(f"  [yellow]•[/yellow] {issue}")

    def _cmd_export(self) -> None:
        """Export the complete novel as a single text file."""
        chapters = self.orchestrator.chapters
        if not chapters:
            self.console.print("[yellow]尚未生成任何章节[/yellow]")
            return

        title = self.config.novel.title or "未命名小说"
        lines = [f"《{title}》\n\n"]

        for ch_num in sorted(chapters.keys()):
            lines.append(chapters[ch_num])
            lines.append("\n\n")

        output_path = self.config.project_dir / f"{title}.txt"
        output_path.write_text("".join(lines), encoding="utf-8")

        total_chars = sum(len(ch) for ch in chapters.values())
        self.console.print(f"[green]已导出到: {output_path}[/green]")
        self.console.print(f"总字数: {total_chars:,}")

    def _cmd_config(self) -> None:
        """Show current configuration."""
        table = Table(title="当前配置", box=box.ROUNDED, show_header=False)
        table.add_column("项目", style="bright_cyan")
        table.add_column("值", style="white")

        table.add_row("模型", self.config.llm.model)
        table.add_row("上下文窗口", f"{self.config.llm.context_window:,}")
        table.add_row("最大输出", f"{self.config.llm.max_tokens:,}")
        table.add_row("启用思考", str(self.config.llm.enable_thinking))
        table.add_row("审查轮次", str(self.config.pipeline.max_review_rounds))
        table.add_row("自我反思", str(self.config.pipeline.enable_self_reflection))
        table.add_row("一致性检查", str(self.config.pipeline.enable_consistency_check))
        table.add_row("批次大小", str(self.config.pipeline.batch_size))

        self.console.print(table)

    def _cmd_memory(self) -> None:
        """Show memory status."""
        memory = self.orchestrator.memory

        self.console.print("[bold]工作记忆[/bold]")
        working = memory.working.get_all()
        if working:
            for entry in working[-10:]:
                self.console.print(f"  [dim]{entry.key}[/dim] {entry.content}")
        else:
            self.console.print("  [dim]（空）[/dim]")

        self.console.print("\n[bold]情节记忆[/bold]")
        episodic = memory.episodic.get_all()
        if episodic:
            for entry in episodic[-10:]:
                prefix = f"[CH{entry.chapter}] " if entry.chapter else ""
                self.console.print(f"  {prefix}{entry.content}")
        else:
            self.console.print("  [dim]（空）[/dim]")

        self.console.print("\n[bold]语义记忆[/bold]")
        semantic = memory.semantic.get_all()
        if semantic:
            for entry in semantic[-10:]:
                self.console.print(f"  [bright_cyan]{entry.key}[/bright_cyan]: {entry.content}")
        else:
            self.console.print("  [dim]（空）[/dim]")

    # -- Callbacks -------------------------------------------------------------

    def _on_progress(self, agent: str, message: str, fraction: float) -> None:
        """Called by orchestrator to report progress."""
        color = AGENT_COLORS.get(agent, "white")
        icon = AGENT_ICONS.get(agent, "")
        self.console.print(f"  {icon} [{color}]{message}[/{color}]")

        if hasattr(self, "_progress_bar") and hasattr(self, "_progress_task"):
            self._progress_bar.update(
                self._progress_task,
                completed=int(fraction * 100),
                description=message,
            )

    def _on_message(self, message: Message) -> None:
        """Called for every message on the bus (for logging/display)."""
        if message.msg_type == MessageType.STATUS:
            # Already handled by _on_progress
            pass
