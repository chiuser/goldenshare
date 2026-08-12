from __future__ import annotations


ETF_BASIC_FIELDS = (
    "ts_code",
    "csname",
    "extname",
    "cname",
    "index_code",
    "index_name",
    "setup_date",
    "list_date",
    "list_status",
    "exchange",
    "mgr_name",
    "custod_name",
    "mgt_fee",
    "etf_type",
)

BSE_MAPPING_FIELDS = (
    "name",
    "o_code",
    "n_code",
    "list_date",
)

HK_BASIC_FIELDS = (
    "ts_code",
    "name",
    "fullname",
    "enname",
    "cn_spell",
    "market",
    "list_status",
    "list_date",
    "delist_date",
    "trade_unit",
    "isin",
    "curr_type",
)

NAMECHANGE_FIELDS = (
    "ts_code",
    "name",
    "start_date",
    "end_date",
    "ann_date",
    "change_reason",
)

STOCK_COMPANY_FIELDS = (
    "ts_code",
    "com_name",
    "com_id",
    "exchange",
    "chairman",
    "manager",
    "secretary",
    "reg_capital",
    "setup_date",
    "province",
    "city",
    "introduction",
    "website",
    "email",
    "office",
    "employees",
    "main_business",
    "business_scope",
    "ann_date",
)

ST_FIELDS = (
    "ts_code",
    "name",
    "pub_date",
    "imp_date",
    "st_type",
    "st_reason",
    "st_explain",
)

INDEX_BASIC_FIELDS = (
    "ts_code",
    "name",
    "fullname",
    "market",
    "publisher",
    "index_type",
    "category",
    "base_date",
    "base_point",
    "list_date",
    "weight_rule",
    "desc",
    "exp_date",
)

ETF_INDEX_FIELDS = (
    "ts_code",
    "indx_name",
    "indx_csname",
    "pub_party_name",
    "pub_date",
    "base_date",
    "bp",
    "adj_circle",
)

THS_INDEX_FIELDS = (
    "ts_code",
    "name",
    "count",
    "exchange",
    "list_date",
    "type",
)

THS_MEMBER_FIELDS = (
    "ts_code",
    "con_code",
    "con_name",
    "weight",
    "in_date",
    "out_date",
    "is_new",
)
