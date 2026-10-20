from render_knowledge_demos import demo_spec, select_demo_entries


def test_builtin_batch_does_not_replace_personal_source_clips():
    entries = [
        {"id": "k_0"},
        {"id": "k_51"},
        {"id": "k_u3_personal"},
        {"id": "k_u3_8f2d_effect_contract"},
    ]
    assert select_demo_entries(entries, built_in=True) == entries[:2]
    assert select_demo_entries(entries, only="k_51", built_in=True) == [entries[1]]
    assert select_demo_entries(entries, only="k_u3_personal") == [entries[2]]
    assert select_demo_entries(entries, only="k_u3_personal", built_in=True) == []


def test_personal_knowledge_types_use_matching_teaching_demos():
    assert demo_spec({"type": "structure_template", "structured_data": {}}) == (
        "emotion_arc",
        "structure_arc",
    )
    assert demo_spec({"type": "hook_technique", "structured_data": {}}) == (
        "montage",
        "hook",
    )
    assert demo_spec({"type": "rhythm_pattern", "structured_data": {}}) == (
        "beat",
        "beat",
    )
    assert demo_spec({"type": "emotion_design", "structured_data": {}}) == (
        "emotion_arc",
        "emotion_arc",
    )
    assert demo_spec({"type": "packaging_style", "structured_data": {}}) == (
        "packaging",
        "douyin_travel_fast",
    )
