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
