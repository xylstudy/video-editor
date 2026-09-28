import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from graph.builder import build_graph, create_initial_state
from config import settings
from config.output_manager import OutputManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)


async def run_pipeline(
    sample_videos: list[str],
    user_materials: list[dict],
    target_topic: str,
    target_info: Optional[dict] = None,
    user_preferences: Optional[dict] = None,
    max_iterations: int = 3,
    run_id: str = "",
):
    if not run_id:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_topic = "".join(c if c.isalnum() else "_" for c in target_topic)[:20]
        run_id = f"{timestamp}_{safe_topic}"

    out = OutputManager(run_id=run_id)
    out.save_run_info(
        target_topic=target_topic,
        sample_videos=sample_videos,
        user_materials_count=len(user_materials),
        max_iterations=max_iterations,
    )

    initial_state = create_initial_state(
        sample_videos=sample_videos,
        user_materials=user_materials,
        target_topic=target_topic,
        target_info=target_info,
        user_preferences=user_preferences,
        max_iterations=max_iterations,
        run_id=run_id,
    )

    logger.info("=" * 60)
    logger.info("爆款Vlog结构迁移引擎 — Multi-Agent")
    logger.info(f"主题: {target_topic}")
    logger.info(f"参考视频: {len(sample_videos)} 条")
    logger.info(f"输出目录: {out.run_dir}")
    logger.info("=" * 60)

    try:
        app = build_graph()
        final_state = await app.ainvoke(initial_state)
    except Exception as exc:
        out.save_pipeline_summary({
            "status": "failed",
            "target_topic": target_topic,
            "phase": "execution_failed",
            "is_complete": False,
            "errors": [str(exc)],
        })
        try:
            from evaluation.run_evaluator import evaluate_run
            out.save_json("evaluation", "report.json", evaluate_run(out.run_dir))
        except Exception:
            logger.exception("Pipeline 失败评测报告生成失败")
        raise

    result = {
        "status": "completed",
        "target_topic": target_topic,
        "phase": final_state.get("phase", "unknown"),
        "iteration": final_state.get("iteration", 0),
        "is_complete": final_state.get("is_complete", False),
        "rendered_video_path": final_state.get("rendered_video_path", ""),
        "review_result": final_state.get("review_result", {}),
        "skill_trace": final_state.get("skill_trace", {}),
        "error_count": len(final_state.get("errors", [])),
        "errors": final_state.get("errors", []),
        "log_count": len(final_state.get("logs", [])),
        "logs": final_state.get("logs", []),
        "run_id": run_id,
        "output_dir": str(out.run_dir),
    }

    out.save_pipeline_summary(final_state)

    # The report is deterministic and reads only this run's saved artifacts;
    # failures in evaluation must not hide a completed generation result.
    try:
        from evaluation.run_evaluator import evaluate_run
        evaluation = evaluate_run(out.run_dir)
        out.save_json("evaluation", "report.json", evaluation)
        result["evaluation"] = evaluation
    except Exception as exc:
        logger.warning("运行评测报告生成失败: %s", exc)

    logger.info(f"Pipeline 结果已保存至: {out.run_dir}")
    return result


def main():
    parser = argparse.ArgumentParser(
        description="爆款Vlog结构迁移引擎 — 分析爆款Vlog的结构，基于用户素材生成迁移方案并渲染视频"
    )
    parser.add_argument("--topic", required=True, help="目标视频主题")
    parser.add_argument("--samples", nargs="+", default=[], help="参考视频路径（爆款Vlog）")
    parser.add_argument("--materials", type=str, default=None, help="用户素材JSON文件路径（可选）")
    parser.add_argument("--output", type=str, default=None, help="输出结果文件路径")
    parser.add_argument("--max-iterations", type=int, default=3, help="最大迭代次数")

    args = parser.parse_args()

    if not args.samples:
        logger.warning("未指定参考视频路径，将跳过分析阶段")

    user_materials = []
    if args.materials:
        materials_path = Path(args.materials)
        if materials_path.exists():
            with open(materials_path, "r", encoding="utf-8") as f:
                user_materials = json.load(f)
            logger.info(f"加载了 {len(user_materials)} 个素材")

    result = asyncio.run(
        run_pipeline(
            sample_videos=args.samples,
            user_materials=user_materials,
            target_topic=args.topic,
            max_iterations=args.max_iterations,
        )
    )

    output = args.output or str(settings.OUTPUT_DIR / "result.json")
    with open(output, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    logger.info(f"结果已保存至: {output}")
    if result.get("rendered_video_path"):
        logger.info(f"视频已输出至: {result['rendered_video_path']}")

    print("\n" + "=" * 60)
    print(f"主题: {result['target_topic']}")
    print(f"状态: {result['status']}")
    print(f"最终阶段: {result['phase']}")
    print(f"迭代次数: {result['iteration']}")
    print(f"完成: {result['is_complete']}")
    print(f"错误数: {result['error_count']}")

    review = result.get("review_result", {})
    if review and isinstance(review, dict):
        print(f"审核总分: {review.get('total_score', 'N/A')}")
        print(f"审核通过: {review.get('pass', 'N/A')}")

    if result.get("rendered_video_path"):
        print(f"视频路径: {result['rendered_video_path']}")
    if result.get("output_dir"):
        print(f"输出目录: {result['output_dir']}")
    print("=" * 60)

    # 打印目录结构概览
    out_dir = result.get("output_dir", "")
    if out_dir:
        _print_run_tree(Path(out_dir))


def _print_run_tree(run_dir: Path):
    """打印 runs/ 目录下的文件树概览"""
    if not run_dir.exists():
        return
    print(f"\n[输出目录] 运行产物:")
    for p in sorted(run_dir.rglob("*")):
        if p.is_file() and p.parent.name not in ("frames", "generated_images", "__pycache__"):
            rel = p.relative_to(run_dir)
            size = p.stat().st_size
            size_str = f"{size/1024:.1f}KB" if size > 1024 else f"{size}B"
            print(f"  [FILE] {rel}  ({size_str})")
        elif p.is_dir() and p != run_dir:
            rel = p.relative_to(run_dir)
            count = len(list(p.iterdir()))
            if count > 0:
                print(f"  [DIR]  {rel}/  ({count} 文件)")


if __name__ == "__main__":
    main()
