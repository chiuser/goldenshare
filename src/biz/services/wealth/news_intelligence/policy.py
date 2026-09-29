from __future__ import annotations

from dataclasses import dataclass

from .contracts import LabelCandidates


TIMEZONE = "Asia/Shanghai"
SCHEDULE_HOURS = (8, 12, 16, 20, 22)
TAXONOMY_VERSION = "news-taxonomy-v2-m1-candidate-1"
SCORING_VERSION = "news-score-v1-m1-candidate-1"
SUMMARY_VERSION = "news-summary-v1-m1-candidate-1"
MODEL_POLICY_VERSION = "news-model-v1-m1-candidate-1"

EMBEDDING_BATCH_SIZE = 1
EMBEDDING_MAX_TOKENS = 512
EMBEDDING_REPRESENTATIVE_TOKENS = 128
NLI_BATCH_SIZE = 16
NLI_MAX_TOKENS = 512
QWEN_THREADS = 4
QWEN_PARALLEL = 1
QWEN_CONTEXT_TOKENS = 2048
DEEP_ANALYSIS_LIMIT = 30
SUMMARY_MIN_CHARS = 800
SUMMARY_CHUNK_CHARS = 12_000
MAX_PRIMARY_TOPIC_CANDIDATES = 4
MAX_EVENT_TYPE_CANDIDATES = 6
DEBUG_TOP_N = 30
DELIVERY_TOP_N = 15

PRIMARY_TOPICS = (
    "DISASTER_ACCIDENT_EMERGENCY",
    "HUMAN_INTEREST",
    "POLITICS",
    "EDUCATION",
    "CRIME_LAW_JUSTICE",
    "ECONOMY_BUSINESS_FINANCE",
    "CONFLICT_WAR_PEACE",
    "ARTS_CULTURE_ENTERTAINMENT_MEDIA",
    "LABOUR",
    "WEATHER",
    "RELIGION",
    "SOCIETY",
    "HEALTH",
    "ENVIRONMENT",
    "LIFESTYLE_LEISURE",
    "SCIENCE_TECHNOLOGY",
    "SPORT",
)

FOCUSED_SUBTOPICS = (
    "ECONOMY.MACRO_ECONOMY",
    "ECONOMY.MONETARY_POLICY",
    "ECONOMY.FISCAL_POLICY",
    "ECONOMY.FINANCIAL_MARKETS",
    "ECONOMY.CAPITAL_MARKET_REGULATION",
    "ECONOMY.FINANCIAL_INSTITUTIONS",
    "ECONOMY.CORPORATE_BUSINESS",
    "ECONOMY.INDUSTRY_DEVELOPMENT",
    "ECONOMY.INTERNATIONAL_TRADE",
    "ECONOMY.COMMODITY_ENERGY",
    "ECONOMY.REAL_ESTATE",
    "ECONOMY.FX_CROSS_BORDER_CAPITAL",
    "TECH.ARTIFICIAL_INTELLIGENCE",
    "TECH.SEMICONDUCTOR",
    "TECH.SOFTWARE_CLOUD_NETWORK",
    "TECH.COMPUTING_TELECOM",
    "TECH.ROBOTICS_MANUFACTURING",
    "TECH.BIOTECH_MEDTECH",
    "TECH.NEW_ENERGY_MATERIALS",
    "TECH.AEROSPACE",
    "TECH.RESEARCH_INNOVATION",
    "POLITICS.GOVERNMENT_GOVERNANCE",
    "POLITICS.PUBLIC_POLICY",
    "POLITICS.LEGISLATION",
    "POLITICS.DOMESTIC_POLITICS",
    "POLITICS.INTERNATIONAL_RELATIONS",
    "POLITICS.REGIONAL_DEVELOPMENT",
    "CONFLICT.GEOPOLITICAL_CONFLICT",
    "CONFLICT.ARMED_CONFLICT",
    "CONFLICT.SANCTIONS_COUNTERMEASURES",
    "CONFLICT.DIPLOMATIC_CONFLICT",
    "CONFLICT.PEACE_PROCESS",
    "CONFLICT.CIVIL_UNREST",
)

FOCUSED_SUBTOPIC_NAMES = {
    "ECONOMY.MACRO_ECONOMY": "宏观经济",
    "ECONOMY.MONETARY_POLICY": "货币政策",
    "ECONOMY.FISCAL_POLICY": "财政政策",
    "ECONOMY.FINANCIAL_MARKETS": "金融市场",
    "ECONOMY.CAPITAL_MARKET_REGULATION": "资本市场制度与监管",
    "ECONOMY.FINANCIAL_INSTITUTIONS": "金融机构业务",
    "ECONOMY.CORPORATE_BUSINESS": "公司经营与商业活动",
    "ECONOMY.INDUSTRY_DEVELOPMENT": "产业与行业发展",
    "ECONOMY.INTERNATIONAL_TRADE": "国际贸易",
    "ECONOMY.COMMODITY_ENERGY": "商品、能源与资源市场",
    "ECONOMY.REAL_ESTATE": "房地产",
    "ECONOMY.FX_CROSS_BORDER_CAPITAL": "汇率与跨境资金",
    "TECH.ARTIFICIAL_INTELLIGENCE": "人工智能",
    "TECH.SEMICONDUCTOR": "半导体与芯片",
    "TECH.SOFTWARE_CLOUD_NETWORK": "软件、云与网络",
    "TECH.COMPUTING_TELECOM": "算力、数据中心与通信",
    "TECH.ROBOTICS_MANUFACTURING": "机器人与智能制造",
    "TECH.BIOTECH_MEDTECH": "生物与医疗科技",
    "TECH.NEW_ENERGY_MATERIALS": "新能源技术与新材料",
    "TECH.AEROSPACE": "航空航天",
    "TECH.RESEARCH_INNOVATION": "科研与创新",
    "POLITICS.GOVERNMENT_GOVERNANCE": "政府治理",
    "POLITICS.PUBLIC_POLICY": "公共政策",
    "POLITICS.LEGISLATION": "立法与法规",
    "POLITICS.DOMESTIC_POLITICS": "国内政治",
    "POLITICS.INTERNATIONAL_RELATIONS": "国际关系",
    "POLITICS.REGIONAL_DEVELOPMENT": "区域发展政策",
    "CONFLICT.GEOPOLITICAL_CONFLICT": "地缘政治冲突",
    "CONFLICT.ARMED_CONFLICT": "战争与军事行动",
    "CONFLICT.SANCTIONS_COUNTERMEASURES": "制裁与反制",
    "CONFLICT.DIPLOMATIC_CONFLICT": "外交冲突",
    "CONFLICT.PEACE_PROCESS": "和平进程",
    "CONFLICT.CIVIL_UNREST": "社会动荡",
}

EVENT_TYPES = (
    "POLICY_RELEASE",
    "POLICY_ADJUSTMENT",
    "LAW_REGULATION_RELEASE",
    "MACRO_DATA_RELEASE",
    "EARNINGS_GUIDANCE",
    "CORPORATE_FINANCE",
    "MERGER_ACQUISITION_RESTRUCTURING",
    "CONTRACT_PROJECT_INVESTMENT",
    "PRODUCTION_OPERATION_CHANGE",
    "GOVERNANCE_PERSONNEL_CHANGE",
    "INVESTIGATION_PENALTY_LITIGATION",
    "DEFAULT_DISTRESS",
    "MARKET_PRICE_MOVE",
    "CAPITAL_FLOW_CHANGE",
    "PRODUCT_TECH_RELEASE",
    "ACCIDENT_DISASTER",
    "DIPLOMATIC_ACTION",
    "SANCTION_TRADE_CONTROL",
    "ARMED_CONFLICT_CHANGE",
    "SPEECH_STATEMENT",
    "FORECAST_OPINION",
    "RUMOR_UNCONFIRMED",
)

PRIMARY_TOPIC_NAMES = {
    "DISASTER_ACCIDENT_EMERGENCY": "灾害、事故与紧急事件",
    "HUMAN_INTEREST": "人物与人情故事",
    "POLITICS": "政治与政府治理",
    "EDUCATION": "教育",
    "CRIME_LAW_JUSTICE": "犯罪、法律与司法",
    "ECONOMY_BUSINESS_FINANCE": "经济、商业与金融",
    "CONFLICT_WAR_PEACE": "冲突、战争与和平",
    "ARTS_CULTURE_ENTERTAINMENT_MEDIA": "艺术、文化、娱乐与媒体",
    "LABOUR": "劳动与就业",
    "WEATHER": "天气",
    "RELIGION": "宗教",
    "SOCIETY": "社会",
    "HEALTH": "健康与医疗",
    "ENVIRONMENT": "环境与生态",
    "LIFESTYLE_LEISURE": "生活方式与休闲",
    "SCIENCE_TECHNOLOGY": "科学与技术",
    "SPORT": "体育",
}

EVENT_TYPE_NAMES = {
    "POLICY_RELEASE": "政策首次发布",
    "POLICY_ADJUSTMENT": "政策调整与执行",
    "LAW_REGULATION_RELEASE": "法律或监管规则发布修订",
    "MACRO_DATA_RELEASE": "宏观或行业数据发布",
    "EARNINGS_GUIDANCE": "财报或业绩指引",
    "CORPORATE_FINANCE": "公司融资或股东回报",
    "MERGER_ACQUISITION_RESTRUCTURING": "并购或重大资产重组",
    "CONTRACT_PROJECT_INVESTMENT": "订单、项目或投资",
    "PRODUCTION_OPERATION_CHANGE": "生产经营变化",
    "GOVERNANCE_PERSONNEL_CHANGE": "公司治理或人事变化",
    "INVESTIGATION_PENALTY_LITIGATION": "调查、处罚或诉讼",
    "DEFAULT_DISTRESS": "违约或财务困境",
    "MARKET_PRICE_MOVE": "市场价格显著异动",
    "CAPITAL_FLOW_CHANGE": "资金流显著变化",
    "PRODUCT_TECH_RELEASE": "产品或技术发布",
    "ACCIDENT_DISASTER": "事故或灾害",
    "DIPLOMATIC_ACTION": "外交行动",
    "SANCTION_TRADE_CONTROL": "制裁或贸易管制",
    "ARMED_CONFLICT_CHANGE": "武装冲突变化",
    "SPEECH_STATEMENT": "正式讲话或声明",
    "FORECAST_OPINION": "预测或观点",
    "RUMOR_UNCONFIRMED": "传闻或未确认信息",
}


@dataclass(frozen=True, slots=True)
class _Rule:
    code: str
    keywords: tuple[str, ...]


_TOPIC_RULES = (
    _Rule(
        "ECONOMY_BUSINESS_FINANCE",
        (
            "央行",
            "证监会",
            "交易所",
            "经济",
            "公司",
            "市场",
            "银行",
            "基金",
            "债券",
            "股票",
            "关税",
            "地产",
        ),
    ),
    _Rule(
        "SCIENCE_TECHNOLOGY",
        (
            "人工智能",
            "AI",
            "大模型",
            "芯片",
            "半导体",
            "算力",
            "机器人",
            "航天",
            "软件",
            "云计算",
        ),
    ),
    _Rule("POLITICS", ("国务院", "政府", "政策", "外交", "总统", "总理", "立法")),
    _Rule("CONFLICT_WAR_PEACE", ("战争", "军事", "制裁", "停火", "冲突", "出口管制")),
    _Rule("CRIME_LAW_JUSTICE", ("法院", "检察", "判决", "诉讼", "犯罪", "警方")),
    _Rule(
        "DISASTER_ACCIDENT_EMERGENCY", ("事故", "地震", "洪水", "台风", "伤亡", "应急")
    ),
    _Rule("HEALTH", ("疾病", "医疗", "药品", "医院", "公共卫生", "临床试验")),
    _Rule("ENVIRONMENT", ("气候", "污染", "生态", "碳排放", "环保")),
    _Rule("LABOUR", ("就业", "失业", "工资", "工会", "退休")),
    _Rule("WEATHER", ("天气", "气象", "暴雨", "高温", "寒潮")),
    _Rule("SPORT", ("比赛", "联赛", "奥运", "冠军", "足球", "篮球")),
)

_EVENT_RULES = (
    _Rule("POLICY_ADJUSTMENT", ("降准", "降息", "加息", "税率调整", "补贴落地")),
    _Rule(
        "LAW_REGULATION_RELEASE", ("新规", "监管规则", "法律修订", "条例", "办法发布")
    ),
    _Rule("MACRO_DATA_RELEASE", ("GDP", "CPI", "PPI", "PMI", "就业数据", "进出口")),
    _Rule("EARNINGS_GUIDANCE", ("财报", "业绩预告", "净利润", "营业收入", "盈利")),
    _Rule("CORPORATE_FINANCE", ("增发", "发债", "回购", "分红", "减持", "增持")),
    _Rule(
        "MERGER_ACQUISITION_RESTRUCTURING", ("并购", "收购", "合并", "重组", "资产出售")
    ),
    _Rule(
        "CONTRACT_PROJECT_INVESTMENT",
        ("中标", "合同", "项目开工", "投资建设", "资本开支"),
    ),
    _Rule("PRODUCTION_OPERATION_CHANGE", ("扩产", "减产", "停产", "涨价", "供应中断")),
    _Rule("INVESTIGATION_PENALTY_LITIGATION", ("调查", "处罚", "诉讼", "仲裁")),
    _Rule("DEFAULT_DISTRESS", ("违约", "流动性危机", "破产", "退市风险")),
    _Rule(
        "MARKET_PRICE_MOVE", ("大涨", "大跌", "暴涨", "暴跌", "创出新高", "价格异动")
    ),
    _Rule(
        "CAPITAL_FLOW_CHANGE",
        ("资金流", "净流入", "净流出", "融资余额", "申购", "赎回"),
    ),
    _Rule("PRODUCT_TECH_RELEASE", ("发布模型", "产品发布", "技术突破", "研发里程碑")),
    _Rule("SANCTION_TRADE_CONTROL", ("制裁", "出口管制", "实体清单", "反制")),
    _Rule("ARMED_CONFLICT_CHANGE", ("军事行动", "空袭", "停火", "撤军", "冲突升级")),
    _Rule("SPEECH_STATEMENT", ("表示", "声明", "讲话", "答记者问")),
    _Rule("FORECAST_OPINION", ("预计", "预测", "研报", "观点", "认为")),
    _Rule("RUMOR_UNCONFIRMED", ("传闻", "据悉", "未经证实", "市场消息")),
    _Rule("POLICY_RELEASE", ("发布政策", "指导意见", "规划", "政策发布")),
)

_FOCUSED_RULES = (
    _Rule(
        "ECONOMY.MONETARY_POLICY", ("央行", "降准", "降息", "公开市场操作", "准备金")
    ),
    _Rule("ECONOMY.MACRO_ECONOMY", ("GDP", "CPI", "PPI", "PMI", "宏观经济")),
    _Rule(
        "ECONOMY.CAPITAL_MARKET_REGULATION",
        ("证监会", "交易所", "减持新规", "退市", "信息披露"),
    ),
    _Rule("ECONOMY.FINANCIAL_MARKETS", ("A股", "港股", "美股", "债券", "基金", "期货")),
    _Rule("TECH.ARTIFICIAL_INTELLIGENCE", ("人工智能", "AI", "大模型", "生成式")),
    _Rule("TECH.SEMICONDUCTOR", ("芯片", "半导体", "晶圆", "光刻")),
    _Rule(
        "CONFLICT.SANCTIONS_COUNTERMEASURES", ("制裁", "出口管制", "实体清单", "反制")
    ),
)


def build_label_candidates(title: str, content: str) -> LabelCandidates:
    text = f"{title}\n{content}".casefold()
    topic_matches = _match_rules(text, _TOPIC_RULES)
    focused_matches = _match_rules(text, _FOCUSED_RULES)
    event_matches = _match_rules(text, _EVENT_RULES)

    for focused in focused_matches:
        parent = (
            "SCIENCE_TECHNOLOGY"
            if focused.startswith("TECH.")
            else "CONFLICT_WAR_PEACE"
            if focused.startswith("CONFLICT.")
            else "ECONOMY_BUSINESS_FINANCE"
        )
        if parent not in topic_matches:
            topic_matches.insert(0, parent)

    return LabelCandidates(
        primary_topics=tuple(topic_matches[:MAX_PRIMARY_TOPIC_CANDIDATES]),
        event_types=tuple(event_matches[:MAX_EVENT_TYPE_CANDIDATES]),
        matched_rules=tuple(focused_matches),
    )


def topic_hypothesis(code: str) -> str:
    return f"这条新闻的主要主题是{PRIMARY_TOPIC_NAMES[code]}。"


def event_type_hypothesis(code: str) -> str:
    return f"这条新闻报道的主要事件是{EVENT_TYPE_NAMES[code]}。"


def parent_topic_for_subtopic(code: str) -> str:
    if code.startswith("TECH."):
        return "SCIENCE_TECHNOLOGY"
    if code.startswith("CONFLICT."):
        return "CONFLICT_WAR_PEACE"
    if code.startswith("POLITICS."):
        return "POLITICS"
    if code.startswith("ECONOMY."):
        return "ECONOMY_BUSINESS_FINANCE"
    raise KeyError(code)


def _match_rules(text: str, rules: tuple[_Rule, ...]) -> list[str]:
    matches: list[tuple[int, int, str]] = []
    for index, rule in enumerate(rules):
        hit_count = sum(keyword.casefold() in text for keyword in rule.keywords)
        if hit_count:
            matches.append((-hit_count, index, rule.code))
    matches.sort()
    return [code for _, _, code in matches]
