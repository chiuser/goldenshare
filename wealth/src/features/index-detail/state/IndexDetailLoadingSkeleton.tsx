const CANDLE_HEIGHTS = [90, 108, 126, 144, 90, 108, 126, 144, 90, 108, 126, 144, 90, 108, 126, 144, 90, 108, 126, 144, 90, 108];

export function IndexDetailLoadingSkeleton({ supportsTrend }: { supportsTrend: boolean }) {
  return (
    <>
      <section aria-busy="true" aria-label="正在加载指数行情" className="index-loading-chart-skeleton">
        <div className="index-loading-status">
          <strong>正在加载指数行情</strong>
          <span>{supportsTrend ? "正在读取日线、技术指标与趋势通道" : "正在读取日线与技术指标"}</span>
        </div>
        <div className="index-loading-main-chart">
          <div aria-hidden="true" className="index-loading-candles">
            {CANDLE_HEIGHTS.map((height, index) => <i key={index} style={{ height }} />)}
          </div>
        </div>
        {[
          ["MACD", "macd"],
          ["成交量", "volume"],
          ["KDJ", "kdj"],
        ].map(([label, key]) => (
          <div className="index-loading-indicator" data-indicator={key} key={key}>
            <span>{label}</span>
          </div>
        ))}
      </section>
      <aside aria-label="指数信息栏加载中" className="index-loading-rail-skeleton">
        <div className="index-loading-rail-header">
          <i className="wide" /><i className="short" />
          <div>{Array.from({ length: 3 }, (_, index) => <i key={index} />)}</div>
        </div>
        <div className="index-loading-tabs">{Array.from({ length: 3 }, (_, index) => <i key={index} />)}</div>
        <div className="index-loading-basic">
          <i className="heading" />
          <div>{Array.from({ length: 16 }, (_, index) => <i key={index} />)}</div>
        </div>
        <div className="index-loading-note"><i className="heading" /><i /><i className="short" /></div>
      </aside>
    </>
  );
}
