"""
断点续跑脚本：加载已完成的分析产物（video_structure + inventory），
直接从 planner 阶段继续 pipeline。
"""
import asyncio
import json
import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

# 指定上一个运行的输出目录
RESUME_RUN_DIR = Path(r"E:\py pbjects\video_claw\viral-structure-engine\data\runs\20260607_162312_北京旅行Vlog")

sys.path.insert(0, str(Path(__file__).resolve().parent))

from graph.builder import build_graph
from graph.state import ViralEngineState
from models.video_structure import VideoStructure, ShotInfo, ShotType, TransitionType, EffectEvent
from models.material import MaterialInventory, MaterialItem, MaterialType, MaterialQuality


def load_video_structure() -> VideoStructure:
    path = RESUME_RUN_DIR / "analyst" / "video_structure.json"
    with open(path, encoding="utf-8") as f:
        d = json.load(f)

    shots = []
    for sd in d.get("shots", []):
        # 从 JSON 字符串转换为 Enum
        st_str = sd.get("shot_type", "daily_moment")
        try:
            st = ShotType(st_str)
        except ValueError:
            st = ShotType.DAILY_MOMENT

        tr_str = sd.get("transition_in", "cut")
        try:
            tr = TransitionType(tr_str)
        except ValueError:
            tr = TransitionType.CUT

        shot = ShotInfo(
            index=sd.get("index", 0),
            start_time=sd.get("start_time", 0),
            end_time=sd.get("end_time", 0),
            duration=sd.get("duration", 0),
            shot_type=st,
            visual_description=sd.get("visual_description", ""),
            camera_movement=sd.get("camera_movement", ""),
            shot_size=sd.get("shot_size", ""),
            composition=sd.get("composition", ""),
            color_mood=sd.get("color_mood", ""),
            subtitle_text=sd.get("subtitle_text", ""),
            voiceover_text=sd.get("voiceover_text", ""),
            transition_in=tr,
            emotion=sd.get("emotion", ""),
            structure_purpose=sd.get("structure_purpose", ""),
            has_face=sd.get("has_face", False),
            bgm_sync=sd.get("bgm_sync", False),
            is_empty_shot=sd.get("is_empty_shot", False),
            motion_intensity=sd.get("motion_intensity", 0.0),
            color_stats=sd.get("color_stats", {}),
            audio_type=sd.get("audio_type", ""),
            effect_events=[
                EffectEvent.from_dict(event, default_id=f"shot_{sd.get('index', 0):03d}_effect_{idx:02d}")
                for idx, event in enumerate(sd.get("effect_events", []) or [])
                if isinstance(event, dict)
            ],
            match_cut_to_next=sd.get("match_cut_to_next", {}),
        )
        shots.append(shot)

    vs = VideoStructure(
        source_id=d.get("source_id", ""),
        source_path=d.get("source_path", ""),
        duration=d.get("duration", 0),
        resolution=tuple(d.get("resolution", [1080, 1920])),
        aspect_ratio=d.get("aspect_ratio", "9:16"),
        shots=shots,
        script_blocks=d.get("script_blocks", []),
        overall_summary=d.get("overall_summary", ""),
        structure_summary=d.get("structure_summary", ""),
        hook_summary=d.get("hook_summary", ""),
        key_techniques=d.get("key_techniques", []),
        raw_analysis=d.get("raw_analysis", ""),
        transcript=d.get("transcript", ""),
        full_transcript=d.get("full_transcript", ""),
        audio_analysis=d.get("audio_analysis", {}),
    )
    logger.info(f"Loaded VideoStructure: {vs.shot_count} shots, {vs.duration:.1f}s")
    return vs


def load_inventory() -> MaterialInventory:
    path = RESUME_RUN_DIR / "material" / "inventory.json"
    with open(path, encoding="utf-8") as f:
        d = json.load(f)

    items = []
    for md in d.get("items", []):
        mtype_str = md.get("type", "image")
        try:
            mtype = MaterialType(mtype_str)
        except ValueError:
            mtype = MaterialType.IMAGE

        quality_str = md.get("quality", "medium")
        try:
            quality = MaterialQuality(quality_str)
        except ValueError:
            quality = MaterialQuality.MEDIUM

        item = MaterialItem(
            id=md.get("id", ""),
            type=mtype,
            path=md.get("path", ""),
            description=md.get("description", ""),
            main_subject=md.get("main_subject", ""),
            tags=md.get("tags", []),
            quality=quality,
            quality_notes=md.get("quality_notes", ""),
            resolution=md.get("resolution", "medium"),
            composition=md.get("composition", "okay"),
            light=md.get("light", "sufficient"),
            duration=md.get("duration", 0.0),
            width=md.get("width", 0),
            height=md.get("height", 0),
            has_face=md.get("has_face", False),
            face_count=md.get("face_count", 0),
            emotion_label=md.get("emotion_label", ""),
            scene_type=md.get("scene_type", ""),
            vlog_value=md.get("vlog_value", "medium"),
            vlog_applicability=md.get("vlog_applicability", []),
            highlight_clips=md.get("highlight_clips", []),
            content_segments=md.get("content_segments", []),
            is_ai_generated=md.get("is_ai_generated", False),
        )
        items.append(item)

    gaps_data = d.get("gaps", [])
    from models.material import MaterialGap
    from models.video_structure import ShotType

    gaps = []
    for gd in gaps_data:
        gap = MaterialGap(
            slot_index=gd.get("slot_index", 0),
            required_type=ShotType(gd.get("required_type", "daily_moment")),
            purpose=gd.get("purpose", ""),
            needed_content=gd.get("needed_content", ""),
            priority=gd.get("priority", 3),
            is_filled=gd.get("is_filled", False),
            fill_strategy=gd.get("fill_strategy", ""),
        )
        gaps.append(gap)

    inventory = MaterialInventory(
        items=items,
        gaps=gaps,
        coverage_rate=d.get("coverage_rate", 0),
    )
    logger.info(f"Loaded MaterialInventory: {len(items)} items, {len(gaps)} gaps")
    return inventory


async def main():
    logger.info("=" * 60)
    logger.info("断点续跑：从已有分析产物继续 Pipeline")
    logger.info("=" * 60)

    # 1. 加载已保存的分析产物
    vs = load_video_structure()
    inventory = load_inventory()

    # 2. 从 run_info 读取原始参数
    run_info_path = RESUME_RUN_DIR / "run_info.json"
    with open(run_info_path, encoding="utf-8") as f:
        run_info = json.load(f)

    # 3. 构造初始状态，跳过 analyst 和 material_manager
    initial_state: ViralEngineState = {
        "sample_videos": run_info.get("sample_videos", []),
        "user_materials": [],
        "target_topic": run_info.get("target_topic", "北京旅行Vlog"),
        "target_info": {},
        "user_preferences": {},
        "domain": "vlog",
        "vlog_style_preference": "",
        "narrative_type_hint": "",
        "persona_config": {},
        "source_structures": [vs],
        "material_inventory": inventory,
        "scheme": None,
        "knowledge_refs": [],
        "gap_report": {},
        "generated_materials": [],
        "rendered_video_path": "",
        "review_result": {},
        "current_task": {},
        "last_result": {},
        "output_dir": str(RESUME_RUN_DIR),
        "run_id": run_info.get("run_id", "resume_run"),
        "phase": "planning",          # <-- 跳过 analyst/material，从策划开始
        "iteration": 0,
        "max_iterations": run_info.get("max_iterations", 3),
        "is_complete": False,
        "errors": [],
        "logs": [],
    }

    # 4. 构建并运行 graph
    app = build_graph()

    logger.info(f"开始运行 Pipeline (从 planning 阶段继续)...")
    logger.info(f"主题: {initial_state['target_topic']}")
    logger.info(f"已有结构分析: {len(initial_state['source_structures'])} 条")
    logger.info(f"已有素材: {len(inventory.items)} 个")

    final_state = await app.ainvoke(initial_state)

    logger.info("=" * 60)
    logger.info(f"Pipeline 完成")
    logger.info(f"最终阶段: {final_state.get('phase')}")
    logger.info(f"完成: {final_state.get('is_complete')}")
    logger.info(f"错误数: {len(final_state.get('errors', []))}")
    logger.info(f"渲染视频: {final_state.get('rendered_video_path', 'N/A')}")
    logger.info("=" * 60)

    # 保存结果摘要
    result = {
        "status": "completed",
        "phase": final_state.get("phase"),
        "is_complete": final_state.get("is_complete"),
        "rendered_video_path": final_state.get("rendered_video_path"),
        "error_count": len(final_state.get("errors", [])),
        "errors": final_state.get("errors", []),
    }
    result_path = Path(run_info.get("run_id", "resume_run") + "_result.json")
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    logger.info(f"结果已保存至: {result_path.resolve()}")


if __name__ == "__main__":
    asyncio.run(main())
