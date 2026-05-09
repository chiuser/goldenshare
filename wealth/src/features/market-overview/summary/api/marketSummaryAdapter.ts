import type { FactItem, MarketOverview } from "../../api/marketOverviewTypes";
import type { MarketSummaryResponse } from "./marketSummaryApi";

export interface MarketSummaryViewModel {
  facts: FactItem[];
  textTitle: string;
  textContent: string;
  statusLabel: string;
  statusTone: "ready" | "delayed";
  cardCount: 5 | 6;
  layoutVariant: "FIVE_SINGLE_ROW" | "SIX_TWO_ROWS";
  source: "mock" | "real";
}

function mapDirectionTone(direction?: string | null): FactItem["valueTone"] {
  if (direction === "UP") return "up";
  if (direction === "DOWN") return "down";
  if (direction === "FLAT") return "flat";
  return undefined;
}

function splitSummaryText(text: string): { title: string; content: string } {
  const normalized = text.trim();
  const index = normalized.indexOf("。");
  if (index < 0) {
    return { title: normalized, content: "" };
  }
  const title = normalized.slice(0, index + 1);
  const content = normalized.slice(index + 1).trim();
  return { title, content };
}

export function buildSummaryViewModelFromMock(overview: MarketOverview): MarketSummaryViewModel {
  const split = splitSummaryText(overview.summaryText);
  return {
    facts: overview.summaryFacts,
    textTitle: split.title,
    textContent: split.content,
    statusLabel: "事实聚合已就绪",
    statusTone: "ready",
    cardCount: 5,
    layoutVariant: "FIVE_SINGLE_ROW",
    source: "mock",
  };
}

export function buildSummaryViewModelFromApi(payload: MarketSummaryResponse): MarketSummaryViewModel {
  return {
    facts: payload.marketSummary.cards.map((card) => ({
      label: card.label,
      value: card.value ?? "--",
      valueTone: mapDirectionTone(card.direction),
      sub: card.subText ?? "",
    })),
    textTitle: payload.marketSummary.textCard.title,
    textContent: payload.marketSummary.textCard.content,
    statusLabel: payload.pageStatus.displayText,
    statusTone: payload.pageStatus.status === "READY" ? "ready" : "delayed",
    cardCount: payload.marketSummary.definition.cardCount,
    layoutVariant: payload.marketSummary.definition.layoutVariant,
    source: "real",
  };
}

