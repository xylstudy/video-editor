import json
import logging
import re
import shutil
from pathlib import Path
from typing import Any

from langgraph.graph import StateGraph, END

from graph.state import ViralEngineState
from agents.supervisor import SupervisorAgent
from agents.analyst import AnalystAgent
from agents.material_manager import MaterialManagerAgent
from agents.planner import PlannerAgent
from agents.creative import CreativeAgent
from agents.reviewer import ReviewerAgent
from agents.renderer import RendererAgent
from models.material import MaterialInventory, MaterialItem, MaterialType
from models.scheme import VideoScheme
from models.trace import (
    ANALYST_PROMPT_VERSION, STRUCTURE_PROMPT_VERSION,
    make_shot_trace, make_analysis_trace,
)
from config.llm_client import LLMTools
from config.output_manager import OutputManager
from config import settings
from tools.video_tools import VideoTools
from tools.face_tools import FaceTools
from tools.audio_tools import AudioTools
from tools.remotion_renderer import render_with_remotion

logger = logging.getLogger(__name__)


def _get_out(state: ViralEngineState) -> OutputManager:
    return OutputManager(run_id=state.get("run_id", ""))


def _create_llm() -> LLMTools:
    """默认文本 LLM（DeepSeek），用于各类 Agent 文本推理"""
    return LLMTools(
        api_key=settings.TEXT_API_KEY,
        base_url=settings.TEXT_BASE_URL,
        model=settings.TEXT_MODEL_ID,
    )


def _create_vision_llm() -> LLMTools:
    """使用智谱 GLM-4.6V 进行爆款视频画面理解"""
    return LLMTools(
        api_key=settings.VISION_API_KEY,
        base_url=settings.VISION_BASE_URL,
        model=settings.VISION_MODEL_ID,
    )


def _collect_knowledge_refs() -> list[str]:
    """收集注入 Planner 的手法注册表 id 列表（前缀区分来源，供 reviewer 关联与效果统计）。"""
    try:
        from knowledge.techniques_loader import load_registry
        reg = load_registry()
        refs = [f"transition:{k}" for k in reg.get("transitions", {})]
        refs += [f"effect:{k}" for k in reg.get("effects", {})]
        refs += [f"fg_reveal:{k}" for k in reg.get("foreground_reveal_effects", {})]
        refs += [f"subtitle:{k}" for k in reg.get("subtitle_styles", {})]
        refs += [f"style_profile:{k}" for k in reg.get("style_profiles", {})]
        return refs
    except Exception:
        return []


def _compact_skill_routing_context(state: ViralEngineState, genes: list) -> str:
    """Build a bounded, path-free context for semantic Skill routing."""
    inventory = state.get("material_inventory")
    if hasattr(inventory, "to_dict"):
        inventory = inventory.to_dict()
    inventory = inventory if isinstance(inventory, dict) else {}
    raw_items = inventory.get("items", inventory.get("materials", []))
    compact_items = []
    for item in raw_items[:40] if isinstance(raw_items, list) else []:
        if not isinstance(item, dict):
            continue
        compact_items.append({
            key: item.get(key)
            for key in (
                "id", "type", "description", "scene_type", "shot_scale",
                "camera_motion", "motion_intensity", "emotion_tags",
                "semantic_tags", "suitable_functions", "quality_score",
            )
            if item.get(key) not in (None, "", [], {})
        })
    raw_preferences = state.get("user_preferences", {})
    raw_preferences = raw_preferences if isinstance(raw_preferences, dict) else {}
    compact_preferences = {
        key: raw_preferences.get(key)
        for key in (
            "style", "duration", "shot_count_target", "total_duration_guide",
            "material_usage", "narrative_type", "vlog_style_preference", "note",
        )
        if raw_preferences.get(key) not in (None, "", [], {})
    }
    compact_genes = []
    for gene in genes:
        value = gene.to_dict() if hasattr(gene, "to_dict") else gene
        if isinstance(value, dict):
            value = dict(value)
            value.pop("source_path", None)
        compact_genes.append(value)
    payload = {
        "target_topic": state.get("target_topic", ""),
        "user_preferences": compact_preferences,
        "reference_genes": compact_genes,
        "material_summary": {
            "item_count": len(raw_items) if isinstance(raw_items, list) else 0,
            "items": compact_items,
        },
    }
    # Semantic routing needs a summary, not the complete task state.
    return json.dumps(payload, ensure_ascii=False, default=str)[:12000]


async def _collect_gene_and_skills(
    state: ViralEngineState,
    llm: LLMTools | None = None,
) -> tuple[str, list[str], list, dict]:
    """从 state 中取出 Reference Gene，并按需路由加载 Editing Skill。

    返回 (gene_json, skill_refs, skill_context, skill_plan)：
      - gene_json:   Reference Gene 序列化文本（Planner 的核心结构约束）
      - skill_refs:  本次按需加载的 Skill reference 名（渐进式披露）
      - skill_context: [{name, content}]，直接注入 Planner prompt
      - skill_plan:  每个 Skill 的版本、触发原因与选择方式，供审计/验证使用
    """
    from skills.router import SkillRouter

    genes = []
    for vs in state.get("source_structures", []):
        g = getattr(vs, "gene", None)
        if g is not None:
            genes.append(g)
    if not genes:
        genes = [g for g in state.get("source_genes", []) if g]

    gene_json = "\n\n".join(
        json.dumps(g.to_dict() if hasattr(g, "to_dict") else g, ensure_ascii=False)
        for g in genes
    ) if genes else ""

    router = SkillRouter()
    existing_plan = state.get("skill_plan")
    if isinstance(existing_plan, dict) and existing_plan.get("references"):
        loaded_references = router.collect(existing_plan.get("references", []))
        skill_refs = [reference.name for reference in loaded_references]
        skill_context = [reference.to_dict() for reference in loaded_references]
        return gene_json, skill_refs, skill_context, existing_plan

    if llm is not None:
        route_context = _compact_skill_routing_context(state, genes)
        plan = await router.route_hybrid(genes, route_context, llm)
    else:
        plan = router.route_for_genes(genes)
    skill_refs = list(plan.references)
    skill_context = [r.to_dict() for r in router.collect(skill_refs)] if skill_refs else []
    skill_plan = plan.to_dict()
    return gene_json, skill_refs, skill_context, skill_plan


async def supervisor_node(state: ViralEngineState) -> dict:
    """Supervisor 节点：判断下一步该叫谁"""
    llm = _create_llm()
    supervisor = SupervisorAgent(llm)
    decision = await supervisor.decide_next(state)

    next_expert = decision.get("next_expert", "__end__")
    task_desc = decision.get("task_description", "")

    logger.info(f"Supervisor 决策: → {next_expert} | {task_desc}")
    logs = list(state.get("logs", []))
    log_entry = {"stage": "supervisor", "decision": next_expert, "reason": decision.get("reasoning", "")}
    logs.append(log_entry)

    out = _get_out(state)
    out.append_log("supervisor", log_entry)

    return {
        "current_task": {
            "expert": next_expert,
            "task_description": task_desc,
            "context": decision,
        },
        "logs": logs,
    }


async def analyst_node(state: ViralEngineState) -> dict:
    """分析师节点：用 GLM-4.6V 分析爆款Vlog"""
    out = _get_out(state)
    llm = _create_vision_llm()
    video_tools = VideoTools()
    face_tools = FaceTools()
    audio_tools = AudioTools()
    analyst = AnalystAgent(llm, video_tools, face_tools, audio_tools)

    sample_videos = state.get("sample_videos", [])
    structures = list(state.get("source_structures", []))
    genes = list(state.get("source_genes", []))
    errors = list(state.get("errors", []))
    logs = list(state.get("logs", []))

    task = state.get("current_task", {})
    video_index = len(structures)

    if video_index >= len(sample_videos):
        return {"phase": "materials", "current_task": {}}

    video_path = sample_videos[video_index]
    logger.info(f"")
    logger.info(f"  ===========================================")
    logger.info(f"    分析师：正在逐镜头分析视频")
    logger.info(f"    视频: {Path(video_path).name}")
    logger.info(f"  ===========================================")

    try:
        info = video_tools.get_video_info(video_path)
        scenes = video_tools.detect_scene_changes(video_path)
        out.save_json("analyst", "video_info.json", info)
        out.save_json("analyst", "scenes.json", scenes)

        # ===== 预处理阶段 =====

        # 1. 镜头多帧抽取
        frames_map = video_tools.extract_multiple_frames(video_path, scenes, frames_per_shot=3)

        # 保存关键帧图片到 frames/
        for shot_idx, frame_paths in frames_map.items():
            for fpath in frame_paths:
                p = Path(fpath)
                if p.exists():
                    out.copy_to("analyst/frames", str(p), f"shot_{shot_idx:03d}_{p.name}")

        # 2. 节奏数据计算
        rhythm_data = video_tools.compute_rhythm_data(scenes, info["duration"])

        # 3. 音频分析（可选，失败不影响主流程）
        transcript = ""
        audio_data = {}
        try:
            audio_path = video_tools.extract_audio(video_path)
            a_tools = AudioTools()
            transcript = a_tools.transcribe(audio_path)
            audio_data = a_tools.analyze_audio_segments(audio_path)

            # 增强音频分析：节拍检测 + 关键转场候选 + 推荐 Ken Burns 速度
            beat_info = a_tools.detect_beats(audio_path)
            audio_data["bpm"] = beat_info.get("bpm", audio_data.get("bpm", 0))
            audio_data["beat_times"] = beat_info.get("beat_times", [])
            audio_data["beat_count"] = beat_info.get("beat_count", 0)
            audio_data["key_transitions"] = a_tools.compute_key_transitions(
                beat_info.get("beat_times", []),
                audio_data.get("bpm", 0),
            )
            # 根据 BPM 推导 Ken Burns 推荐速度
            bpm = audio_data.get("bpm", 0)
            if bpm > 120:
                audio_data["recommended_ken_burns_speed"] = "fast"
            elif bpm > 90:
                audio_data["recommended_ken_burns_speed"] = "medium"
            else:
                audio_data["recommended_ken_burns_speed"] = "slow"
        except Exception as e:
            logger.debug(f"音频分析跳过: {e}")

        # ===== 逐镜头 LLM 分析阶段 =====
        shot_analyses = []
        shot_traces = []  # 分析轨迹：记录每镜头的推理上下文与原始返回
        prev_desc = ""
        total_shots = len(scenes)
        for i, scene in enumerate(scenes):
            logger.info(f"  [分析师] 镜头 {i+1}/{total_shots} ({scene['start']:.1f}s-{scene['end']:.1f}s) 分析中...")
            motion = video_tools.compute_shot_motion(video_path, scene["start"], scene["end"])
            color = video_tools.compute_color_stats(frames_map.get(i, []))
            try:
                # Fix: method name is _analyze_shot, not _analyze_frame
                analysis = await analyst._analyze_shot(
                    shot_index=i, start_time=scene["start"], end_time=scene["end"],
                    total_duration=info["duration"], prev_frame_desc=prev_desc,
                    video_path=video_path,
                    motion_intensity=motion,
                    color_stats=color,
                )
            except Exception as e:
                logger.warning(f"  镜头 {i+1} 分析失败: {e}，跳过")
                errors.append(f"shot_{i}_analysis: {e}")
                shot_traces.append(make_shot_trace(
                    index=i, start_time=scene["start"], end_time=scene["end"],
                    analysis={"_error": str(e)}, frame_paths=frames_map.get(i, []),
                    motion_intensity=motion, color_stats=color,
                    prev_context_summary=prev_desc,
                    model=getattr(llm, "model", ""),
                ))
                continue
            analysis["start_time"] = scene["start"]
            analysis["end_time"] = scene["end"]
            analysis["motion_intensity"] = motion
            analysis["color_stats"] = color
            shot_analyses.append(analysis)
            shot_traces.append(make_shot_trace(
                index=i, start_time=scene["start"], end_time=scene["end"],
                analysis=analysis, frame_paths=frames_map.get(i, []),
                motion_intensity=motion, color_stats=color,
                prev_context_summary=prev_desc,
                model=getattr(llm, "model", ""),
            ))
            prev_desc = analysis.get("one_sentence_summary", "")
            role = analysis.get("structure_role", {})
            logger.info(f"  [分析师]   → {role.get('primary_function', '?')}: {analysis.get('one_sentence_summary', '')[:50]}")

        out.save_json("analyst", "shot_analyses.json", shot_analyses)

        # ===== 全局结构分析阶段 =====
        logger.info(f"  [分析师] 全局结构分析 ({total_shots} 个镜头)...")
        shot_text = json.dumps(shot_analyses, ensure_ascii=False)
        structure = await analyst._analyze_structure(
            duration=info["duration"], width=info["width"], height=info["height"],
            shot_count=len(shot_analyses), shot_analyses_text=shot_text,
            transcript=transcript,
            rhythm_data=rhythm_data,
            audio_data=audio_data,
        )
        out.save_json("analyst", "structure_analysis.json", structure)

        # ===== 分析轨迹落盘：记录推理过程，供知识溯源与故障排查 =====
        trace = make_analysis_trace(
            video_path=str(video_path), duration=info["duration"],
            resolution=[info["width"], info["height"]],
            scene_count=len(scenes), scene_threshold=settings.SCENE_CHANGE_THRESHOLD,
            audio_summary={
                "transcript_chars": len(transcript),
                "bpm": audio_data.get("bpm", 0),
                "beat_count": audio_data.get("beat_count", 0),
                "recommended_ken_burns_speed": audio_data.get("recommended_ken_burns_speed", ""),
            },
            shots=shot_traces,
            structure_input_summary=shot_text,
            structure_analysis=structure,
            versions={
                "model": getattr(llm, "model", ""),
                "prompt_version": f"{ANALYST_PROMPT_VERSION}+{STRUCTURE_PROMPT_VERSION}",
                "llm_client": "LLMTools",
            },
        )
        out.save_json("analyst", "analysis_trace.json", trace)

        video_structure = analyst.build_video_structure(
            video_path, info["duration"], info["width"], info["height"],
            shot_analyses, structure, transcript,
        )
        # 保存音频全轨分析到 VideoStructure
        if audio_data:
            video_structure.audio_analysis = audio_data
        structures.append(video_structure)
        out.save_json("analyst", "video_structure.json", video_structure)

        # ===== 结构基因（Reference Gene）—— Planner 的核心输入 =====
        if video_structure.gene is not None:
            genes.append(video_structure.gene)
            out.save_json("analyst", "gene.json", video_structure.gene)
            logger.info(f"  [分析师] [Gene] 已提取结构基因: "
                        f"{len(video_structure.gene.shot_genes)} 个镜头功能, "
                        f"硬约束 {len(video_structure.gene.hard_constraints)} 条")

        logger.info(f"  [分析师] [OK] 分析完成: {len(shot_analyses)} 个镜头, "
                     f"结构类型: {structure.get('structure_type', {}).get('category', '?')}")
        log_entry = {"stage": "analyst", "video": video_path, "shots": len(shot_analyses)}
        logs.append(log_entry)
        out.append_log("analyst", log_entry)

    except Exception as e:
        logger.exception(f"分析失败: {e}")
        errors.append(str(e))

    return {
        "source_structures": structures,
        "source_genes": genes,
        "phase": "analyst" if video_index + 1 < len(sample_videos) else "materials",
        "errors": errors,
        "logs": logs,
        "current_task": {},
    }


async def material_node(state: ViralEngineState) -> dict:
    """素材节点：入库和理解用户素材"""
    out = _get_out(state)
    llm = _create_vision_llm()  # 图像分析需要视觉模型
    manager = MaterialManagerAgent(llm, VideoTools(), FaceTools())

    user_materials = state.get("user_materials", [])
    target_topic = state.get("target_topic", "")
    topic_desc = state.get("target_info", {}).get("description", "")
    errors = list(state.get("errors", []))
    logs = list(state.get("logs", []))

    logger.info(f"")
    logger.info(f"  ===========================================")
    logger.info(f"    素材管家：分析用户素材 ({len(user_materials)} 个)")
    logger.info(f"  ===========================================")

    items = []
    total_mats = len(user_materials)
    for idx, mat in enumerate(user_materials):
        mat_id = mat.get("id", "")
        mat_path = mat.get("path", "")
        mat_type_str = mat.get("type", "image")
        logger.info(f"  [素材] [{idx+1}/{total_mats}] {Path(mat_path).name} ({mat_type_str})")

        try:
            mtype = MaterialType(mat_type_str)
        except ValueError:
            mtype = MaterialType.IMAGE

        if not Path(mat_path).exists():
            logger.warning(f"素材不存在: {mat_path}")
            continue

        try:
            if mtype == MaterialType.IMAGE:
                analysis = await manager._analyze_image(mat_id, mat_path, target_topic, topic_desc)
                item = manager.build_material_item(mat_id, mtype, mat_path, analysis)
            elif mtype == MaterialType.VIDEO:
                analysis = await manager._analyze_video_material(mat_id, mat_path, target_topic)
                item = manager.build_material_item(mat_id, mtype, mat_path, analysis)
            elif mtype == MaterialType.TEXT:
                text_content = mat.get("content", "")
                analysis = await manager._analyze_text(target_topic, text_content)
                item = manager.build_material_item(mat_id, mtype, mat_path, analysis)
            else:
                item = MaterialItem(id=mat_id, type=mtype, path=mat_path)
            items.append(item)
        except Exception as e:
            logger.error(f"素材分析失败 {mat_id}: {e}")
            errors.append(str(e))

    inventory = MaterialInventory(items=items)
    out.save_json("material", "inventory.json", inventory)
    face_items = len(inventory.get_face_items()) if hasattr(inventory, "get_face_items") else 0
    logger.info(f"  [素材] [OK] 入库完成: {len(items)} 个素材 (含人脸: {face_items})")
    log_entry = {"stage": "material", "items": len(items)}
    logs.append(log_entry)
    out.append_log("material", log_entry)

    return {
        "material_inventory": inventory,
        "phase": "planning",
        "errors": errors,
        "logs": logs,
        "current_task": {},
    }


async def planner_node(state: ViralEngineState) -> dict:
    """编导节点：生成迁移方案"""
    out = _get_out(state)
    llm = _create_llm()
    planner = PlannerAgent(llm)

    target_topic = state.get("target_topic", "")
    target_info = state.get("target_info", {})
    preferences = state.get("user_preferences", {})
    review_result = state.get("review_result", {})
    iteration = state.get("iteration", 0)
    errors = list(state.get("errors", []))
    logs = list(state.get("logs", []))

    structures = state.get("source_structures", [])

    # ===== Reference Gene + 确定性规则/LLM 语义补充的混合 Skill 路由 =====
    gene_json, skill_refs, skill_context, skill_plan = await _collect_gene_and_skills(state, llm)

    logger.info(f"")
    logger.info(f"  ===========================================")
    logger.info(f"    编导策划：{'迭代优化方案' if iteration > 0 else '生成迁移方案'} (第{iteration+1}轮)")
    logger.info(f"  ===========================================")
    logger.info(
        "  [编导] Reference Gene: %d 条 | Skill 路由: %s | 按需加载: %s",
        len(state.get("source_genes", [])),
        skill_plan.get("routing_mode", "deterministic"),
        skill_refs or "无",
    )
    if skill_plan.get("semantic_routing_error"):
        logger.warning(
            "  [编导] Skill 语义路由失败，已降级为确定性结果: %s",
            skill_plan["semantic_routing_error"],
        )

    try:
        if iteration == 0:
            structure_summaries = []
            for vs in structures:
                s = vs.to_dict() if hasattr(vs, "to_dict") else str(vs)
                structure_summaries.append(json.dumps(s, ensure_ascii=False))
            structure_summary = "\n\n".join(structure_summaries)

            logger.info(f"  [编导] 提取结构骨架...")
            skeleton = await planner._extract_skeleton(
                structure_summary, target_topic, json.dumps(target_info, ensure_ascii=False),
            )
            out.save_json("planner", "skeleton.json", skeleton)
            logger.info(f"  [编导] 骨架提取完成")

            inventory = state.get("material_inventory")
            inv_json = json.dumps(
                inventory.to_dict() if hasattr(inventory, "to_dict") else {},
                ensure_ascii=False,
            )

            logger.info(f"  [编导] 生成视频方案...")
            # 提取音频分析数据，传递给 Planner
            audio_data_str = ""
            for vs in structures:
                if hasattr(vs, 'audio_analysis') and vs.audio_analysis:
                    audio_data_str = json.dumps(vs.audio_analysis, ensure_ascii=False)
                    break
            scheme_data = await planner._generate_scheme(
                json.dumps(skeleton, ensure_ascii=False), inv_json,
                target_topic, json.dumps(target_info, ensure_ascii=False),
                json.dumps(preferences, ensure_ascii=False),
                audio_data=audio_data_str,
                gene_json=gene_json,
                skill_context=skill_context,
            )
        else:
            scheme = state.get("scheme")
            scheme_json = json.dumps(scheme.to_dict() if hasattr(scheme, "to_dict") else {}, ensure_ascii=False)
            review_json = json.dumps(review_result, ensure_ascii=False)
            inventory = state.get("material_inventory")
            inv_json = json.dumps(
                inventory.to_dict() if hasattr(inventory, "to_dict") else {},
                ensure_ascii=False,
            )
            logger.info(f"  [编导] 根据审核结果迭代优化...")
            scheme_data = await planner._iterate_scheme(
                scheme_json, review_json, inv_json,
                gene_json=gene_json, skill_context=skill_context,
            )

        scheme = planner.build_scheme(scheme_data, target_topic, iteration)
        scheme.knowledge_refs = _collect_knowledge_refs()
        # A routed reference is not automatically "used".  Persist selection,
        # prompt loading, model declaration and rule verification separately.
        from skills.verifier import initialise_skill_trace, verify_skill_usage
        initialise_skill_trace(scheme, skill_plan)
        skill_trace = verify_skill_usage(
            scheme, skill_plan, state.get("material_inventory")
        )
        out.save_json("planner", f"skill_routing_v{iteration}.json", skill_plan)
        out.save_json("evaluation", f"skill_evaluation_v{iteration}.json", skill_trace)
        out.save_json("planner", f"scheme_v{iteration}.json", scheme)
        logger.info(f"  [编导] [OK] 方案生成完成: {len(scheme.storyboard)} 个分镜, 目标时长 {scheme.target_duration}s")
        log_entry = {"stage": "planner", "iteration": iteration, "frames": len(scheme.storyboard)}
        logs.append(log_entry)
        out.append_log("planner", log_entry)

        # ===== 方案决策轨迹：记录编导做方案时参考了什么 =====
        inventory_summary = {}
        inventory = state.get("material_inventory")
        if inventory:
            items = getattr(inventory, "items", getattr(inventory, "materials", []))
            type_counts: dict[str, int] = {}
            face_count = 0
            for m in items:
                t = str(getattr(m, "type", "unknown"))
                type_counts[t] = type_counts.get(t, 0) + 1
                if getattr(m, "has_face", False):
                    face_count += 1
            inventory_summary = {"total": len(items), "by_type": type_counts, "face_count": face_count}
        planning_trace = {
            "iteration": iteration,
            "target_topic": target_topic,
            "skeleton": skeleton if iteration == 0 else "(迭代轮：基于审核反馈修改)",
            "review_feedback": review_result if iteration > 0 else {},
            "gene": (gene_json[:3000] + "...") if len(gene_json) > 3000 else gene_json,
            "skill_refs": skill_refs,
            "skill_routing": skill_plan,
            "skill_trace": skill_trace,
            "knowledge_refs": scheme.knowledge_refs,
            "inventory_summary": inventory_summary,
            "audio_data": audio_data_str if iteration == 0 else "",
            "scheme_frame_count": len(scheme.storyboard),
            "adaptation_log": getattr(scheme, "adaptation_log", []),
        }
        out.save_json("planner", "planning_trace.json", planning_trace)

        return {
            "scheme": scheme,
            "skill_refs": list(getattr(scheme, "declared_skill_refs", [])),
            "skill_plan": skill_plan,
            "skill_trace": skill_trace,
            "phase": "renderer" if iteration == 0 else "review",
            "errors": errors,
            "logs": logs,
            "current_task": {},
        }

    except Exception as e:
        logger.exception(f"方案生成失败: {e}")
        errors.append(str(e))
        return {
            "errors": errors,
            "logs": logs,
            "current_task": {},
            "phase": "complete",
            "is_complete": True,
        }


async def creative_node(state: ViralEngineState) -> dict:
    """补全节点：处理素材缺口，支持图像生成（Z-Image-Turbo / Qwen-Image-2.0）"""
    out = _get_out(state)
    llm = _create_llm()
    creative = CreativeAgent(llm, VideoTools(), FaceTools())

    scheme = state.get("scheme")
    inventory = state.get("material_inventory")
    errors = list(state.get("errors", []))
    logs = list(state.get("logs", []))

    if not scheme or not inventory:
        return {"phase": "assemble", "current_task": {}}

    gaps = []
    if hasattr(inventory, "gaps"):
        gaps = [g for g in inventory.gaps if not getattr(g, "is_filled", False)]

    logger.info(f"")
    logger.info(f"  ===========================================")
    logger.info(f"    创意补全：处理 {len(gaps)} 个素材缺口")
    logger.info(f"  ===========================================")

    if not gaps:
        logger.info(f"  [补全] 无缺口，跳过")
        return {"phase": "assemble", "current_task": {}}

    try:
        storyboard = getattr(scheme, "storyboard", [])
        frames_desc = "\n".join(
            f"  [{f.index}] {getattr(f, 'shot_type', '')} {getattr(f, 'duration', 3)}s"
            for f in storyboard[:10]
        )
        materials_desc = "\n".join(
            f"  [{m.id}] {m.type.value} {m.description[:40]}"
            for m in (getattr(inventory, "items", getattr(inventory, "materials", []))[:10])
        )

        fill_plan = await creative._plan_fill_strategy(frames_desc, materials_desc, "")

        for plan in fill_plan.get("fill_plans", []):
            gap_idx = plan.get("gap_slot_index")
            for g in gaps:
                if g.slot_index == gap_idx:
                    g.is_filled = True
                    g.fill_strategy = plan.get("chosen_strategy", "")
                    break

        out.save_json("creative", "fill_strategy.json", fill_plan)
        plans_count = len(fill_plan.get("fill_plans", []))
        logger.info(f"  [补全] [OK] 已规划 {plans_count} 个补全策略")
        log_entry = {"stage": "creative", "plans": plans_count}
        logs.append(log_entry)
        out.append_log("creative", log_entry)

        return {
            "material_inventory": inventory,
            "generated_materials": fill_plan,
            "phase": "assemble",
            "errors": errors,
            "logs": logs,
            "current_task": {},
        }

    except Exception as e:
        logger.exception(f"补全失败: {e}")
        errors.append(str(e))
        return {"phase": "assemble", "errors": errors, "logs": logs, "current_task": {}}


async def renderer_node(state: ViralEngineState) -> dict:
    """渲染决策节点：分析方案，逐分镜决定渲染策略，生成自定义组件"""
    out = _get_out(state)
    llm = _create_llm()
    renderer = RendererAgent(llm)

    scheme = state.get("scheme")
    inventory = state.get("material_inventory")
    if not scheme:
        return {"phase": "assemble", "current_task": {}}

    logger.info(f"")
    logger.info(f"  ===========================================")
    logger.info(f"    渲染决策：分析方案渲染策略")
    logger.info(f"  ===========================================")
    errors = list(state.get("errors", []))
    logs = list(state.get("logs", []))

    try:
        scheme_json = json.dumps(
            scheme.to_dict() if hasattr(scheme, "to_dict") else {},
            ensure_ascii=False,
        )
        inv_summary = ""
        if inventory:
            items = getattr(inventory, "items", getattr(inventory, "materials", []))
            inv_summary = f"{len(items)} 个素材"

        decisions = await renderer._analyze_scheme(scheme_json, inv_summary)
        frame_decisions = decisions.get("frame_decisions", [])
        out.save_json("renderer", "render_decisions.json", decisions)

        storyboard = list(getattr(scheme, "storyboard", []))
        decisions_map = {d["index"]: d for d in frame_decisions}
        custom_needed = []

        for frame in storyboard:
            d = decisions_map.get(frame.index, {})
            rc = d.get("render_component", "auto")
            object.__setattr__(frame, "render_component", rc)
            config = d.get("custom_render_config", {})
            if config:
                object.__setattr__(frame, "custom_render_config", config)
            if d.get("need_new_component"):
                custom_needed.append({
                    "index": frame.index,
                    "name": rc.replace("custom:", "") if rc.startswith("custom:") else f"frame_{frame.index}",
                    "spec": d.get("new_component_spec", {}),
                    "frame_data": frame.to_dict(),
                })

        generated = 0
        for item in custom_needed:
            result = await renderer._generate_component(
                component_name=item["name"],
                spec_json=json.dumps(item["spec"], ensure_ascii=False),
                frame_json=json.dumps(item["frame_data"], ensure_ascii=False),
            )
            if result.get("file_path"):
                generated += 1
                logger.info(f"生成自定义组件: {item['name']}")

        compile_result = await renderer._compile_components()
        logger.info(f"动态组件编译: {compile_result.get('message', '')}")

        log_entry = {
            "stage": "renderer",
            "decisions": len(frame_decisions),
            "custom_components": generated,
            "compiled": compile_result.get("compiled_count", 0),
        }
        logs.append(log_entry)
        out.append_log("renderer", log_entry)

        return {
            "scheme": scheme,
            "phase": "gaps",
            "errors": errors,
            "logs": logs,
            "current_task": {},
        }

    except Exception as e:
        logger.exception(f"渲染决策失败: {e}")
        errors.append(str(e))
        return {"phase": "gaps", "errors": errors, "logs": logs, "current_task": {}}


async def assembler_node(state: ViralEngineState) -> dict:
    """合成节点：用 Remotion 渲染视频，失败时回退到 FFmpeg"""
    out = _get_out(state)
    scheme = state.get("scheme")
    inventory = state.get("material_inventory")
    errors = list(state.get("errors", []))
    logs = list(state.get("logs", []))

    if not scheme:
        return {"phase": "review", "current_task": {}}

    logger.info(f"")
    logger.info(f"  ===========================================")
    logger.info(f"    视频合成：渲染最终视频")
    logger.info(f"  ===========================================")

    # 从参考视频提取音频，给 FFmpeg 回退使用
    audio_path = None
    sample_videos = state.get("sample_videos", [])
    if sample_videos:
        try:
            from tools.video_tools import VideoTools
            vt = VideoTools()
            audio_path = vt.extract_audio(sample_videos[0])
            logger.info(f"  [合成] 提取参考音频: {Path(audio_path).name}")
        except Exception as e:
            logger.debug(f"  [合成] 音频提取跳过: {e}")

    try:
        rendered = await _render_with_remotion(scheme, inventory)
        if rendered:
            out.copy_to("assembler", rendered, "rendered_video.mp4")
            size_mb = Path(rendered).stat().st_size / 1024 / 1024
            logger.info(f"  [合成] [OK] Remotion 渲染完成: {size_mb:.1f}MB")
            log_entry = {"stage": "assembler", "path": rendered, "method": "remotion"}
            logs.append(log_entry)
            out.append_log("assembler", log_entry)
            return {"rendered_video_path": rendered, "phase": "review", "logs": logs, "current_task": {}}

        logger.warning("  [合成] Remotion 不可用，回退 FFmpeg 智能渲染")
        rendered = await _render_fallback(scheme, inventory, audio_path)
        if rendered:
            out.copy_to("assembler", rendered, "rendered_video.mp4")
            size_mb = Path(rendered).stat().st_size / 1024 / 1024
            logger.info(f"  [合成] [OK] FFmpeg 智能渲染完成: {size_mb:.1f}MB")
            log_entry = {"stage": "assembler", "path": rendered, "method": "ffmpeg_intelligent"}
            logs.append(log_entry)
            out.append_log("assembler", log_entry)
            return {"rendered_video_path": rendered, "phase": "review", "logs": logs, "current_task": {}}

        logger.warning("  [合成] 所有渲染方式均失败")
        return {"phase": "review", "logs": logs, "current_task": {}}

    except Exception as e:
        logger.exception(f"合成失败: {e}")
        errors.append(str(e))
        return {"phase": "review", "errors": errors, "logs": logs, "current_task": {}}


def _safe_filename(name: str, fallback: str = "vlog") -> str:
    """清理文件名中的 Windows 非法字符：\\/:*?\"<>| 和前后空格"""
    name = (name or fallback).strip()
    name = re.sub(r'[\\/:*?"<>|]', "_", name)
    name = re.sub(r"\s+", " ", name)
    return name or fallback


async def _render_with_remotion(scheme, inventory) -> str | None:
    """用 Remotion 渲染完整视频，返回输出路径或 None。"""
    scheme_dict = scheme.to_dict() if hasattr(scheme, "to_dict") else scheme
    output = str(settings.OUTPUT_DIR / f"{_safe_filename(scheme_dict.get('title', 'vlog'))}.mp4")
    return render_with_remotion(scheme, inventory, output)


async def _render_fallback(scheme, inventory, audio_path=None) -> str | None:
    """FFmpeg 回退：使用方案数据渲染高质量视频（Ken Burns、字幕、前景合成、转场、BGM）"""
    try:
        from tools.ffmpeg_renderer import FFMpegRenderer

        renderer = FFMpegRenderer()
        title = _safe_filename(getattr(scheme, "title", "vlog") or "vlog")

        result = renderer.render(scheme, inventory, audio_path)
        if result and Path(result).exists():
            logger.info(f"FFmpeg 智能渲染完成: {result}")
            return result
        logger.warning("FFmpeg 智能渲染返回空，回退到基础拼接")
        # fallback 到基础拼接
        from tools.video_tools import VideoTools
        video = VideoTools()
        material_map = {}
        if inventory:
            for m in getattr(inventory, "items", getattr(inventory, "materials", [])):
                mid = getattr(m, "id", "")
                mpath = getattr(m, "path", "")
                if mid and mpath:
                    material_map[mid] = mpath
        storyboard = getattr(scheme, "storyboard", [])
        clip_paths = []
        for frame in storyboard:
            mid = getattr(frame, "material_id", "") or getattr(frame, "source_material_id", "")
            if mid and mid in material_map:
                clip_paths.append(material_map[mid])
        if clip_paths:
            merged = video.concat_clips(clip_paths)
            # 使用唯一文件名避免文件锁冲突
            output2 = str(settings.OUTPUT_DIR / f"{title}_concat_{id(scheme)}.mp4")
            shutil.copy2(merged, output2)
            Path(merged).unlink(missing_ok=True)
            logger.info(f"FFmpeg 基础拼接完成: {output2}")
            return output2
        return None
    except Exception as e:
        logger.exception(f"FFmpeg 智能渲染失败: {e}")
        return None


async def reviewer_node(state: ViralEngineState) -> dict:
    """审核节点：评估方案质量（10维度，含字幕/素材覆盖率/镜头切换）"""
    out = _get_out(state)
    llm = _create_llm()
    reviewer = ReviewerAgent(llm)

    scheme = state.get("scheme")
    structures = state.get("source_structures", [])
    inventory = state.get("material_inventory")
    errors = list(state.get("errors", []))
    logs = list(state.get("logs", []))

    if not scheme:
        return {"phase": "complete", "is_complete": True, "current_task": {}}

    logger.info(f"")
    logger.info(f"  ===========================================")
    logger.info(f"    方案审核：结构保真 (Fidelity) + 适配质量 (Quality) 双维度")
    logger.info(f"  ===========================================")

    try:
        gene_json, _, _, _ = await _collect_gene_and_skills(state)
        structure_summaries = "\n\n".join(
            json.dumps(vs.to_dict() if hasattr(vs, "to_dict") else str(vs), ensure_ascii=False)
            for vs in structures
        )
        scheme_json = json.dumps(scheme.to_dict() if hasattr(scheme, "to_dict") else {}, ensure_ascii=False)
        out.save_json("planner", "scheme_final.json", json.loads(scheme_json))

        # ---- 素材覆盖描述 ----
        storyboard = getattr(scheme, "storyboard", [])
        shot_count = len(storyboard)
        material_list = []
        used_material_ids = set()
        if inventory:
            items = getattr(inventory, "items", getattr(inventory, "materials", []))
            for m in items:
                mid = getattr(m, "id", "")
                mdesc = getattr(m, "description", "")[:60]
                mtype = getattr(m, "type", "")
                material_list.append(f"  [{mid}] ({mtype}) {mdesc}")
        for frame in storyboard:
            mid = getattr(frame, "material_id", "") or getattr(frame, "source_material_id", "")
            if mid:
                used_material_ids.add(mid)
        material_list_desc = "\n".join(material_list) if material_list else "无素材信息"

        coverage_parts = [
            f"分镜: {shot_count}",
            f"素材总数: {len(material_list)}",
            f"已使用素材数: {len(used_material_ids)}",
            f"未使用素材: {len(material_list) - len(used_material_ids)} 个" if len(material_list) > len(used_material_ids) else "全部素材已使用",
        ]
        coverage = "\n".join(coverage_parts)

        # ---- 镜头切换统计 ----
        transitions = []
        for frame in storyboard:
            tr = getattr(frame, "transition_in", None) or getattr(frame, "transition", "cut")
            transitions.append(f"  分镜{getattr(frame, 'index', 0)}: {tr}")
            if hasattr(frame, "subtitle_text") and frame.subtitle_text:
                transitions.append(f"        字幕: {frame.subtitle_text[:40]}")
        transition_summary = "\n".join(transitions) if transitions else "无切换信息"

        review = await reviewer._review_scheme(
            structure_summaries, scheme_json, coverage,
            material_list_desc=material_list_desc,
            transition_summary=transition_summary,
            gene_json=gene_json,
        )
        from evaluation.run_evaluator import scheme_fingerprint
        review["scheme_fingerprint"] = scheme_fingerprint(json.loads(scheme_json))
        # 关联本方案参考的知识/手法，供后续统计「知识 → 审核分数」效果
        review["knowledge_refs_applied"] = list(getattr(scheme, "knowledge_refs", []))
        review["skill_refs_applied"] = list(getattr(scheme, "declared_skill_refs", []))

        # Reviewer outcome is linked to the trace as observational evidence.
        # It is intentionally not labelled as a causal Skill-effect score.
        from skills.verifier import attach_skill_outcomes
        skill_trace = state.get("skill_trace") or getattr(scheme, "skill_evaluation", {})
        if isinstance(skill_trace, dict):
            attach_skill_outcomes(skill_trace, reviewer=review)
            scheme.skill_evaluation = skill_trace
            out.save_json("evaluation", "skill_evaluation.json", skill_trace)
            out.save_json("planner", "scheme_final.json", scheme)

        if hasattr(scheme, "review_notes"):
            scheme.review_notes.append(json.dumps(review, ensure_ascii=False))

        passed = review.get("pass", False)
        iteration = state.get("iteration", 0) + 1
        max_iter = state.get("max_iterations", 3)

        score = review.get("total_score", 0)
        # hook 分：优先读新 fidelity 维度，回退旧扁平 scores
        hook_score = (
            review.get("fidelity", {}).get("dimensions", {}).get("hook_preserved", {}).get("score")
            or review.get("scores", {}).get("hook_appeal", {}).get("score", 10)
        )
        scores_detail = review.get("scores", {})
        score_line = " | ".join(f"{k}: {v.get('score', '?')}" for k, v in scores_detail.items())
        fidelity_overall = review.get("fidelity", {}).get("overall", "?")
        quality_overall = review.get("quality", {}).get("overall", "?")
        feedback_type = review.get("feedback_type", "?")
        logger.info(f"  [审核] [OK] 评分: {score}/100")
        logger.info(f"  [审核]   Fidelity={fidelity_overall}/10 Quality={quality_overall}/10 | feedback_type={feedback_type}")
        logger.info(f"  [审核]   维度: {score_line}")

        is_complete = passed or iteration >= max_iter or hook_score < 4

        if is_complete:
            logger.info(f"  [审核] [OK] 审核{'通过' if passed else '结束'}")
        else:
            logger.info(f"  [审核] 审核未通过 (总分{score})，进入迭代 {iteration}/{max_iter}")

        out.save_json("reviewer", "review_result.json", review)
        log_entry = {"stage": "reviewer", "score": score, "passed": passed, "iteration": iteration}
        logs.append(log_entry)
        out.append_log("reviewer", log_entry)

        return {
            "review_result": review,
            "skill_trace": skill_trace if isinstance(skill_trace, dict) else {},
            "iteration": iteration,
            "is_complete": is_complete,
            "phase": "complete" if is_complete else "planning",
            "errors": errors,
            "logs": logs,
            "current_task": {},
        }

    except Exception as e:
        logger.exception(f"审核失败: {e}")
        errors.append(str(e))
        return {
            "is_complete": True,
            "phase": "complete",
            "errors": errors,
            "logs": logs,
            "current_task": {},
        }


def build_graph():
    graph = StateGraph(ViralEngineState)

    graph.add_node("supervisor", supervisor_node)
    graph.add_node("analyst", analyst_node)
    graph.add_node("material", material_node)
    graph.add_node("planner", planner_node)
    graph.add_node("renderer", renderer_node)
    graph.add_node("creative", creative_node)
    graph.add_node("assembler", assembler_node)
    graph.add_node("reviewer", reviewer_node)

    graph.set_entry_point("supervisor")

    graph.add_conditional_edges(
        "supervisor",
        lambda s: s.get("current_task", {}).get("expert", "__end__"),
        {
            "analyst": "analyst",
            "material_manager": "material",
            "planner": "planner",
            "renderer": "renderer",
            "creative": "creative",
            "assembler": "assembler",
            "reviewer": "reviewer",
            "__end__": END,
        },
    )

    for node_name in ("analyst", "material", "planner", "renderer", "creative", "assembler", "reviewer"):
        graph.add_conditional_edges(
            node_name,
            lambda s: END if s.get("is_complete") else "supervisor",
            {
                "supervisor": "supervisor",
                END: END,
            },
        )

    return graph.compile()


def create_initial_state(
    sample_videos: list[str],
    user_materials: list[dict],
    target_topic: str,
    target_info: dict | None = None,
    user_preferences: dict | None = None,
    max_iterations: int = 3,
    run_id: str = "",
) -> ViralEngineState:
    out_dir = str(settings.RUNS_DIR / run_id) if run_id else ""
    return {
        "sample_videos": sample_videos,
        "user_materials": user_materials,
        "target_topic": target_topic,
        "target_info": target_info or {},
        "user_preferences": user_preferences or {},
        "domain": "vlog",
        "vlog_style_preference": (user_preferences or {}).get("style", ""),
        "narrative_type_hint": (user_preferences or {}).get("narrative_type", ""),
        "persona_config": (user_preferences or {}).get("persona_config", {}),
        "source_structures": [],
        "source_genes": [],
        "material_inventory": None,
        "scheme": None,
        "knowledge_refs": [],
        "skill_refs": [],
        "skill_plan": {},
        "skill_trace": {},
        "gap_report": {},
        "generated_materials": [],
        "rendered_video_path": "",
        "review_result": {},
        "current_task": {},
        "last_result": {},
        "output_dir": out_dir,
        "run_id": run_id,
        "phase": "init",
        "iteration": 0,
        "max_iterations": max_iterations,
        "is_complete": False,
        "errors": [],
        "logs": [],
    }
