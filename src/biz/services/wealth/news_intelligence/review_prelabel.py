"""Small v3 demo prelabeler. Suggestions are not gold labels or production scores."""
from __future__ import annotations

import math
from typing import Callable, Mapping

from .policy import build_label_candidates, event_type_hypothesis, topic_hypothesis
from .review_policy import REVIEW_FIELDS, SUBTOPICS, validate_prediction

PROMPT_VERSION = "news-review-nli-v3-demo-1"
NLI_REVISION = "MoritzLaurer/mDeBERTa-v3-base-mnli-xnli@8adb042d524ecd5c26d3e3ba0e3fbcf7e2d0864c"

# Conservative literal triggers; all are visible, versioned demo suggestions.
INDUSTRY_TRIGGERS = {
    "AGRICULTURE_FOOD": ("农业", "粮食", "食品", "养殖"),
    "EXTRACTION_RESOURCES": ("采矿", "煤矿", "矿产"),
    "ENERGY_UTILITIES": ("电力", "发电", "供水", "天然气", "石油"),
    "CHEMICALS": ("化工", "化肥"), "MATERIALS": ("钢铁", "有色金属", "新材料"),
    "INDUSTRIAL_EQUIPMENT": ("机械", "装备", "机器人"),
    "AUTOMOTIVE_TRANSPORT_EQUIPMENT": ("汽车", "造船", "飞机制造"),
    "ELECTRONICS_SEMICONDUCTORS": ("芯片", "半导体", "晶圆", "电子"),
    "IT_TELECOMMUNICATIONS": ("软件", "人工智能", "大模型", "通信", "数据中心"),
    "CONSUMER_RETAIL": ("零售", "消费品", "百货", "家电"),
    "PHARMA_HEALTHCARE": ("医药", "药品", "医疗", "医院"),
    "FINANCE": ("银行", "保险", "证券公司", "基金"),
    "REAL_ESTATE_CONSTRUCTION": ("房地产", "地产", "建筑", "住宅"),
    "TRANSPORT_LOGISTICS": ("物流", "航运", "铁路", "航空公司"),
    "CULTURE_MEDIA_ENTERTAINMENT": ("电影", "出版", "传媒", "游戏"),
    "EDUCATION_PROFESSIONAL_SERVICES": ("教育", "培训", "咨询服务"),
    "TOURISM_HOSPITALITY_LIFE_SERVICES": ("旅游", "餐饮", "酒店"),
}
INTEREST_TRIGGERS = {
    "MACRO": ("GDP", "CPI", "PPI", "PMI", "宏观经济"),
    "MONETARY": ("央行", "降准", "降息", "公开市场操作", "准备金"),
    "FISCAL": ("财政", "税收", "专项债"),
    "CAPITAL_REGULATION": ("证监会", "证券监管", "交易所", "退市"),
    "FINANCIAL_MARKETS": ("A股", "港股", "美股", "债券", "期货"),
    "AI": ("人工智能", "大模型", "生成式"),
    "SEMICONDUCTORS": ("半导体", "芯片", "晶圆", "光刻"),
    "COMPUTING_TELECOM": ("算力", "数据中心", "通信"),
    "SOFTWARE_SECURITY": ("软件", "网络安全", "云计算"),
    "ROBOTICS": ("机器人",), "NEW_ENERGY": ("新能源", "光伏", "储能"),
    "BIOMEDICAL": ("生物医药", "创新药", "临床试验"),
    "AEROSPACE": ("航天", "卫星", "火箭"),
    "COMPANY_RISK": ("违约", "破产", "退市风险", "流动性危机"),
    "TRADE_SANCTIONS": ("制裁", "出口管制", "关税", "国际贸易"),
}
SUBTOPIC_TRIGGERS = {
    "ECONOMY.ECONOMIC_CONDITIONS": ("统计", "GDP", "CPI", "PMI", "数据"),
    "ECONOMY.ECONOMIC_POLICY": ("政策", "央行", "降息", "监管", "财政"),
    "ECONOMY.MARKET_ACTIVITY": ("价格", "股价", "指数", "资金流", "期货"),
    "ECONOMY.BUSINESS_OPERATIONS": ("公司", "业绩", "利润", "订单", "并购"),
    "ECONOMY.INDUSTRY_STRUCTURE": ("产业链", "行业", "供需", "产能"),
    "ECONOMY.TRADE_RELATIONS": ("贸易", "跨境", "出口", "进口"),
    "SCIENCE.RESEARCH": ("研究", "实验", "科学发现"),
    "SCIENCE.TECHNOLOGY_DEVELOPMENT": ("研发", "技术", "发布", "突破", "应用"),
}


def _literal_matches(text: str, triggers: Mapping[str, tuple[str, ...]]) -> dict[str, str]:
    return {code: next(word for word in words if word in text)
            for code, words in triggers.items() if any(word in text for word in words)}


def build_demo_prediction(*, title: str, content: str,
                          infer: Callable[[str, tuple[str, ...]], tuple[float, ...]]) -> dict[str, object]:
    source = title + "\n" + content
    # Small bounded premise. The review UI still displays the complete original.
    premise = title[:80] + "\n" + content[:240]
    candidates = build_label_candidates(title, content)
    scores_by_axis = {}

    def best(axis, codes, hypotheses):
        if not codes:
            scores_by_axis[axis] = {}
            return None
        scores = infer(premise, tuple(hypotheses))
        if len(scores) != len(codes) or any(not math.isfinite(s) or not 0 <= s <= 1 for s in scores):
            raise ValueError("invalid/missing NLI scores; refusing fabricated predictions")
        scores_by_axis[axis] = dict(zip(codes, scores, strict=True))
        index = max(range(len(scores)), key=lambda i: scores[i])
        # Provisional demo threshold, not a calibrated accuracy claim.
        return codes[index] if scores[index] >= 0.5 else None

    topic = best("primary", candidates.primary_topics,
                 [topic_hypothesis(code) for code in candidates.primary_topics])
    paths = [code for code in _literal_matches(source, SUBTOPIC_TRIGGERS)
             if SUBTOPICS[code][0] == topic][:3]
    subtopic = best("subtopic", paths, [f"这条新闻主要报道{SUBTOPICS[code][1]}。" for code in paths])
    event = best("event", candidates.event_types,
                 [event_type_hypothesis(code) for code in candidates.event_types])
    industries = _literal_matches(source, INDUSTRY_TRIGGERS)
    interests = _literal_matches(source, INTEREST_TRIGGERS)
    values = {
        "classification_status": "CLASSIFIED" if topic else "UNRESOLVED",
        "topic_path": subtopic or topic, "secondary_topics": [],
        "industry_status": "SPECIFIC" if industries else "UNKNOWN",
        "industries": list(industries), "interest_tags": list(interests),
        "event_type_status": "CLASSIFIED" if event else "UNRESOLVED",
        "primary_event_type": event,
        # Do not invent a seven-dimensional production judgment from classification scores.
        "importance_tier": "UNKNOWN",
    }
    evidence = {field: {"source": "RULE", "quote": premise[:80] or content[:80]}
                for field in REVIEW_FIELDS}
    for field in ("classification_status", "topic_path", "event_type_status", "primary_event_type"):
        axis = "primary" if field in {"classification_status", "topic_path"} else "event"
        evidence[field] = {"source": "MODEL" if scores_by_axis.get(axis) else "RULE",
                           "quote": title[:80] or content[:80]}
    for field, matches in (("industries", industries), ("interest_tags", interests)):
        if matches:
            evidence[field]["quote"] = next(iter(matches.values()))
            evidence[field]["matched_quotes"] = matches
    prediction = {
        "status": "COMPLETE", "prompt_version": PROMPT_VERSION, "model_revision": NLI_REVISION,
        "values": values, "evidence": evidence, "nli_scores": scores_by_axis,
        "coverage": "TITLE_AND_LEAD_ONLY", "importance_status": "NOT_ASSESSED",
        "warnings": ["仅供表单演示；0.5为临时阈值；行业与关注标签是字面规则建议；重要度未评估。"],
    }
    return validate_prediction(prediction, source)
