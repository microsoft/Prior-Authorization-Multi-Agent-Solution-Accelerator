import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    AZURE_FOUNDRY_API_KEY: str = os.getenv("AZURE_FOUNDRY_API_KEY", "")
    AZURE_FOUNDRY_ENDPOINT: str = os.getenv("AZURE_FOUNDRY_ENDPOINT", "")
    CLAUDE_MODEL: str = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")
    FRONTEND_ORIGIN: str = os.getenv("FRONTEND_ORIGIN", "http://localhost:3000")

    # Skills-based approach toggle (default: True)
    # When True, agents use SKILL.md files via MAF native skill discovery.
    # When False, agents use inline system prompt instructions.
    USE_SKILLS: bool = os.getenv("USE_SKILLS", "true").lower() in ("true", "1", "yes")

    # Healthcare MCP Server endpoints (from anthropics/healthcare)
    MCP_NPI_REGISTRY: str = os.getenv(
        "MCP_NPI_REGISTRY", "https://mcp.deepsense.ai/npi_registry/mcp"
    )
    MCP_ICD10_CODES: str = os.getenv(
        "MCP_ICD10_CODES", "https://mcp.deepsense.ai/icd10_codes/mcp"
    )
    MCP_CMS_COVERAGE: str = os.getenv(
        "MCP_CMS_COVERAGE", "https://mcp.deepsense.ai/cms_coverage/mcp"
    )
    MCP_PUBMED: str = os.getenv(
        "MCP_PUBMED", "https://pubmed.mcp.claude.com/mcp"
    )
    MCP_CLINICAL_TRIALS: str = os.getenv(
        "MCP_CLINICAL_TRIALS", "https://mcp.deepsense.ai/clinical_trials/mcp"
    )


settings = Settings()
