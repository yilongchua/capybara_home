import { getBackendBaseURL } from "@/core/config";

import type {
  ComfyuiTestResult,
  EmbeddingEndpointsData,
  EmbeddingTestResult,
  GenericTestResult,
  LlmEndpointsData,
  LlmTestResult,
  UserLlmEndpoint,
} from "./types";

export async function testLlmEndpoint(baseUrl: string, apiKey: string) {
  const response = await fetch(`${getBackendBaseURL()}/api/onboarding/test-llm`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ base_url: baseUrl, api_key: apiKey }),
  });
  return response.json() as Promise<LlmTestResult>;
}

export async function testComfyuiEndpoint(baseUrl: string) {
  const response = await fetch(
    `${getBackendBaseURL()}/api/onboarding/test-comfyui`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ base_url: baseUrl }),
    },
  );
  return response.json() as Promise<ComfyuiTestResult>;
}

export async function testGenericEndpoint(url: string, timeoutSeconds = 10) {
  const response = await fetch(
    `${getBackendBaseURL()}/api/onboarding/test-generic`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, timeout_seconds: timeoutSeconds }),
    },
  );
  return response.json() as Promise<GenericTestResult>;
}

export async function loadLlmEndpoints() {
  const response = await fetch(
    `${getBackendBaseURL()}/api/onboarding/llm-endpoints`,
  );
  return response.json() as Promise<LlmEndpointsData>;
}

export async function saveLlmEndpoints(userModels: Record<string, UserLlmEndpoint>) {
  const response = await fetch(
    `${getBackendBaseURL()}/api/onboarding/llm-endpoints`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ userModels }),
    },
  );
  return response.json() as Promise<LlmEndpointsData>;
}

export async function testEmbeddingEndpoint(
  baseUrl: string,
  apiKey: string,
  model?: string,
) {
  const response = await fetch(
    `${getBackendBaseURL()}/api/onboarding/test-embedding`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ base_url: baseUrl, api_key: apiKey, model }),
    },
  );
  return response.json() as Promise<EmbeddingTestResult>;
}

export async function loadEmbeddingEndpoints() {
  const response = await fetch(
    `${getBackendBaseURL()}/api/onboarding/embedding-endpoints`,
  );
  return response.json() as Promise<EmbeddingEndpointsData>;
}

export async function saveEmbeddingEndpoints(
  userEmbeddingModels: Record<string, UserLlmEndpoint>,
) {
  const response = await fetch(
    `${getBackendBaseURL()}/api/onboarding/embedding-endpoints`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ userEmbeddingModels }),
    },
  );
  return response.json() as Promise<EmbeddingEndpointsData>;
}
