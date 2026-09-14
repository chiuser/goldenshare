// Approved internal read cadence: design §11.13.14. Not a server execution policy.
export const CALCULATION_READ_POLICY = Object.freeze({ activeDelayMs: 2000, waitingDataDelayMs: 60000 });
