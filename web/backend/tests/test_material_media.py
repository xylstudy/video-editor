from fastapi import HTTPException
from pathlib import Path
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine
from starlette.requests import Request
from uuid import uuid4

from db_models import Material, MaterialType, Project, User
from routers.materials import get_material_media


def _session_with_material():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    session = Session(engine)
    owner = User(username="material-owner", hashed_password="x")
    other = User(username="material-other", hashed_password="x")
    session.add_all([owner, other])
    session.commit()
    session.refresh(owner)
    session.refresh(other)
    project = Project(name="media-project", user_id=owner.id)
    session.add(project)
    session.commit()
    session.refresh(project)
    source = Path(__file__).parent / f"_material-media-{uuid4().hex}.mp4"
    source.write_bytes(b"0123456789")
    material = Material(
        project_id=project.id,
        type=MaterialType.VIDEO,
        filename=source.name,
        storage_path=str(source),
    )
    session.add(material)
    session.commit()
    session.refresh(material)
    return session, owner, other, material


def test_material_media_supports_range_for_owner():
    session, owner, _other, material = _session_with_material()
    request = Request({
        "type": "http",
        "method": "GET",
        "path": f"/api/materials/{material.id}/media",
        "headers": [(b"range", b"bytes=2-5")],
        "query_string": b"",
    })

    try:
        response = get_material_media(material.id, request, owner, session)

        assert response.status_code == 206
        assert response.headers["content-range"] == "bytes 2-5/10"
        assert response.headers["content-type"].startswith("video/mp4")
    finally:
        Path(material.storage_path).unlink(missing_ok=True)
        session.close()


def test_material_media_hides_foreign_material():
    session, _owner, other, material = _session_with_material()
    request = Request({
        "type": "http",
        "method": "GET",
        "path": f"/api/materials/{material.id}/media",
        "headers": [],
        "query_string": b"",
    })

    try:
        get_material_media(material.id, request, other, session)
        raise AssertionError("foreign material should not be readable")
    except HTTPException as exc:
        assert exc.status_code == 404
    finally:
        Path(material.storage_path).unlink(missing_ok=True)
        session.close()
