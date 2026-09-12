import { useState } from "react";
import type { CreateAccountInput, InitializationDefaults } from "../api/generatedContracts";
import { getInitialization } from "../api/tradingAssistantApi";
import { AccountingWriteFlow } from "./AccountingWriteFlow";
import { AccountSetupDialog } from "./AccountSetupDialog";

export function NewAccountFlow({ defaults, onClose, onCreated }: {
  defaults: InitializationDefaults; onClose: () => void; onCreated: (accountId: string) => Promise<void>;
}) {
  const [restored, setRestored] = useState<CreateAccountInput | null>(null);
  return <AccountingWriteFlow scope={{ scopeType: "ACCOUNT_CREATE" }} onClose={onClose}
    onRestore={async recovered => {
      if (recovered.operationType !== "ACCOUNT_CREATE") throw new Error("Unexpected recovered operation");
      setRestored(recovered.input);
    }}
    onSaved={async receipt => {
      if (receipt.operationType !== "ACCOUNT_CREATE") throw new Error("Unexpected receipt");
      const id = receipt.result.account.accountId;
      await getInitialization(id);
      await onCreated(id);
    }}>
    {session => <AccountSetupDialog stampTaxRatePct={defaults.stampTaxRatePct} onClose={onClose}
      restoredInput={restored} saving={session.busy && !!session.recovery && !session.editing}
      saveDisabled={!session.canSave} errors={session.fieldErrors}
      onSubmit={input => { void session.save("ACCOUNT_CREATE", input); }} />}
  </AccountingWriteFlow>;
}
