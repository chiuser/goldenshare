import type { AccountSummary } from "../api/generatedContracts";
import { validInputField } from "../api/contractValidation";

type PreferenceStorage = Pick<Storage, "getItem" | "setItem">;
const key = (userId: number) => `wealth.ta.last-account.v1:${userId}`;
const validUser = (userId: number) => Number.isSafeInteger(userId) && userId > 0;
function browserStorage(): PreferenceStorage | null {
  try { return window.localStorage; } catch { return null; }
}

/** The server orders the owned list by creation time and then account ID. */
export function restoreAccountSelection(userId: number, accounts: readonly AccountSummary[],
  storage: PreferenceStorage | null = browserStorage()): string | null {
  let remembered: string | null = null;
  try { if (validUser(userId)) remembered = storage?.getItem(key(userId)) ?? null; } catch { /* Preference is optional. */ }
  if (remembered && validInputField("AccountRef", "accountId", remembered)
    && accounts.some(account => account.accountId === remembered)) return remembered;
  return accounts[0]?.accountId ?? null;
}

/** ALL and unowned values never overwrite the last specific account. */
export function rememberAccountSelection(userId: number, selected: string, accounts: readonly AccountSummary[],
  storage: PreferenceStorage | null = browserStorage()): void {
  if (!validUser(userId) || !validInputField("AccountRef", "accountId", selected)
    || !accounts.some(account => account.accountId === selected)) return;
  try { storage?.setItem(key(userId), selected); } catch { /* Storage failure must not prevent accounting. */ }
}
