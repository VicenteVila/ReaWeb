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
from tools.domain.meta_editor import EditSkill, ReviewHarness
from tools.domain.bundle_analyzer import AnalyzeProject
from tools.domain.deployer import DeployPreview, GitSnapshot


def build_domain_registry(llm, archetype: str = "", task: str = "", rules: str = "", stack: str = "") -> ToolRegistry:
    from tools.domain.evaluator import extract_requirements

    requirements = extract_requirements(task)
    registry = ToolRegistry(
        [
            InspectArchetype(),
            FetchUrl(),
            FetchReadme(task=task),
            GenerateCandidate(llm=llm, archetype=archetype, task=task, rules=rules, stack=stack, requirements=requirements),
            AuditPage(requirements=requirements, task=task),
            AnalyzeProject(),
            UpdateLessons(),
            SelectFinal(),
            EditSkill(),
            ReviewHarness(),
            DeployPreview(),
            GitSnapshot(),
        ]
    )
    return registry