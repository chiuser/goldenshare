export function resolveIndexRecognitionAvailability({development, tsCode, validatedTsCode}: {
  development: boolean; tsCode: string; validatedTsCode: string | null;
}) {
  return development && validatedTsCode === tsCode && tsCode !== "899050.BJ";
}
