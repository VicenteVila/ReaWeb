from tools.base import ToolRegistry
from tools.domain.web_generator import (
    FetchUrl,
    GenerateCandidate,
    AuditPage,
    UpdateLessons,
    SelectFinal,
    InspectArchetype,
)
from tools.domain.readme_fetcher import FetchReadme
from tools.domain.repo_topics import FetchRepoTopics
from tools.domain.meta_editor import EditSkill, ReviewHarness
from tools.domain.bundle_analyzer import AnalyzeProject
from tools.domain.deployer import DeployPreview, GitSnapshot
from tools.domain.visual_critic import AuditVisual
from tools.domain.truth_audit import AuditTruth


def build_domain_registry(llm, archetype: str = "", task: str = "", rules: str = "", stack: str = "") -> ToolRegistry:
    from tools.domain.evaluator import extract_requirements

    requirements = extract_requirements(task)
    registry = ToolRegistry(
        [
            InspectArchetype(),
            FetchUrl(),
            FetchReadme(task=task),
            FetchRepoTopics(llm=llm, task=task),
            GenerateCandidate(llm=llm, archetype=archetype, task=task, rules=rules, stack=stack, requirements=requirements),
            AuditPage(requirements=requirements, task=task),
            AnalyzeProject(),
            AuditVisual(llm=llm),
            AuditTruth(llm=llm, task=task),
            UpdateLessons(),
            SelectFinal(),
            EditSkill(),
            ReviewHarness(),
            DeployPreview(),
            GitSnapshot(),
        ]
    )
    return registry