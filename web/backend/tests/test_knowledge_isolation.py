import json
import pytest
from fastapi import HTTPException
from starlette.requests import Request
from types import SimpleNamespace

from sqlmodel import Session, SQLModel, create_engine, select
from sqlalchemy.pool import StaticPool

from db_models import Gene, GeneStatus, KnowledgeOwnership, User
import knowledge_sync
import pipeline_runner
from routers import knowledge, stats


class FakeEntry:
    def __init__(self, entry_id: str, title: str):
        self.id = entry_id
        self.title = title
        self.type = SimpleNamespace(value="editing_technique")

    def to_dict(self):
        return {
            "id": self.id,
            "type": self.type.value,
            "title": self.title,
            "content": "content",
            "tags": [],
        }


class FakeStore:
    def __init__(self, entries):
        self.entries = entries

    def get_all_entries(self):
        return self.entries

    def get_entry(self, entry_id):
        return next((entry for entry in self.entries if entry.id == entry_id), None)

    def remove_entry(self, entry_id):
        self.entries = [entry for entry in self.entries if entry.id != entry_id]


def make_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def seed_users_and_ownership(session):
    users = [
        User(id=1, username="alice", hashed_password="x"),
        User(id=2, username="bob", hashed_password="x"),
        User(id=3, username="new-user", hashed_password="x"),
    ]
    session.add_all(users)
    session.add(KnowledgeOwnership(entry_id="k_u1_private", user_id=1))
    session.add(KnowledgeOwnership(entry_id="k_u2_private", user_id=2))
    session.commit()
    return users


def test_knowledge_scopes_separate_system_and_personal_entries(monkeypatch):
    session = make_session()
    alice, _, new_user = seed_users_and_ownership(session)
    store = FakeStore([
        FakeEntry("k_0", "system"),
        FakeEntry("k_u1_private", "alice private"),
        FakeEntry("k_u2_private", "bob private"),
    ])
    monkeypatch.setattr(knowledge, "_load_store", lambda: store)

    mine = knowledge.list_knowledge(scope="mine", current_user=alice, session=session)
    system = knowledge.list_knowledge(scope="system", current_user=alice, session=session)
    visible = knowledge.list_knowledge(scope="all", current_user=alice, session=session)
    new_user_mine = knowledge.list_knowledge(
        scope="mine", current_user=new_user, session=session
    )

    assert [(item["id"], item["source"]) for item in mine] == [
        ("k_u1_private", "user")
    ]
    assert [(item["id"], item["source"]) for item in system] == [
        ("k_0", "system")
    ]
    assert {item["id"] for item in visible} == {"k_0", "k_u1_private"}
    assert new_user_mine == []


def test_teaching_variants_respect_ownership_and_keep_source_clips(monkeypatch, tmp_path):
    session = make_session()
    alice, bob, _ = seed_users_and_ownership(session)
    monkeypatch.setattr(knowledge, "_load_store", lambda: FakeStore([FakeEntry("k_u1_private", "alice private")]))
    monkeypatch.setattr(knowledge, "DEMO_DIR", tmp_path)
    (tmp_path / "k_u1_private.mp4").write_bytes(b"example")
    (tmp_path / "k_u1_private.teaching.mp4").write_bytes(b"teaching")
    request = Request({"type": "http", "headers": [(b"range", b"bytes=0-2")]})
    for old_mode in ("personal-teaching-v1", "personal-footage-v2", "personal-effect-v3"):
        (tmp_path / "k_u1_private.teaching.json").write_text(json.dumps({"mode": old_mode, 'recipe': {'reference_recut': True}}))
        legacy = knowledge.list_knowledge(scope="mine", current_user=alice, session=session)
        assert legacy[0]["demos"] == [{"variant": "example", "label": "原片示例"}]
        assert not legacy[0]["has_teaching_demo"]
        with pytest.raises(HTTPException) as outdated:
            knowledge.get_knowledge_demo("k_u1_private", request, variant="teaching", current_user=alice, session=session)
        assert outdated.value.status_code == 404
    for suffix in ("teaching.json", "mp4.source.json"):
        (tmp_path / f"k_u1_private.{suffix}").write_text(json.dumps({"mode": "personal-effect-v3"}))
    entries = knowledge.list_knowledge(scope="mine", current_user=alice, session=session)
    assert [(demo['variant'], demo['label']) for demo in entries[0]["demos"]] == [('teaching', '效果示例'), ('example', '原片示例')]
    assert entries[0]["has_teaching_demo"]
    assert entries[0]['demos'][0]['version']
    request = Request({"type": "http", "headers": [(b"range", b"bytes=0-2")]})
    response = knowledge.get_knowledge_demo("k_u1_private", request, variant="teaching", current_user=alice, session=session)
    assert response.status_code == 206
    for variant in ("example", "teaching"):
        with pytest.raises(HTTPException) as denied:
            knowledge.get_knowledge_demo("k_u1_private", request, variant=variant, current_user=bob, session=session)
        assert denied.value.status_code == 404
    knowledge.delete_knowledge("k_u1_private", current_user=alice, session=session)
    assert list(tmp_path.iterdir()) == []


def test_pending_effects_do_not_expose_old_reference_teaching_files(monkeypatch, tmp_path):
    session = make_session()
    alice, _, _ = seed_users_and_ownership(session)
    monkeypatch.setattr(knowledge, '_load_store', lambda: FakeStore([FakeEntry('k_u1_private', 'pending')]))
    monkeypatch.setattr(knowledge, 'DEMO_DIR', tmp_path)
    (tmp_path / 'k_u1_private.mp4').write_bytes(b'reference')
    (tmp_path / 'k_u1_private.teaching.mp4').write_bytes(b'old duplicate')
    (tmp_path / 'k_u1_private.teaching.json').write_text(json.dumps({'mode': 'personal-effect-v4', 'status': 'pending', 'reason': '缺少独立素材'}))
    entry = knowledge.list_knowledge(scope='mine', current_user=alice, session=session)[0]
    assert not entry['has_teaching_demo'] and entry['demo_pending_reason'] == '缺少独立素材'
    assert entry['demos'] == [{'variant': 'example', 'label': '原片示例'}]


def test_dashboard_count_excludes_system_knowledge(monkeypatch, tmp_path):
    session = make_session()
    alice, _, new_user = seed_users_and_ownership(session)
    knowledge_db = tmp_path / "knowledge.json"
    knowledge_db.write_text(
        json.dumps([
            {"id": "k_0"},
            {"id": "k_u1_private"},
            {"id": "k_u2_private"},
        ]),
        encoding="utf-8",
    )
    monkeypatch.setattr(stats, "VSE_KNOWLEDGE_DB", knowledge_db)

    assert stats._personal_knowledge_count(session, alice.id) == 1
    assert stats._personal_knowledge_count(session, new_user.id) == 0


def test_pipeline_context_contains_only_current_users_knowledge(tmp_path):
    session = make_session()
    alice, _, new_user = seed_users_and_ownership(session)
    knowledge_db = tmp_path / "knowledge.json"
    knowledge_db.write_text(
        json.dumps([
            {"id": "k_0", "title": "system"},
            {"id": "k_u1_private", "title": "alice private"},
            {"id": "k_u2_private", "title": "bob private"},
        ]),
        encoding="utf-8",
    )

    assert pipeline_runner._personal_knowledge_entries(
        session, alice.id, knowledge_db
    ) == [{"id": "k_u1_private", "title": "alice private"}]
    assert pipeline_runner._personal_knowledge_entries(
        session, new_user.id, knowledge_db
    ) == []


def test_gene_knowledge_extraction_is_idempotent_and_user_owned(tmp_path, monkeypatch):
    from config import settings

    session = make_session()
    user = User(username="knowledge-user", hashed_password="x")
    session.add(user)
    session.commit()
    session.refresh(user)
    report_path = tmp_path / "gene" / "report.json"
    report_path.parent.mkdir()
    report_path.write_text(json.dumps({
        "duration": 15,
        "shot_count": 1,
        "vlog_meta": {
            "structure_type": "递进型",
            "narrative_type": "timeline",
            "overall_emotion": "期待",
            "hook_method": "视觉冲击",
        },
        "raw_shot_analyses": [{"emotion": "期待"}],
        "raw_structure_analysis": {"script_structure": [{"index": 0}]},
    }, ensure_ascii=False), encoding="utf-8")
    gene = Gene(
        user_id=user.id,
        title="city gene",
        source_filename="city.mp4",
        status=GeneStatus.DONE,
        report_path=str(report_path),
        duration=15,
    )
    session.add(gene)
    session.commit()
    session.refresh(gene)

    monkeypatch.setattr(knowledge_sync, "engine", session.get_bind())
    monkeypatch.setattr(settings, "KNOWLEDGE_DB_DIR", tmp_path / "knowledge_db")
    monkeypatch.setattr(
        knowledge_sync,
        "_render_demo_entries",
        lambda entries: {
            "demos_rendered": len(entries),
            "demos_existing": 0,
            "demos_available": len(entries),
            "demo_failures": [],
        },
    )
    knowledge_sync._gene_locks.clear()

    async def run_twice():
        first = await knowledge_sync.extract_gene_knowledge(gene.id, user.id)
        second = await knowledge_sync.extract_gene_knowledge(gene.id, user.id)
        return first, second

    first, second = __import__("asyncio").run(run_twice())

    ownership = session.exec(
        select(KnowledgeOwnership).where(KnowledgeOwnership.user_id == user.id)
    ).all()
    persisted = json.loads((settings.KNOWLEDGE_DB_DIR / "knowledge.json").read_text(encoding="utf-8"))
    assert first["added"] == 5
    assert second["added"] == 0
    assert second["existing"] == 5
    assert second["skipped"] is True
    assert second["demos_available"] == 5
    assert len(ownership) == 5
    assert len(persisted) == 5
    assert persisted[0]["derivation"]["source_gene_id"] == gene.id
    assert persisted[0]["derivation"]["source_user_id"] == user.id
