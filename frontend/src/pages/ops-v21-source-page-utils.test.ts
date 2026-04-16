import { describe, expect, it } from "vitest";

import { dedupeModeItemsForSource } from "./ops-v21-source-page-utils";

describe("ops-v21 source page mode dedupe", () => {
  it("Biying 页面优先保留 biying_* 的同名数据集", () => {
    const items = [
      {
        dataset_key: "moneyflow",
        display_name: "资金流向",
        domain_key: "equity",
        domain_display_name: "股票",
        mode: "multi_source_pipeline",
        source_scope: "tushare,biying",
        layer_plan: "raw->std->resolution->serving",
        raw_table: "raw_tushare.moneyflow",
        std_table_hint: "core_multi.moneyflow_std",
        serving_table: "core_serving.equity_moneyflow",
        freshness_status: "healthy",
        latest_business_date: "2026-04-16",
        std_mapping_configured: true,
        std_cleansing_configured: true,
        resolution_policy_configured: true,
      },
      {
        dataset_key: "biying_moneyflow",
        display_name: "BIYING 资金流向",
        domain_key: "equity",
        domain_display_name: "股票",
        mode: "raw_only",
        source_scope: "biying",
        layer_plan: "raw-only",
        raw_table: "raw_biying.moneyflow",
        std_table_hint: null,
        serving_table: null,
        freshness_status: "healthy",
        latest_business_date: "2026-04-16",
        std_mapping_configured: false,
        std_cleansing_configured: false,
        resolution_policy_configured: false,
      },
    ];

    const deduped = dedupeModeItemsForSource(items, "biying");
    expect(deduped).toHaveLength(1);
    expect(deduped[0]?.dataset_key).toBe("biying_moneyflow");
  });

  it("Tushare 页面优先保留非 biying 前缀的数据集", () => {
    const items = [
      {
        dataset_key: "moneyflow",
        display_name: "资金流向",
        domain_key: "equity",
        domain_display_name: "股票",
        mode: "multi_source_pipeline",
        source_scope: "tushare,biying",
        layer_plan: "raw->std->resolution->serving",
        raw_table: "raw_tushare.moneyflow",
        std_table_hint: "core_multi.moneyflow_std",
        serving_table: "core_serving.equity_moneyflow",
        freshness_status: "healthy",
        latest_business_date: "2026-04-16",
        std_mapping_configured: true,
        std_cleansing_configured: true,
        resolution_policy_configured: true,
      },
      {
        dataset_key: "biying_moneyflow",
        display_name: "BIYING 资金流向",
        domain_key: "equity",
        domain_display_name: "股票",
        mode: "raw_only",
        source_scope: "biying",
        layer_plan: "raw-only",
        raw_table: "raw_biying.moneyflow",
        std_table_hint: null,
        serving_table: null,
        freshness_status: "healthy",
        latest_business_date: "2026-04-16",
        std_mapping_configured: false,
        std_cleansing_configured: false,
        resolution_policy_configured: false,
      },
    ];

    const deduped = dedupeModeItemsForSource(items, "tushare");
    expect(deduped).toHaveLength(1);
    expect(deduped[0]?.dataset_key).toBe("moneyflow");
  });

  it("不同业务键的数据集不会被错误合并", () => {
    const items = [
      {
        dataset_key: "stock_basic",
        display_name: "股票主数据",
        domain_key: "reference_data",
        domain_display_name: "基础主数据",
        mode: "multi_source_pipeline",
        source_scope: "tushare,biying",
        layer_plan: "raw->std->resolution->serving",
        raw_table: "raw_tushare.stock_basic",
        std_table_hint: "core_multi.security_std",
        serving_table: "core_serving.security_serving",
        freshness_status: "healthy",
        latest_business_date: null,
        std_mapping_configured: true,
        std_cleansing_configured: true,
        resolution_policy_configured: true,
      },
      {
        dataset_key: "biying_equity_daily",
        display_name: "BIYING 股票日线",
        domain_key: "equity",
        domain_display_name: "股票",
        mode: "raw_only",
        source_scope: "biying",
        layer_plan: "raw-only",
        raw_table: "raw_biying.equity_daily_bar",
        std_table_hint: null,
        serving_table: null,
        freshness_status: "healthy",
        latest_business_date: "2026-04-16",
        std_mapping_configured: false,
        std_cleansing_configured: false,
        resolution_policy_configured: false,
      },
    ];

    const deduped = dedupeModeItemsForSource(items, "biying");
    expect(deduped).toHaveLength(2);
  });
});

