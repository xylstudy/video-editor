"""video-editing Skill — 跨任务复用的剪辑知识，渐进式披露加载。"""
from skills.router import SkillRouter, SkillReference, SkillPlan, SkillRouteDecision
from skills.registry import SkillDefinition, SkillRegistry
from skills.verifier import initialise_skill_trace, verify_skill_usage, attach_skill_outcomes
from skills.experience import ExperienceExtractor, ExperienceRepository, capture_run_experiences
from skills.mining import ExperienceNormalizer, IncrementalSkillMiner
from skills.candidates import CandidateGenerator, CandidateRepository, CandidateValidator
from skills.experiments import FixedTaskSet, ExperimentRepository, analyse_experiment, run_paired_experiment
from skills.lifecycle import PromotionPolicy, SkillLifecycleManager, RoutingWeightLearner

__all__ = [
    "SkillRouter", "SkillReference", "SkillPlan", "SkillRouteDecision",
    "SkillDefinition", "SkillRegistry",
    "initialise_skill_trace", "verify_skill_usage", "attach_skill_outcomes",
    "ExperienceExtractor", "ExperienceRepository", "capture_run_experiences",
    "ExperienceNormalizer", "IncrementalSkillMiner",
    "CandidateGenerator", "CandidateRepository", "CandidateValidator",
    "FixedTaskSet", "ExperimentRepository", "analyse_experiment", "run_paired_experiment",
    "PromotionPolicy", "SkillLifecycleManager", "RoutingWeightLearner",
]
