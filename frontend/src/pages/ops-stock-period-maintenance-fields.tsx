import { Stack, Textarea } from '@mantine/core';
import type { OpsStockPeriodMaintenanceIntent } from '../shared/api/types';

export function stockPeriodMaintenanceIntent(kind: string, fields: string[], codes: string, keys: string): OpsStockPeriodMaintenanceIntent {
  const intent: OpsStockPeriodMaintenanceIntent = { kind };
  if (fields.includes('stock_codes')) {
    intent.stock_codes = codes.split(/[\s,，]+/).filter(Boolean).map(code => code.toUpperCase());
    if (!intent.stock_codes.length) throw new Error('请填写要下载完整历史的股票代码。');
  }
  if (fields.includes('remove_keys')) {
    const lines = keys.split(/\r?\n/).map(line => line.trim()).filter(Boolean);
    if (!lines.length) throw new Error('请填写要撤回的完整原始记录键。');
    intent.remove_keys = lines.map(line => {
      const values = line.split(/[\s,，]+/);
      if (values.length !== 3) throw new Error('撤回记录每行须填写股票代码、源日期、频率。');
      return { ts_code: values[0].toUpperCase(), trade_date: values[1], freq: values[2] };
    });
  }
  return intent;
}

export function StockPeriodMaintenanceFields(props: {
  fields: string[]; codes: string; keys: string;
  onCodes: (value: string) => void; onKeys: (value: string) => void;
}) {
  return <Stack gap="sm">
    {props.fields.includes('stock_codes') ? <Textarea label="完整历史股票代码" autosize minRows={3}
      description="每行一个完整股票代码，也可用逗号分隔。只处理这些股票，不限定历史日期。"
      placeholder="000001.SZ" value={props.codes} onChange={event => props.onCodes(event.currentTarget.value)} /> : null}
    {props.fields.includes('remove_keys') ? <Textarea label="撤回原始记录" autosize minRows={3}
      description="每行填写：股票代码,源日期,频率。日期用YYYY-MM-DD，频率用week或month；只撤回列出的完整键。"
      placeholder="000001.SZ,2020-02-28,month" value={props.keys} onChange={event => props.onKeys(event.currentTarget.value)} /> : null}
  </Stack>;
}
