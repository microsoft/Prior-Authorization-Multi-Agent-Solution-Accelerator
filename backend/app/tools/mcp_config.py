"""MCP server configuration for healthcare MCP servers.

Provides pre-built mcp_servers dicts that can be passed directly to
ClaudeAgentOptions.mcp_servers. Claude CLI handles the MCP protocol,
tool discovery, and tool calls natively.

DeepSense MCP servers require User-Agent: claude-code/1.0, which is
passed via the McpHttpServerConfig.headers field.
"""

from app.config import settings

# DeepSense CloudFront routes on User-Agent; without this header
# the servers return a 301 redirect to the docs site instead of
# handling MCP protocol messages.
_HEADERS = {"User-Agent": "claude-code/1.0"}


# Individual server configs (McpHttpServerConfig TypedDicts)
NPI_SERVER = {"type": "http", "url": settings.MCP_NPI_REGISTRY, "headers": _HEADERS}
ICD10_SERVER = {"type": "http", "url": settings.MCP_ICD10_CODES, "headers": _HEADERS}
CMS_SERVER = {"type": "http", "url": settings.MCP_CMS_COVERAGE, "headers": _HEADERS}
PUBMED_SERVER = {"type": "http", "url": settings.MCP_PUBMED, "headers": _HEADERS}
TRIALS_SERVER = {"type": "http", "url": settings.MCP_CLINICAL_TRIALS, "headers": _HEADERS}


# Pre-built server groups for each agent role
CLINICAL_MCP_SERVERS = {
    "icd10-codes": ICD10_SERVER,
    "pubmed": PUBMED_SERVER,
    "clinical-trials": TRIALS_SERVER,
}

COVERAGE_MCP_SERVERS = {
    "npi-registry": NPI_SERVER,
    "cms-coverage": CMS_SERVER,
}

ALL_MCP_SERVERS = {
    "npi-registry": NPI_SERVER,
    "icd10-codes": ICD10_SERVER,
    "cms-coverage": CMS_SERVER,
    "pubmed": PUBMED_SERVER,
    "clinical-trials": TRIALS_SERVER,
}
