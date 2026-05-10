import { OpsV21SourcePage } from "./ops-v21-source-page";


export function OpsV21BizTablePage() {
  return (
    <OpsV21SourcePage
      sourceKey="biz_tableset"
      title="数据集 · Biz数据集"
      description="展示本系统自建业务派生表的只读状态。暂不提供写入和调度入口。"
    />
  );
}
