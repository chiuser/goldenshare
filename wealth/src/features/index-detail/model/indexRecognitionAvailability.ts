export function resolveIndexRecognitionAvailability({development,tsCode,search}:{development:boolean;tsCode:string;search:string}) {
  const recognitionEnabled=development && tsCode==="000001.SH";
  return {recognitionEnabled,debugEnabled:recognitionEnabled && new URLSearchParams(search).get("debug")==="1"};
}
