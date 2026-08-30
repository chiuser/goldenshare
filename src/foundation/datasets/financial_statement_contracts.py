from __future__ import annotations


FINANCIAL_STATEMENT_REPORT_TYPE_VALUES = tuple(str(value) for value in range(1, 13))

FINANCIAL_STATEMENT_REPORT_TYPE_LABELS = {
    "1": "合并报表",
    "2": "单季合并",
    "3": "调整单季合并表",
    "4": "调整合并报表",
    "5": "调整前合并报表",
    "6": "母公司报表",
    "7": "母公司单季表",
    "8": "母公司调整单季表",
    "9": "母公司调整表",
    "10": "母公司调整前报表",
    "11": "母公司调整前合并报表",
    "12": "母公司调整前报表（源站代码 12）",
}

FINANCIAL_STATEMENT_IDENTITY_FIELDS = (
    "ts_code",
    "ann_date",
    "f_ann_date",
    "end_date",
    "report_type",
    "comp_type",
    "update_flag",
)

if set(FINANCIAL_STATEMENT_REPORT_TYPE_LABELS) != set(FINANCIAL_STATEMENT_REPORT_TYPE_VALUES):
    raise RuntimeError("财务报表类型中文标签必须完整覆盖 1 至 12")


__all__ = [
    "FINANCIAL_STATEMENT_IDENTITY_FIELDS",
    "FINANCIAL_STATEMENT_REPORT_TYPE_LABELS",
    "FINANCIAL_STATEMENT_REPORT_TYPE_VALUES",
]
