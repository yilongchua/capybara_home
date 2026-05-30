import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  loadCanonicalThresholds,
  loadEmbeddingEndpoints,
  loadKnowledgeVaultConfig,
  loadLlmEndpoints,
  saveCanonicalThresholds,
  saveEmbeddingEndpoints,
  saveKnowledgeVaultConfig,
  saveLlmEndpoints,
  testComfyuiEndpoint,
  testEmbeddingEndpoint,
  testGenericEndpoint,
  testLlmEndpoint,
} from "./api";
import type {
  CanonicalThresholds,
  CanonicalThresholdsResponse,
  ComfyuiTestResult,
  EmbeddingTestResult,
  GenericTestResult,
  KnowledgeVaultConfig,
  LlmTestResult,
  UserLlmEndpoint,
} from "./types";

export function useLlmEndpoints() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["llmEndpoints"],
    queryFn: () => loadLlmEndpoints(),
  });
  return { endpoints: data?.userModels ?? ({} as Record<string, UserLlmEndpoint>), isLoading, error };
}

export function useSaveLlmEndpoints() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (userModels: Record<string, UserLlmEndpoint>) => {
      await saveLlmEndpoints(userModels);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["llmEndpoints"] });
      // /api/models is derived from user endpoints — refresh the chatbox
      // dropdown so newly added models appear without a page reload.
      void queryClient.invalidateQueries({ queryKey: ["models"] });
    },
  });
}

export function useTestLlmEndpoint() {
  return useMutation<LlmTestResult, Error, { baseUrl: string; apiKey: string }>({
    mutationFn: ({ baseUrl, apiKey }) => testLlmEndpoint(baseUrl, apiKey),
  });
}

export function useTestComfyuiEndpoint() {
  return useMutation<ComfyuiTestResult, Error, { baseUrl: string }>({
    mutationFn: ({ baseUrl }) => testComfyuiEndpoint(baseUrl),
  });
}

export function useTestGenericEndpoint() {
  return useMutation<GenericTestResult, Error, { url: string; timeoutSeconds?: number }>({
    mutationFn: ({ url, timeoutSeconds }) => testGenericEndpoint(url, timeoutSeconds),
  });
}

export function useEmbeddingEndpoints() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["embeddingEndpoints"],
    queryFn: () => loadEmbeddingEndpoints(),
  });
  return {
    endpoints: data?.userEmbeddingModels ?? ({} as Record<string, UserLlmEndpoint>),
    isLoading,
    error,
  };
}

export function useSaveEmbeddingEndpoints() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (userEmbeddingModels: Record<string, UserLlmEndpoint>) => {
      await saveEmbeddingEndpoints(userEmbeddingModels);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["embeddingEndpoints"] });
    },
  });
}

export function useTestEmbeddingEndpoint() {
  return useMutation<
    EmbeddingTestResult,
    Error,
    { baseUrl: string; apiKey: string; model?: string }
  >({
    mutationFn: ({ baseUrl, apiKey, model }) =>
      testEmbeddingEndpoint(baseUrl, apiKey, model),
  });
}

export function useKnowledgeVaultConfig() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["knowledgeVaultConfig"],
    queryFn: () => loadKnowledgeVaultConfig(),
  });
  return {
    config:
      data ?? ({ path: "", llmModel: "", embeddingModel: "" } as KnowledgeVaultConfig),
    isLoading,
    error,
  };
}

export function useSaveKnowledgeVaultConfig() {
  const queryClient = useQueryClient();
  return useMutation<KnowledgeVaultConfig, Error, KnowledgeVaultConfig>({
    mutationFn: (config) => saveKnowledgeVaultConfig(config),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["knowledgeVaultConfig"] });
    },
  });
}

export function useCanonicalThresholds() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["canonicalThresholds"],
    queryFn: () => loadCanonicalThresholds(),
  });
  return { data, isLoading, error };
}

export function useSaveCanonicalThresholds() {
  const queryClient = useQueryClient();
  return useMutation<
    CanonicalThresholdsResponse,
    Error,
    CanonicalThresholds | null
  >({
    mutationFn: (thresholds) => saveCanonicalThresholds(thresholds),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["canonicalThresholds"] });
    },
  });
}
