"""Versioned v3 review contract; never reinterpret frozen v2 annotations."""
from __future__ import annotations

from copy import deepcopy
from typing import Mapping

from .policy import EVENT_TYPES, PRIMARY_TOPIC_NAMES

REVIEW_SCHEMA_VERSION = "news-intelligence-review-v3"
REVIEW_TAXONOMY_VERSION = "news-taxonomy-v3-m1-candidate-1"
INDUSTRY_VERSION = "news-industry-v1-m1-candidate-1"
INTEREST_VERSION = "news-interest-v1-m1-candidate-1"

# A path has exactly one parent. Parent-only options deliberately remain valid.
SUBTOPICS = {
    "ECONOMY.ECONOMIC_CONDITIONS": ("ECONOMY_BUSINESS_FINANCE", "经济运行与统计"),
    "ECONOMY.ECONOMIC_POLICY": ("ECONOMY_BUSINESS_FINANCE", "经济政策与制度"),
    "ECONOMY.MARKET_ACTIVITY": ("ECONOMY_BUSINESS_FINANCE", "市场交易与价格"),
    "ECONOMY.BUSINESS_OPERATIONS": ("ECONOMY_BUSINESS_FINANCE", "公司与机构经营"),
    "ECONOMY.INDUSTRY_STRUCTURE": ("ECONOMY_BUSINESS_FINANCE", "行业与产业链运行"),
    "ECONOMY.TRADE_RELATIONS": ("ECONOMY_BUSINESS_FINANCE", "贸易与跨境商业"),
    "SCIENCE.RESEARCH": ("SCIENCE_TECHNOLOGY", "科学研究与发现"),
    "SCIENCE.TECHNOLOGY_DEVELOPMENT": ("SCIENCE_TECHNOLOGY", "技术研发与应用"),
}
INDUSTRIES = {
    "AGRICULTURE_FOOD": "农业与食品",
    "EXTRACTION_RESOURCES": "采掘与资源",
    "ENERGY_UTILITIES": "能源与公用事业",
    "CHEMICALS": "基础化工",
    "MATERIALS": "材料",
    "INDUSTRIAL_EQUIPMENT": "工业与装备",
    "AUTOMOTIVE_TRANSPORT_EQUIPMENT": "汽车与交通设备",
    "ELECTRONICS_SEMICONDUCTORS": "电子与半导体",
    "IT_TELECOMMUNICATIONS": "信息技术与通信",
    "CONSUMER_RETAIL": "消费品与零售",
    "PHARMA_HEALTHCARE": "医药与医疗",
    "FINANCE": "金融",
    "REAL_ESTATE_CONSTRUCTION": "房地产与建筑",
    "TRANSPORT_LOGISTICS": "运输与物流",
    "CULTURE_MEDIA_ENTERTAINMENT": "文化传媒与娱乐",
    "EDUCATION_PROFESSIONAL_SERVICES": "教育与专业服务",
    "TOURISM_HOSPITALITY_LIFE_SERVICES": "旅游餐饮与生活服务",
}
INTERESTS = dict(zip(
    ("MACRO", "MONETARY", "FISCAL", "CAPITAL_REGULATION", "FINANCIAL_MARKETS",
     "AI", "SEMICONDUCTORS", "COMPUTING_TELECOM", "SOFTWARE_SECURITY", "ROBOTICS",
     "NEW_ENERGY", "BIOMEDICAL", "AEROSPACE", "COMPANY_RISK", "TRADE_SANCTIONS"),
    ("宏观经济", "货币政策", "财政政策", "资本市场监管", "金融市场", "人工智能",
     "半导体", "算力与通信", "软件与网络安全", "机器人", "新能源技术", "生物医疗科技",
     "航空航天", "重大公司风险", "国际贸易与制裁"), strict=True,
))
REVIEW_FIELDS = (
    "classification_status", "topic_path", "secondary_topics", "industry_status", "industries",
    "interest_tags", "event_type_status", "primary_event_type", "importance_tier",
)
BLIND_ROLES = {"BLIND_VALIDATION", "BLIND_REPEAT"}
ASSISTED_ROLES = {"TUTORIAL", "ASSISTED_CALIBRATION"}
ISSUE_REASONS = {"SOURCE_INSUFFICIENT", "LABEL_GAP", "DEFINITION_CONFLICT", "MODEL_INVALID"}


def topic_options() -> dict[str, str]:
    return {
        **{code: f"{name}（仅一级）" for code, name in PRIMARY_TOPIC_NAMES.items()},
        **{code: f"{PRIMARY_TOPIC_NAMES[parent]} → {name}"
           for code, (parent, name) in SUBTOPICS.items()},
    }


def topic_parent(code: str) -> str:
    if code in PRIMARY_TOPIC_NAMES:
        return code
    if code in SUBTOPICS:
        return SUBTOPICS[code][0]
    raise ValueError(f"invalid v3 topic path: {code}")


def validate_values(values: Mapping[str, object]) -> dict[str, object]:
    if set(values) != set(REVIEW_FIELDS):
        raise ValueError("review values must contain exactly the v3 review fields")
    result = deepcopy(dict(values))
    status = result["classification_status"]
    if status not in {"CLASSIFIED", "UNRESOLVED", "AMBIGUOUS", "NOT_NEWS", "MIXED_CONTENT", "INVALID_CONTENT"}:
        raise ValueError("invalid classification_status")
    path = result["topic_path"]
    if status == "CLASSIFIED" and not isinstance(path, str):
        raise ValueError("topic_path is required")
    if path is not None and not isinstance(path, str):
        raise ValueError("invalid topic_path")
    parent = topic_parent(path) if path is not None else None
    secondary = _codes(result["secondary_topics"], topic_options(), "secondary_topics", 2)
    if parent is None and secondary:
        raise ValueError("secondary topics require a main topic")
    for code in secondary:
        other_parent = topic_parent(code)
        if code == path or (other_parent == parent and (code == parent or path == parent)):
            raise ValueError("main and secondary topics cannot repeat or contain one another")
    industry_status = result["industry_status"]
    if industry_status not in {"SPECIFIC", "CROSS_INDUSTRY", "NONE", "UNKNOWN"}:
        raise ValueError("invalid industry_status")
    industries = _codes(result["industries"], INDUSTRIES, "industries", len(INDUSTRIES))
    if (industry_status == "SPECIFIC" and not industries) or (
        industry_status in {"NONE", "UNKNOWN"} and industries
    ):
        raise ValueError("industry status contradicts selected industries")
    _codes(result["interest_tags"], INTERESTS, "interest_tags", len(INTERESTS))
    event_status, event = result["event_type_status"], result["primary_event_type"]
    if event_status not in {"CLASSIFIED", "NOT_APPLICABLE", "UNRESOLVED"}:
        raise ValueError("invalid event_type_status")
    if (event_status == "CLASSIFIED" and event not in EVENT_TYPES) or (
        event_status != "CLASSIFIED" and event is not None
    ):
        raise ValueError("event status contradicts primary_event_type")
    if result["importance_tier"] not in {"HIGH", "MEDIUM", "LOW", "UNKNOWN"}:
        raise ValueError("invalid importance_tier")
    return result


def _codes(value, allowed, name, limit):
    if not isinstance(value, list) or not all(isinstance(code, str) for code in value):
        raise ValueError(f"{name} must be a list of codes")
    if len(value) > limit or len(set(value)) != len(value) or any(code not in allowed for code in value):
        raise ValueError(f"invalid {name}")
    return value


def validate_prediction(prediction: Mapping[str, object], source_text: str) -> dict[str, object]:
    if prediction.get("status") != "COMPLETE":
        raise ValueError("only a complete prediction can be accepted")
    if not prediction.get("prompt_version") or not prediction.get("model_revision"):
        raise ValueError("prediction requires prompt_version and model_revision")
    values, evidence = prediction.get("values"), prediction.get("evidence")
    if not isinstance(values, Mapping) or not isinstance(evidence, Mapping):
        raise ValueError("prediction requires values and evidence")
    validated = validate_values(values)
    for field in REVIEW_FIELDS:
        entry = evidence.get(field)
        if not isinstance(entry, Mapping) or entry.get("source") not in {"RULE", "MODEL"}:
            raise ValueError(f"missing evidence provenance for {field}")
        quote = entry.get("quote")
        if not isinstance(quote, str) or not quote.strip() or quote not in source_text:
            raise ValueError(f"evidence for {field} is not in the original text")
    return {**deepcopy(dict(prediction)), "values": validated}


def resolve_review(*, response: Mapping[str, object], prediction: Mapping[str, object] | None,
                   role: str, source_text: str) -> dict[str, object]:
    if role not in BLIND_ROLES | ASSISTED_ROLES:
        raise ValueError("invalid evaluation role")
    action = response.get("review_action")
    edits = {field: deepcopy(response[field]) for field in REVIEW_FIELDS if field in response}
    original = deepcopy(dict(response))
    base = None
    if role in BLIND_ROLES:
        if prediction is not None or action not in {"LABEL", "UNRESOLVED"}:
            raise ValueError("blind review cannot expose or accept predictions")
    elif action != "UNRESOLVED":
        if prediction is None:
            raise ValueError("assisted review requires a prediction")
        base = validate_prediction(prediction, source_text)["values"]
    if action == "UNRESOLVED":
        if response.get("issue_reason") not in ISSUE_REASONS:
            raise ValueError("unresolved review requires an issue reason")
        return {"machine_prediction": deepcopy(prediction), "human_response": original,
                "final_values": None, "changed_fields": [], "status": "UNRESOLVED"}
    if action == "ACCEPT" and not edits and base is not None:
        final = deepcopy(base)
    elif action == "EDIT" and base is not None:
        final = validate_values({**base, **edits})
        if final == base:
            raise ValueError("EDIT requires at least one changed field")
    elif action == "LABEL" and role in BLIND_ROLES:
        final = validate_values(edits)
    else:
        raise ValueError("invalid review action or contradictory edits")
    parent = topic_parent(final["topic_path"]) if final["topic_path"] is not None else None
    return {"machine_prediction": deepcopy(prediction), "human_response": original,
            "final_values": {**final, "primary_topic": parent,
                             "primary_subtopic": final["topic_path"] if final["topic_path"] != parent else None},
            "changed_fields": [field for field in REVIEW_FIELDS if base is not None and base[field] != final[field]],
            "status": "REVIEWED"}
