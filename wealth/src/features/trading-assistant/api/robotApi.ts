import type { CandidateInput, CandidateResult, RobotConfig } from "./generatedContracts";
import { parseContract, InvalidTradingAssistantResponse } from "./contractValidation";
import { request } from "./tradingAssistantApi";

const identity = () => ({ requestId: crypto.randomUUID(), attemptId: crypto.randomUUID() });
export const getRobot = (signal?: AbortSignal) => request("/robot", "RobotResponse", { signal });
export async function createRobotCandidate(input: CandidateInput, signal: AbortSignal) {
  return (await request("/robot/candidates", "CandidateCreateReceipt", { method: "POST", write: true, signal,
    body: parseContract("CandidateCommand", { ...input, ...identity() }) })).result;
}
export async function testRobot(candidate: CandidateResult, signal: AbortSignal) {
  return (await request(`/robot/candidates/${candidate.candidateId}/tests`, "RobotTestReceipt", { method: "POST", write: true, signal,
    body: parseContract("TestCandidateCommand", { ...identity(), expectedCandidateVersion: candidate.candidateVersion }) })).result;
}
export async function getRobotTest(candidateId: string, testId: string, signal: AbortSignal) {
  const value = await request(`/robot/candidates/${candidateId}/tests/${testId}`, "TestResult", { signal });
  if (value.testId !== testId) throw new InvalidTradingAssistantResponse();
  return value;
}
export async function confirmRobot(candidateId: string, testId: string, previous: RobotConfig | null, signal: AbortSignal) {
  return (await request(`/robot/candidates/${candidateId}/confirmations`, "RobotConfirmReceipt", { method: "POST", write: true, signal,
    body: parseContract("ConfirmCandidateCommand", { ...identity(), expectedConfigVersionId: previous?.configVersionId ?? null, testId, receivedConfirmed: true }) })).result;
}
export async function getNotification(id: string, cursor: string | null, signal?: AbortSignal) {
  const query = new URLSearchParams(); if (cursor) query.set("cursor", cursor);
  const value = await request(`/notifications/${encodeURIComponent(id)}?${query}`, "NotificationDetail", { signal });
  if (value.notificationId !== id) throw new InvalidTradingAssistantResponse();
  return value;
}
