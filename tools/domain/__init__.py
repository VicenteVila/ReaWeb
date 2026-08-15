from tools.base import ToolRegistry
from tools.domain.web_generator import (
    GenerateCandidate,
    AuditPage,
    UpdateLessons,
    SelectFinal,
    InspectArchetype,
)
from tools.domain.meta_editor import EditSkill, ReviewHarness
from tools.domain.bundle_analyzer import AnalyzeProject
from tools.domain.deployer import DeployPreview, GitSnapshot


def build_domain_registry(llm, archetype: str = "", task: str = "", rules: str = "", stack: str = "") -> ToolRegistry:
    registry = ToolRegistry(
        [
            InspectArchetype(),
            GenerateCandidate(llm=llm, archetype=archetype, task=task, rules=rules, stack=stack),
            AuditPage(),
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