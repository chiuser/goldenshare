export interface ShortcutItem {
  key: string;
  path: string;
  title: string;
  description: string;
  badge?: string;
  badgeTone?: "alert" | "neutral";
  disabled?: boolean;
}
