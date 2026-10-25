"""统计洞察 API — 仅分析当前用户自己的基因报告。"""
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse

import vse  # noqa: F401  注入 viral-structure-engine 路径
from app_config import STORAGE_ROOT
from auth import get_current_user
from db_models import User
from media import get_current_user_media

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/insights", tags=["insights"])


def _scan_roots(user_id: int) -> list[Path]:
    """只扫描当前用户的基因分析目录。"""
    roots = [STORAGE_ROOT / "users" / str(user_id) / "genes"]
    return [r for r in roots if r.exists()]


def _video_index(video_id: str) -> int:
    try:
        index = int(video_id.removeprefix("video_")) - 1
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="无效的视频标识") from exc
    if index < 0:
        raise HTTPException(status_code=404, detail="视频不存在")
    return index


def _get_user_video(user_id: int, video_id: str):
    from knowledge.insight_miner import discover_analyses

    videos = discover_analyses(_scan_roots(user_id))
    if not videos:
        raise HTTPException(status_code=404, detail="视频不存在")
    index = _video_index(video_id)
    if index >= len(videos):
        raise HTTPException(status_code=404, detail="视频不存在")
    return videos[index]


def _video_cover(video) -> Path | None:
    source = Path(video.video_path) if video.video_path else None
    if source:
        frame_dir = source.parent / "frames"
        for pattern in ("*.jpg", "*.jpeg", "*.png", "*.webp"):
            candidates = sorted(frame_dir.glob(pattern))
            if candidates:
                return candidates[0]
    return None


def _run_mining(user_id: int):
    from knowledge.insight_miner import InsightMiner, discover_analyses

    videos = discover_analyses(_scan_roots(user_id))
    if not videos:
        return None, None
    mined = InsightMiner(videos).mine()
    return mined, videos


def _safe_detail(detail: dict) -> dict:
    analysis = detail.get("analysis") if isinstance(detail.get("analysis"), dict) else {}
    return {
        "index": detail.get("index", 0),
        "has_trace": bool(detail.get("has_trace")),
        "prompt_version": detail.get("prompt_version", ""),
        "model": detail.get("model", ""),
        "summary": analysis.get("one_sentence_summary", ""),
        "reasoning": analysis.get("structure_reasoning", ""),
        "visual": analysis.get("visual_content", ""),
    }


def _safe_video(video, index: int) -> dict:
    details = {
        detail.get("index", i): _safe_detail(detail)
        for i, detail in enumerate(video.shot_details)
    }
    name = Path(video.video_path).name if video.video_path else ""
    source_path = Path(video.video_path) if video.video_path else None
    cover = _video_cover(video)
    return {
        "id": f"video_{index + 1}",
        "name": name or f"分析视频 {index + 1}",
        "format": video.format,
        "duration": video.duration,
        "shot_count": len(video.shots),
        "hook_method": video.hook_method,
        "structure_type": video.structure_type,
        "overall_emotion": video.overall_emotion,
        "front_3s_shot_count": video.front_3s_shot_count,
        "rhythm_curve": video.rhythm_curve,
        "media_available": bool(source_path and source_path.is_file()),
        "cover_available": bool(cover and cover.is_file()),
        "shots": [
            {**shot.to_dict(), "detail": details.get(shot.index, {})}
            for shot in video.shots
        ],
    }


def _response_payload(mined: dict, videos: list) -> dict:
    sample_size = len(videos)
    safe_videos = [_safe_video(video, i) for i, video in enumerate(videos)]
    video_reports = []
    # Keep a true single-video report for drill-down views. The aggregate
    # report is intentionally not reused here because its counters are pooled
    # across every reference video.
    try:
        from knowledge.insight_miner import InsightMiner

        for index, video in enumerate(videos):
            try:
                single = InsightMiner([video]).mine()
                video_reports.append({
                    "video_id": f"video_{index + 1}",
                    "sample_size": 1,
                    "generated_at": single.get("generated_at", ""),
                    "insights": [
                        {key: value for key, value in insight.items() if key != "sources"}
                        for insight in single.get("insights", [])
                    ],
                })
            except (AttributeError, TypeError, ValueError) as exc:
                logger.warning("single-video insight unavailable for %s: %s", index, exc)
    except (AttributeError, TypeError, ValueError) as exc:
        # Keep the endpoint backward-compatible with lightweight test doubles
        # and legacy analysis objects that lack the richer miner properties.
        logger.warning("single-video insight reports unavailable: %s", exc)

    return {
        "mode": "single" if sample_size == 1 else "aggregate",
        "sample_size": sample_size,
        "generated_at": mined["generated_at"],
        "insights": [
            {key: value for key, value in insight.items() if key != "sources"}
            for insight in mined["insights"]
        ],
        "videos": safe_videos,
        "video_reports": video_reports,
    }


@router.get("")
def get_insights(
    current_user: User = Depends(get_current_user),
):
    """挖掘结果 JSON（洞察列表 + 样本信息）。"""
    from insight_cache import read_cached_insights
    cached = read_cached_insights(current_user.id)
    if cached is not None:
        return cached
    try:
        mined, videos = _run_mining(current_user.id)
    except Exception as exc:
        logger.exception("统计洞察生成失败")
        raise HTTPException(status_code=500, detail="统计洞察生成失败") from exc
    if mined is None or videos is None:
        return {
            "mode": "empty",
            "sample_size": 0,
            "videos": [],
            "video_reports": [],
            "insights": [],
            "generated_at": "",
        }
    return _response_payload(mined, videos)


@router.get("/videos/{video_id}/cover")
def get_video_cover(
    video_id: str,
    current_user: User = Depends(get_current_user_media),
):
    video = _get_user_video(current_user.id, video_id)
    cover = _video_cover(video)
    if not cover or not cover.is_file():
        raise HTTPException(status_code=404, detail="视频封面不存在")
    return FileResponse(cover, media_type="image/jpeg")


@router.get("/videos/{video_id}/media")
def get_video_media(
    video_id: str,
    request: Request,
    current_user: User = Depends(get_current_user_media),
):
    video = _get_user_video(current_user.id, video_id)
    path = Path(video.video_path) if video.video_path else None
    if not path or not path.is_file():
        raise HTTPException(status_code=404, detail="视频文件不存在")
    from media import range_file_response

    return range_file_response(request, path, media_type="video/mp4")


@router.get("/report", response_class=HTMLResponse)
def get_insights_report(
    video_id: str | None = None,
    current_user: User = Depends(get_current_user_media),
):
    """自包含 HTML 洞察报告（iframe 嵌入用，支持 ?token= 鉴权）。

    每次请求实时重新挖掘，保证新分析的视频立即出现在报告里。
    """
    mined, videos = _run_mining(current_user.id)
    if mined is None or videos is None:
        return HTMLResponse(
            "<html><body style='font-family:sans-serif;padding:40px;color:#888'>"
            "暂无可分析的报告——请先在基因库中分析至少一个视频。</body></html>"
        )
    if video_id:
        try:
            index = int(video_id.removeprefix("video_")) - 1
        except ValueError:
            raise HTTPException(status_code=400, detail="无效的视频报告标识")
        if index < 0 or index >= len(videos):
            raise HTTPException(status_code=404, detail="视频报告不存在")
        from knowledge.insight_miner import InsightMiner

        videos = [videos[index]]
        mined = InsightMiner(videos).mine()

    from insight_report import generate_report

    report_path = vse.VSE_TEMP_DIR / f"insight_report_u{current_user.id}.html"
    generate_report(mined, videos, report_path)
    return HTMLResponse(report_path.read_text(encoding="utf-8"))
