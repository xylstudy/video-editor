"""Analyze an image manifest and write a material inventory."""
import argparse
import asyncio
import json
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

from config.llm_client import LLMTools
from config import settings
from config.output_manager import OutputManager
from tools.face_tools import FaceTools
from agents.material_manager import MaterialManagerAgent
from models.material import MaterialType, MaterialInventory


def parse_args():
    parser = argparse.ArgumentParser(description="图片素材分析")
    parser.add_argument("--materials-json", required=True, help="待分析素材清单 JSON")
    parser.add_argument("--topic", default="短视频", help="目标视频主题")
    parser.add_argument("--run-id", default="material_analysis", help="本次运行 ID")
    parser.add_argument("--output", default="", help="库存 JSON 的精确输出路径")
    return parser.parse_args()


async def main():
    args = parse_args()
    target_topic = args.topic
    materials_json = args.materials_json
    run_id = args.run_id

    out = OutputManager(run_id=run_id)
    logger.info(f"输出目录: {out.run_dir}")

    # GLM-4.6V：视觉理解
    vision_llm = LLMTools(
        api_key=settings.VISION_API_KEY,
        base_url=settings.VISION_BASE_URL,
        model=settings.VISION_MODEL_ID,
    )

    face_tools = FaceTools()
    manager = MaterialManagerAgent(vision_llm, face=face_tools)

    # 加载素材列表
    with open(materials_json, "r", encoding="utf-8") as f:
        user_materials = json.load(f)
    logger.info(f"加载 {len(user_materials)} 个素材")

    items = []
    fail_count = 0
    total = len(user_materials)

    for idx, mat in enumerate(user_materials):
        mat_id = mat.get("id", "")
        mat_path = mat.get("path", "")
        mat_type_str = mat.get("type", "image")

        try:
            mtype = MaterialType(mat_type_str)
        except ValueError:
            mtype = MaterialType.IMAGE

        if not Path(mat_path).exists():
            logger.warning(f"   [{idx+1}/{total}] 素材不存在: {mat_path}")
            continue

        logger.info(f"   [{idx+1}/{total}] {Path(mat_path).name} ({mat_type_str})")

        try:
            if mtype == MaterialType.IMAGE:
                analysis = await manager._analyze_image(mat_id, mat_path, target_topic)
                item = manager.build_material_item(mat_id, mtype, mat_path, analysis)
            elif mtype == MaterialType.VIDEO:
                analysis = await manager._analyze_video_material(mat_id, mat_path, target_topic)
                item = manager.build_material_item(mat_id, mtype, mat_path, analysis)
            else:
                logger.warning(f"    跳过不支持的素材: {mat_type_str}")
                continue

            items.append(item)
            # 打印关键信息
            tags = ", ".join(item.tags[:5])
            logger.info(f"     → {item.description[:50]} | 质量:{item.quality.value} | 标签:{tags}")
        except Exception as e:
            logger.error(f"    失败: {e}")
            fail_count += 1

    # 保存库存
    inventory = MaterialInventory(items=items)
    out.save_json("material", "inventory.json", inventory)
    if args.output:
        output_path = Path(args.output).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(inventory.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        logger.info("任务库存已保存至: %s", output_path)
    logger.info(f"\n入库完成: {len(items)}/{total} 成功 (失败 {fail_count})")
    logger.info(f"  含人脸: {sum(1 for i in items if i.has_face)} 张")
    logger.info(f"  质量分布: {sum(1 for i in items if i.quality.value == 'high')}高 / "
                f"{sum(1 for i in items if i.quality.value == 'medium')}中 / "
                f"{sum(1 for i in items if i.quality.value == 'low')}低")

    items_json = [i.to_dict() if hasattr(i, "to_dict") else str(i) for i in items]
    out.save_json("material", "items_summary.json", items_json)
    logger.info(f"\n素材清单已保存至: {out.run_dir / 'material'}")


if __name__ == "__main__":
    asyncio.run(main())
