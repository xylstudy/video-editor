import json
from pathlib import Path
from uuid import uuid4

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from db_models import Material, MaterialType, Project, Task, TaskStatus, TaskType, User
from routers.works import list_works


def test_list_works_includes_task_reference_video():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    session = Session(engine)
    test_root = Path(__file__).parent / f"_works-reference-{uuid4().hex}"
    reference_path = test_root / "reference.mp4"
    output_path = test_root / "output" / "final_video.mp4"
    report_path = test_root / "analysis" / "reference_report.json"

    try:
        output_path.parent.mkdir(parents=True)
        report_path.parent.mkdir(parents=True)
        reference_path.write_bytes(b"reference")
        output_path.write_bytes(b"result")
        report_path.write_text(
            json.dumps({"source_path": str(reference_path)}),
            encoding="utf-8",
        )

        user = User(username="works-owner", hashed_password="x")
        session.add(user)
        session.commit()
        session.refresh(user)
        project = Project(name="reference-work", user_id=user.id)
        session.add(project)
        session.commit()
        session.refresh(project)

        wrong_reference = Material(
            project_id=project.id,
            type=MaterialType.VIDEO,
            filename="current-reference.mp4",
            storage_path=str(test_root / "current-reference.mp4"),
        )
        wrong_reference.set_metadata({"role": "reference"})
        used_reference = Material(
            project_id=project.id,
            type=MaterialType.VIDEO,
            filename=reference_path.name,
            storage_path=str(reference_path),
        )
        session.add_all([wrong_reference, used_reference])
        session.commit()
        session.refresh(used_reference)

        task = Task(
            project_id=project.id,
            type=TaskType.END_TO_END,
            status=TaskStatus.SUCCESS,
            result_path=str(output_path),
        )
        session.add(task)
        session.commit()
        session.refresh(task)

        works = list_works(user, session)

        assert len(works) == 1
        assert works[0]["reference_material_id"] == used_reference.id
        assert works[0]["reference_filename"] == "reference.mp4"
    finally:
        session.close()
        for path in (report_path, output_path, reference_path):
            path.unlink(missing_ok=True)
        for directory in (report_path.parent, output_path.parent, test_root):
            directory.rmdir()
