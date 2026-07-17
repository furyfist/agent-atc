"""Span/resource attribute key constants. See PROJECT_PLAN.md S6.

Single source of truth for attribute names so core, tools, the seeder, and
agent-runner can't drift into inconsistent naming.
"""

# agent.* - identity and provenance of the mission this span belongs to.
AGENT_ID = "agent.id"
AGENT_PERSONA = "agent.persona"
AGENT_TASK_ORIGIN_TS = "agent.task.origin_ts"
AGENT_MEMORY_COMPACTION_ID = "agent.memory.compaction_id"
AGENT_MEMORY_SUMMARY_EXCERPT = "agent.memory.summary_excerpt"

# atc.* - governance decision attributes.
ATC_ACTION_ID = "atc.action_id"
ATC_RISK_LEVEL = "atc.risk.level"
ATC_RISK_SCORE = "atc.risk.score"
ATC_RISK_REASONS = "atc.risk.reasons"
ATC_DECISION = "atc.decision"
ATC_DECISION_BY = "atc.decision.by"
ATC_RESOURCE_CLASS = "atc.resource.class"
ATC_RESOURCE_NAME = "atc.resource.name"
ATC_NOVEL_RESOURCE = "atc.novel_resource"
# Consequence signals (V2 - docs/PRODUCT_STRATEGY.md).
ATC_REVERSIBILITY = "atc.reversibility"  # REVERSIBLE | COMPENSABLE | IRREVERSIBLE
ATC_BLAST_RADIUS = "atc.blast_radius"  # pre-approval row-impact estimate
POLICY_VERSION = "policy.version"  # content hash of the rule set in force
POLICY_RULE_ID = "policy.rule_id"

# gen_ai.* - OTel GenAI semantic conventions, used on gen_ai.chat spans.
GEN_AI_SYSTEM = "gen_ai.system"
GEN_AI_REQUEST_MODEL = "gen_ai.request.model"
GEN_AI_USAGE_INPUT_TOKENS = "gen_ai.usage.input_tokens"
GEN_AI_USAGE_OUTPUT_TOKENS = "gen_ai.usage.output_tokens"

# Span names from the S6 tree (agent.mission -> agent.turn -> gen_ai.chat /
# mcp.tool.call -> atc.gate -> atc.risk_assessment / atc.interception /
# atc.approval_wait / atc.execution -> tool.{name}).
SPAN_AGENT_MISSION = "agent.mission"
SPAN_AGENT_TURN = "agent.turn"
SPAN_GEN_AI_CHAT = "gen_ai.chat"
SPAN_MCP_TOOL_CALL_PREFIX = "mcp.tool.call"
SPAN_ATC_GATE_PREFIX = "atc.gate"
SPAN_ATC_RISK_ASSESSMENT = "atc.risk_assessment"
SPAN_ATC_INTERCEPTION = "atc.interception"
SPAN_ATC_APPROVAL_WAIT = "atc.approval_wait"
SPAN_ATC_EXECUTION = "atc.execution"
SPAN_TOOL_PREFIX = "tool"
