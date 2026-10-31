import {expect,it} from "vitest";
import {resolveIndexRecognitionAvailability as resolve} from "./indexRecognitionAvailability";
it("uses only real development, subject and the exact URL parameter",()=>{for(const development of [true,false])for(const tsCode of ["000001.SH","399001.SZ"])for(const search of ["","?debug=0","?debug=1","?debug=true","?debug=01"]){const v=resolve({development,tsCode,search});expect(v.recognitionEnabled).toBe(development&&tsCode==="000001.SH");expect(v.debugEnabled).toBe(development&&tsCode==="000001.SH"&&search==="?debug=1");}});
