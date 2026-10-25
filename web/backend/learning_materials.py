"""Build self-contained demo material manifests from a task's actual footage."""
import json
from pathlib import Path
from uuid import uuid4

from sqlmodel import Session, select

from database import engine
from db_models import Gene, GeneStatus, MaterialType, Project, Task, TaskStatus


def prepare_example_materials(gene_id: int, user_id: int, project_id: int | None = None, expected_materials=None):
    from personal_knowledge_demos import _prepare_assets, _asset_name, reference_materials
    from pipeline_runner import find_materials

    with Session(engine) as session:
        gene = session.get(Gene, gene_id)
        if not gene or gene.user_id != user_id or gene.status != GeneStatus.DONE:
            raise RuntimeError("来源基因不存在或尚未完成")
        gene_video, report_path = Path(gene.video_path), Path(gene.report_path)
        candidates = []
        materials = []
        if project_id:
            project = session.get(Project, project_id)
            if not project or project.user_id != user_id:
                raise RuntimeError("来源项目已删除")
            _, materials = find_materials(session, project_id)
            for material in materials:
                if expected_materials is not None:
                    original = next((item for item in expected_materials if item["id"] == material.id), None)
                    if not original:
                        continue
                    source = Path(material.storage_path)
                    if str(source) != original["path"] or not source.is_file() or source.stat().st_size != original["size"] or source.stat().st_mtime_ns != original["mtime_ns"]:
                        raise RuntimeError("本次任务的示例素材已改变，不能替换为其他任务的素材")
                if material.type == MaterialType.VIDEO and Path(material.storage_path).is_file():
                    candidates.append({"path": material.storage_path, "role": material.filename, "origin": "task_materials"})
    # Photos are not substituted for real video. Use distinct reference shots
    # when the project has fewer than two real source videos.
    if expected_materials is not None and not {item["id"] for item in expected_materials}.issubset({item.id for item in materials}):
        raise RuntimeError("本次任务的部分素材已删除")
    candidates = list({str(Path(item["path"]).resolve()): item for item in candidates}.values())
    # Prefer complementary visual roles from this task, without depending on
    # any example filename/hash or a curated directory outside the project.
    import re
    selected = []
    for role, pattern in [
        ("场景", r"street|city|pedestrian|bus|街|城市"),
        ("视觉钩子", r"splash|balloon|水花|奇观|气球"),
        ("趣味贴纸", r"dog|cat|pet|狗|猫"),
        ("动作", r"slicing|cutting|slice|切|动作"),
        ("细节", r"drink|pour|coffee|juice|饮|咖啡"),
        ("高潮", r"carousel|fair|amusement|乐园|游乐"),
    ]:
        item = next((item for item in candidates if item not in selected and re.search(pattern, item["role"], re.I)), None)
        if item:
            selected.append(item)
    candidates = (selected + [item for item in candidates if item not in selected])[:6]
    if len(candidates) < 2:
        candidates = reference_materials(gene_video, report_path)
    if len(candidates) < 2:
        raise RuntimeError("没有足够的不同实拍片段，无法生成真实剪辑示例")
    directory = gene_video.parent / "example_materials"
    # Keep the complete, task-scoped footage pool for focused effect examples.
    # The montage still uses the six complementary clips chosen above.
    effect_candidates = list({str(Path(material.storage_path).resolve()):
        {"path": material.storage_path, "role": material.filename, "origin": "task_materials"}
        for material in materials if material.type == MaterialType.VIDEO
        and Path(material.storage_path).is_file()
        and (expected_materials is None or material.id in {item['id'] for item in expected_materials})}.values())[:24]
    if not project_id:
        existing_path = directory / 'manifest.json'
        try:
            existing = json.loads(existing_path.read_text(encoding='utf-8'))
            if existing.get('gene_id') == gene_id and all(Path(item['path']).is_file() and Path(item['path']).resolve().is_relative_to(directory.resolve()) for item in existing.get('materials', [])) and existing.get('materials'):
                return existing
        except (OSError, ValueError, KeyError, TypeError):
            pass
    _prepare_assets(list({ _asset_name(item): item for item in candidates + effect_candidates }.values()), directory)
    normalized = [{"path": str(directory / _asset_name(item)), "role": item["role"], "origin": item.get("origin", "task_materials"),
                   "source_name": Path(item["path"]).name, "start": 0, "source_start": item.get("start", 0), "source_duration": item.get("duration")}
                  for item in candidates]
    effect_normalized = [{"path": str(directory / _asset_name(item)), "role": item['role'],
                          "origin": 'task_materials', 'source_name': Path(item['path']).name,
                          'start': 0, 'source_start': 0, 'source_duration': None} for item in effect_candidates]
    manifest = {"gene_id": gene_id, "project_id": project_id, "materials": normalized, "effect_materials": effect_normalized}
    temporary = directory / f"manifest-{uuid4().hex}.tmp"
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(directory / "manifest.json")
    return manifest
