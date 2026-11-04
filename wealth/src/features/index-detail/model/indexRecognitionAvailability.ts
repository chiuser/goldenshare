export function resolveIndexRecognitionAvailability({development,tsCode,validatedTsCode,search}:{development:boolean;tsCode:string;validatedTsCode:string|null;search:string}) {
  const recognitionEnabled=development && validatedTsCode===tsCode && tsCode!=="899050.BJ";
  return {recognitionEnabled,debugEnabled:recognitionEnabled && new URLSearchParams(search).get("debug")==="1"};
}
