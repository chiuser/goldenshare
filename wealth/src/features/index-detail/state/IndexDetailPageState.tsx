type IndexDetailPageStateVariant = "empty" | "error" | "forbidden" | "notFound" | "requestInvalid";

interface IndexDetailPageStateProps {
  detail?: string;
  onBack: () => void;
  onRecentDay?: () => void;
  onRetry?: () => void;
  variant: IndexDetailPageStateVariant;
}

const COPY: Record<IndexDetailPageStateVariant, { code?: string; detail: string; icon: string; title: string }> = {
  empty: {
    detail: "当前交易日没有可展示的行情，请稍后刷新或查看最近交易日。",
    icon: "−",
    title: "暂无指数日线数据",
  },
  error: {
    code: "ERROR · 请求未完成",
    detail: "行情服务暂时不可用，请稍后重试。",
    icon: "!",
    title: "指数详情加载失败",
  },
  forbidden: {
    code: "403 · FORBIDDEN",
    detail: "当前账号无权查看该指数详情，请联系管理员或返回指数首页。",
    icon: "锁",
    title: "暂无访问权限",
  },
  notFound: {
    code: "404 · NOT FOUND",
    detail: "未找到该指数，或该指数不在当前支持范围内。",
    icon: "!",
    title: "指数不存在",
  },
  requestInvalid: {
    code: "400 · INVALID REQUEST",
    detail: "指数详情请求参数无效，请返回指数首页重新进入。",
    icon: "!",
    title: "指数请求无效",
  },
};

export function IndexDetailPageState({ detail, onBack, onRecentDay, onRetry, variant }: IndexDetailPageStateProps) {
  const copy = COPY[variant];
  return (
    <section aria-label={copy.title} className={`index-page-state index-page-state-${variant}`}>
      <div className="index-page-state-content">
        <div aria-hidden="true" className="index-page-state-icon">{copy.icon}</div>
        <strong>{copy.title}</strong>
        <span>{detail || copy.detail}</span>
        {copy.code ? <code>{copy.code}</code> : null}
        <div className="index-page-state-actions">
          {onRetry ? <button className="primary" type="button" onClick={onRetry}>重新加载</button> : null}
          {onRecentDay ? <button type="button" onClick={onRecentDay}>查看最近交易日</button> : null}
          {variant !== "empty" ? <button type="button" onClick={onBack}>返回指数首页</button> : null}
        </div>
      </div>
    </section>
  );
}
