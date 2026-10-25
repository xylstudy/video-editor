"""Build a small, licensed travel-video batch from Wikimedia Commons.

The script stores attribution/provenance for every source, downloads a short
range through ffmpeg, normalises it to H.264 MP4, probes the result, and emits
20 runnable task manifests.  It never treats the clips as proof of virality;
they are an open-licensed functional/evaluation dataset.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


API_URL = "https://commons.wikimedia.org/w/api.php"
USER_AGENT = "video-editor-dataset-builder/1.0 (github.com/xylstudy/video-editor)"


# References are longer, structured travel edits.  Materials are deliberately
# heterogeneous short clips so the same reference structure must adapt to
# different scene/content availability.
ASSETS: list[dict[str, Any]] = [
    {"id": "ref_01", "role": "reference", "title": "File:CZECH SWITZERLAND - 4K TRAVEL VIDEO.webm", "start": 4, "clip": 45, "theme": "nature", "tags": ["landscape", "mountain", "cinematic"]},
    {"id": "ref_02", "role": "reference", "title": "File:Jujuy es magia pura, Jujuy, Argentina.webm", "start": 2, "clip": 45, "theme": "nature", "tags": ["landscape", "travel", "dynamic"]},
    {"id": "ref_03", "role": "reference", "title": "File:Japan- from the North to the South - 北から南へ -.webm", "start": 5, "clip": 45, "theme": "city", "tags": ["japan", "city", "journey"]},
    {"id": "ref_04", "role": "reference", "title": "File:2 Weeks In Italy - A Cinematic Travel Film.webm", "start": 5, "clip": 45, "theme": "architecture", "tags": ["italy", "architecture", "cinematic"]},
    {"id": "ref_05", "role": "reference", "title": "File:The last day of our road trip to Iran in 2 minutes.webm", "start": 3, "clip": 45, "theme": "road_trip", "tags": ["road", "journey", "people"]},

    {"id": "mat_01", "role": "material", "title": "File:Hotel in Sudan.webm", "start": 1, "clip": 8, "theme": "interior", "tags": ["hotel", "interior"]},
    {"id": "mat_02", "role": "material", "title": "File:Водоспад Лоцій.webm", "start": 3, "clip": 8, "theme": "nature", "tags": ["waterfall", "landscape", "motion"]},
    {"id": "mat_03", "role": "material", "title": "File:Hotel in Afghanistan-2.webm", "start": 1, "clip": 8, "theme": "interior", "tags": ["hotel", "room"]},
    {"id": "mat_04", "role": "material", "title": "File:Quadruple Room in Damascus.webm", "start": 2, "clip": 8, "theme": "interior", "tags": ["hotel", "room"]},
    {"id": "mat_05", "role": "material", "title": "File:Acropolis.webm", "start": 3, "clip": 10, "theme": "architecture", "tags": ["acropolis", "architecture", "landmark"]},
    {"id": "mat_06", "role": "material", "title": "File:Hotel in Afghanistan.webm", "start": 5, "clip": 8, "theme": "interior", "tags": ["hotel", "travel"]},
    {"id": "mat_07", "role": "material", "title": "File:Недострой в Бандар-Сери-Бегаване.webm", "start": 3, "clip": 8, "theme": "architecture", "tags": ["building", "city"]},
    {"id": "mat_08", "role": "material", "title": "File:В гостях у брунейца (г. Пекан-Тутонг).webm", "start": 4, "clip": 8, "theme": "people", "tags": ["people", "local", "culture"]},
    {"id": "mat_09", "role": "material", "title": "File:Ночлег в холле студенческого общежития (Киото).webm", "start": 5, "clip": 8, "theme": "people", "tags": ["kyoto", "people", "indoor"]},
    {"id": "mat_10", "role": "material", "title": "File:Cimitirul Vesel de la Sapanta.webm", "start": 8, "clip": 10, "theme": "culture", "tags": ["culture", "landmark", "outdoor"]},
    {"id": "mat_11", "role": "material", "title": "File:RoadToSalineValley.ogv", "start": 5, "clip": 10, "theme": "road_trip", "tags": ["road", "landscape", "motion"]},
    {"id": "mat_12", "role": "material", "title": "File:Berclair Memphis TN Summer Ave from Perkins Rd to Waring Rd.theora.ogv", "start": 4, "clip": 8, "theme": "city", "tags": ["street", "city", "motion"]},
    {"id": "mat_13", "role": "material", "title": "File:Weggebruikers attentie.... onbewaakte overweg-524524.ogv", "start": 12, "clip": 10, "theme": "transport", "tags": ["railway", "transport", "motion"]},
    {"id": "mat_14", "role": "material", "title": "File:La Palma - Road LP-109 from west to east 15 ies.webm", "start": 15, "clip": 10, "theme": "road_trip", "tags": ["road", "island", "motion"]},
    {"id": "mat_15", "role": "material", "title": "File:VID View Of Vivekanand Bridge From Moving Car.ogv", "start": 10, "clip": 10, "theme": "transport", "tags": ["bridge", "car", "motion"]},
    {"id": "mat_16", "role": "material", "title": "File:Bike ride on the outskirt of Janakpur 20161011 165931.ogv", "start": 12, "clip": 10, "theme": "road_trip", "tags": ["bike", "road", "motion"]},
    {"id": "mat_17", "role": "material", "title": "File:View From Bus Of Nepali Highway To Bhairahawa.ogv", "start": 10, "clip": 10, "theme": "transport", "tags": ["bus", "highway", "motion"]},
    {"id": "mat_18", "role": "material", "title": "File:Horse-carriage.webm", "start": 20, "clip": 10, "theme": "transport", "tags": ["horse", "carriage", "people"]},
    {"id": "mat_19", "role": "material", "title": "File:Amazing Mountain bus ride from Monte in Funchal, Madeira, Portugal - No Copyright.webm", "start": 2, "clip": 10, "theme": "nature", "tags": ["mountain", "bus", "motion"]},
    {"id": "mat_20", "role": "material", "title": "File:Resort VILA PORTO MARE - Madeira -- Portugal.webm", "start": 12, "clip": 10, "theme": "architecture", "tags": ["resort", "garden", "architecture"]},
    {"id": "mat_21", "role": "material", "title": "File:Teleférico do Funchal - Holidays Madeira.webm", "start": 15, "clip": 10, "theme": "transport", "tags": ["cable_car", "city", "landscape"]},
    {"id": "mat_22", "role": "material", "title": "File:CAFE OWNER, FUNCHAL- \"The Levadas is THE -1 Attraction On Madeira\" -- Top Travel Tips From Locals.webm", "start": 12, "clip": 10, "theme": "people", "tags": ["cafe", "local", "people"]},
    {"id": "mat_23", "role": "material", "title": "File:Funchal, Madeira, Portugal - City Tour - Impressionen 2017.webm", "start": 20, "clip": 10, "theme": "city", "tags": ["funchal", "city", "street"]},
    {"id": "mat_24", "role": "material", "title": "File:Danco en Po Nagar.webm", "start": 8, "clip": 10, "theme": "culture", "tags": ["dance", "people", "culture"]},
    {"id": "mat_25", "role": "material", "title": "File:Visita la Muralla China en 4 horas.webm", "start": 18, "clip": 10, "theme": "architecture", "tags": ["great_wall", "landmark", "people"]},
]


CASE_SPECS = [
    ("case_01", "自然风光快节奏开场", "ref_01", ["mat_02", "mat_11", "mat_14", "mat_19", "mat_21"]),
    ("case_02", "自然素材不足的结构迁移", "ref_01", ["mat_02", "mat_19", "mat_01"]),
    ("case_03", "山路与交通旅行", "ref_02", ["mat_11", "mat_14", "mat_16", "mat_17", "mat_19"]),
    ("case_04", "自然参考迁移到城市素材", "ref_02", ["mat_12", "mat_15", "mat_21", "mat_23"]),
    ("case_05", "日本城市人物旅行", "ref_03", ["mat_08", "mat_09", "mat_12", "mat_22", "mat_24"]),
    ("case_06", "无人城市交通素材", "ref_03", ["mat_12", "mat_13", "mat_15", "mat_17", "mat_21"]),
    ("case_07", "意大利建筑结构迁移", "ref_04", ["mat_05", "mat_07", "mat_10", "mat_20", "mat_25"]),
    ("case_08", "建筑素材严重不足", "ref_04", ["mat_05", "mat_07", "mat_03"]),
    ("case_09", "公路旅行运动素材", "ref_05", ["mat_11", "mat_14", "mat_15", "mat_16", "mat_17", "mat_18"]),
    ("case_10", "公路参考迁移到人物文化", "ref_05", ["mat_08", "mat_09", "mat_22", "mat_24"]),
    ("case_11", "住宿探店叙事", "ref_03", ["mat_01", "mat_03", "mat_04", "mat_06", "mat_22"]),
    ("case_12", "室内素材的快节奏适配", "ref_01", ["mat_01", "mat_03", "mat_04", "mat_06"]),
    ("case_13", "地标与当地文化", "ref_04", ["mat_05", "mat_10", "mat_24", "mat_25"]),
    ("case_14", "交通方式混剪", "ref_05", ["mat_13", "mat_15", "mat_16", "mat_17", "mat_18", "mat_21"]),
    ("case_15", "城市自然混合素材", "ref_02", ["mat_02", "mat_12", "mat_19", "mat_20", "mat_23"]),
    ("case_16", "人物素材稀缺的情绪迁移", "ref_03", ["mat_08", "mat_22", "mat_02"]),
    ("case_17", "纯运动镜头节奏测试", "ref_01", ["mat_11", "mat_13", "mat_14", "mat_15", "mat_16", "mat_17", "mat_19"]),
    ("case_18", "纯静态感建筑节奏测试", "ref_04", ["mat_05", "mat_07", "mat_10", "mat_20", "mat_25"]),
    ("case_19", "跨地域结构泛化", "ref_05", ["mat_02", "mat_05", "mat_09", "mat_17", "mat_23", "mat_24"]),
    ("case_20", "极少素材降级策略", "ref_02", ["mat_12", "mat_02"]),
]


def _api(params: dict[str, str], attempts: int = 4) -> dict[str, Any]:
    query = urllib.parse.urlencode({"format": "json", "formatversion": "2", "origin": "*", **params})
    request = urllib.request.Request(f"{API_URL}?{query}", headers={"User-Agent": USER_AGENT})
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception:
            if attempt == attempts - 1:
                raise
            time.sleep(2 ** attempt)
    raise RuntimeError("unreachable")


def _strip_html(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html.unescape(value or ""))).strip()


def _meta(ext: dict[str, Any], name: str) -> str:
    item = ext.get(name, {}) if isinstance(ext, dict) else {}
    return _strip_html(str(item.get("value", ""))) if isinstance(item, dict) else ""


def fetch_metadata(assets: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_title: dict[str, dict[str, Any]] = {}
    for offset in range(0, len(assets), 5):
        titles = "|".join(item["title"] for item in assets[offset:offset + 5])
        payload = _api({
            "action": "query",
            "titles": titles,
            "prop": "videoinfo",
            "viprop": "url|size|mime|dimensions|derivatives|extmetadata",
            "viextmetadatalanguage": "en",
        })
        for page in payload.get("query", {}).get("pages", []):
            if page.get("missing"):
                continue
            info = (page.get("videoinfo") or [{}])[0]
            ext = info.get("extmetadata", {})
            derivatives = info.get("derivatives", [])
            by_title[page["title"]] = {
                "source_title": page["title"],
                "source_page": "https://commons.wikimedia.org/wiki/" + urllib.parse.quote(page["title"].replace(" ", "_"), safe=":()_-"),
                "original_url": info.get("url", ""),
                "original_duration": info.get("duration"),
                "original_width": info.get("width"),
                "original_height": info.get("height"),
                "author": _meta(ext, "Artist"),
                "credit": _meta(ext, "Credit"),
                "license": _meta(ext, "LicenseShortName"),
                "license_url": _meta(ext, "LicenseUrl"),
                "description": _meta(ext, "ImageDescription"),
                "attribution_required": _meta(ext, "AttributionRequired"),
                "derivatives": derivatives,
            }
        time.sleep(0.25)
    return by_title


def choose_sources(metadata: dict[str, Any]) -> list[tuple[str, str]]:
    derivatives = metadata.get("derivatives", [])
    preferences = ("360p.mpeg4.mov", "480p.vp9.webm", "360p.vp9.webm", "240p.vp9.webm")
    candidates: list[tuple[str, str]] = []
    for key in preferences:
        match = next((item for item in derivatives if item.get("transcodekey") == key), None)
        if match and match.get("src"):
            candidates.append((str(match["src"]), key))
    original_url = str(metadata.get("original_url") or "")
    if original_url:
        candidates.append((original_url, "original"))
    if not candidates:
        raise RuntimeError("no downloadable source or derivative")
    return candidates


def run(command: list[str], timeout: int = 600) -> None:
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    if completed.returncode:
        raise RuntimeError((completed.stderr or completed.stdout)[-3000:])


def probe(path: Path) -> dict[str, Any]:
    completed = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration,size:stream=index,codec_type,codec_name,width,height,r_frame_rate", "-of", "json", str(path)],
        capture_output=True, text=True, timeout=60, check=True,
    )
    return json.loads(completed.stdout)


def validate_probe(path: Path, details: dict[str, Any]) -> None:
    """Reject empty/truncated files that ffprobe can open but cannot decode."""
    streams = details.get("streams") or []
    has_video = any(item.get("codec_type") == "video" for item in streams)
    duration = float((details.get("format") or {}).get("duration") or 0)
    if path.stat().st_size < 1024 or not has_video or duration < 1.0:
        raise RuntimeError(
            f"invalid media output: bytes={path.stat().st_size}, "
            f"has_video={has_video}, duration={duration}"
        )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_asset(asset: dict[str, Any], metadata: dict[str, Any], output: Path, overwrite: bool) -> dict[str, Any]:
    role_dir = output / "media" / ("references" if asset["role"] == "reference" else "materials")
    role_dir.mkdir(parents=True, exist_ok=True)
    path = role_dir / f"{asset['id']}.mp4"
    source_candidates = choose_sources(metadata)
    source_url, derivative = source_candidates[0]
    source_duration = float(metadata.get("original_duration") or 0)
    start = min(float(asset["start"]), max(0.0, source_duration - 2.0)) if source_duration else float(asset["start"])
    duration = min(float(asset["clip"]), max(2.0, source_duration - start)) if source_duration else float(asset["clip"])

    existing_is_valid = False
    if path.is_file() and path.stat().st_size >= 1024:
        try:
            validate_probe(path, probe(path))
            existing_is_valid = True
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
            existing_is_valid = False

    if overwrite or not existing_is_valid:
        # Keep progress output ASCII-only: the Windows console may use GBK and
        # fail before ffmpeg starts when a Commons title contains other scripts.
        print(f"[download] {asset['id']}", flush=True)
        last_error: Exception | None = None
        for candidate_url, candidate_key in source_candidates:
            source_url, derivative = candidate_url, candidate_key
            command = [
                "ffmpeg", "-y", "-v", "error", "-stats", "-user_agent", USER_AGENT,
                "-i", source_url, "-ss", str(start), "-t", str(duration),
                "-map", "0:v:0", "-map", "0:a?",
                "-vf", "scale=min(854\\,iw):-2", "-c:v", "libx264", "-preset", "veryfast",
                "-crf", "23", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "96k",
                "-movflags", "+faststart", str(path),
            ]
            for attempt in range(3):
                try:
                    run(command)
                    validate_probe(path, probe(path))
                    last_error = None
                    break
                except Exception as exc:
                    last_error = exc
                    # A derivative can exist in API metadata but be an empty
                    # container. Retrying cannot repair it; try another format.
                    if "invalid media output" in str(exc):
                        break
                    # Commons may temporarily rate-limit derivative downloads.
                    time.sleep(20 * (attempt + 1))
            if last_error is None:
                break
        if last_error:
            raise last_error

    details = probe(path)
    validate_probe(path, details)
    return {
        **{key: asset[key] for key in ("id", "role", "theme", "tags")},
        "path": str(path.resolve()),
        "relative_path": path.relative_to(output).as_posix(),
        "sha256": sha256(path),
        "bytes": path.stat().st_size,
        "clip_start_seconds": start,
        "clip_duration_seconds": duration,
        "selected_derivative": derivative,
        **{key: metadata.get(key, "") for key in (
            "source_title", "source_page", "author", "credit", "license", "license_url",
            "description", "attribution_required", "original_duration", "original_width", "original_height",
        )},
        "probe": details,
        "transformation": "Short excerpt transcoded to H.264/AAC MP4, max width 854 px.",
    }


def write_cases(output: Path, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    assets = {item["id"]: item for item in records}
    cases: list[dict[str, Any]] = []
    for case_id, topic, reference_id, material_ids in CASE_SPECS:
        case_dir = output / "cases" / case_id
        case_dir.mkdir(parents=True, exist_ok=True)
        materials = [
            {
                "id": material_id,
                "type": "video",
                "path": assets[material_id]["path"],
                "description": assets[material_id]["description"] or assets[material_id]["source_title"],
                "tags": assets[material_id]["tags"],
                "source_page": assets[material_id]["source_page"],
                "license": assets[material_id]["license"],
            }
            for material_id in material_ids
        ]
        materials_path = case_dir / "materials.json"
        materials_path.write_text(json.dumps(materials, ensure_ascii=False, indent=2), encoding="utf-8")
        case = {
            "case_id": case_id,
            "target_topic": topic,
            "reference_id": reference_id,
            "reference_video": assets[reference_id]["path"],
            "materials_json": str(materials_path.resolve()),
            "material_ids": material_ids,
            "material_count": len(material_ids),
            "target_duration": 30,
            "status": "ready",
        }
        (case_dir / "case.json").write_text(json.dumps(case, ensure_ascii=False, indent=2), encoding="utf-8")
        cases.append(case)
    return cases


def write_attribution(output: Path, records: list[dict[str, Any]]) -> None:
    lines = [
        "# Travel Vlog Batch v1 — Attribution",
        "",
        "All source media was fetched from Wikimedia Commons. Check each source page and license before redistribution.",
        "The local files are excerpts/transcodes for model and video-pipeline evaluation; they are not claimed to be viral-video benchmarks.",
        "",
    ]
    for item in records:
        lines.extend([
            f"## {item['id']} — {item['source_title']}", "",
            f"- Source: {item['source_page']}",
            f"- Author: {item['author'] or 'See source page'}",
            f"- Credit: {item['credit'] or 'See source page'}",
            f"- License: {item['license'] or 'See source page'}",
            f"- License URL: {item['license_url'] or 'See source page'}",
            f"- Local transformation: {item['transformation']}", "",
        ])
    (output / "ATTRIBUTION.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a 20-case open-licensed travel-video batch")
    parser.add_argument(
        "--output", type=Path,
        default=Path(__file__).resolve().parents[1] / "viral-structure-engine" / "data" / "datasets" / "travel_vlog_batch_v1",
    )
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--limit", type=int, default=0, help="Build only the first N assets for a smoke test")
    args = parser.parse_args()
    selected = ASSETS[:args.limit] if args.limit > 0 else ASSETS
    args.output.mkdir(parents=True, exist_ok=True)

    metadata_by_title = fetch_metadata(selected)
    missing = [item["title"] for item in selected if item["title"] not in metadata_by_title]
    if missing:
        raise RuntimeError(f"Wikimedia metadata missing for: {missing}")

    records: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    for asset in selected:
        metadata = metadata_by_title[asset["title"]]
        if not metadata.get("license"):
            failures.append({"id": asset["id"], "error": "missing explicit license metadata"})
            continue
        try:
            records.append(build_asset(asset, metadata, args.output, args.overwrite))
        except Exception as exc:
            failures.append({"id": asset["id"], "error": f"{type(exc).__name__}: {exc}"})

    manifest = {
        "schema_version": "1.0",
        "dataset_id": "travel_vlog_batch_v1",
        "purpose": "functional and Skill-lifecycle evaluation; not a virality benchmark",
        "source": "Wikimedia Commons",
        "source_policy": "https://commons.wikimedia.org/wiki/Commons:Reusing_content_outside_Wikimedia",
        "asset_count": len(records),
        "reference_count": sum(item["role"] == "reference" for item in records),
        "material_count": sum(item["role"] == "material" for item in records),
        "assets": records,
        "failures": failures,
    }
    (args.output / "asset_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    write_attribution(args.output, records)

    required_ids = {item for spec in CASE_SPECS for item in ([spec[2]] + spec[3])}
    available_ids = {item["id"] for item in records}
    cases = write_cases(args.output, records) if required_ids.issubset(available_ids) else []
    batch = {
        "schema_version": "1.0",
        "dataset_id": "travel_vlog_batch_v1",
        "case_count": len(cases),
        "cases": cases,
        "failures": failures,
    }
    (args.output / "batch_manifest.json").write_text(json.dumps(batch, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(args.output), "assets": len(records), "cases": len(cases), "failures": failures}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
