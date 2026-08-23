export type NewsReaderMode = "URL" | "HTML" | "TEXT";

export interface NewsReaderViewModel {
  newsId: string;
  title: string;
  source: string | null;
  publishTime: string;
  displayPublishTime: string;
  readerMode: NewsReaderMode;
  url: string | null;
  html: string | null;
  content: string | null;
}

export type NewsReaderDialogState =
  | { status: "closed" }
  | {
      status: "loading";
      newsId: string;
      title: string;
      publishTime: string;
      readerMode: NewsReaderMode;
      requestId: number;
    }
  | { status: "ready"; requestId: number; item: NewsReaderViewModel }
  | {
      status: "empty";
      newsId: string;
      title: string;
      publishTime: string;
      message: string;
    }
  | {
      status: "error";
      newsId: string;
      title: string;
      publishTime: string;
      message: string;
      retryable: boolean;
    };
