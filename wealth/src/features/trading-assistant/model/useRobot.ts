import { useCallback, useEffect, useState } from "react";
import { getRobot } from "../api/robotApi";
import type { RobotConfig } from "../api/generatedContracts";
import { getAuthEpoch } from "../../auth/model/authStorage";

export function useRobot() {
  const [robot, setRobot] = useState<RobotConfig | null>(null);
  const [loading, setLoading] = useState(true), [error, setError] = useState(false), [revision, setRevision] = useState(0);
  const refresh = useCallback(() => setRevision(v => v + 1), []);
  useEffect(() => {
    const controller = new AbortController(), epoch = getAuthEpoch(); setLoading(true); setError(false); setRobot(null);
    getRobot(controller.signal).then(value => { if (!controller.signal.aborted && epoch === getAuthEpoch()) setRobot(value.robot); })
      .catch(() => { if (!controller.signal.aborted && epoch === getAuthEpoch()) setError(true); })
      .finally(() => { if (!controller.signal.aborted && epoch === getAuthEpoch()) setLoading(false); });
    return () => controller.abort();
  }, [revision]);
  return { robot, loading, error, refresh, setRobot };
}
