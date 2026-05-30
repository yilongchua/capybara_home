export interface UserLlmEndpoint {
  enabled: boolean;
  provider: "ollama" | "lm-studio" | "custom";
  display_name: string;
  base_url: string;
  api_key: string;
  models: string[];
  default_model: string;
  supports_thinking: boolean;
  supports_vision: boolean;
}

export interface LlmEndpointsData {
  userModels: Record<string, UserLlmEndpoint>;
}

export interface EmbeddingEndpointsData {
  userEmbeddingModels: Record<string, UserLlmEndpoint>;
}

export interface EmbeddingTestResult {
  ok: boolean;
  models: string[];
  dimensions: number | null;
  error: string | null;
}

export interface LlmTestResult {
  ok: boolean;
  models: string[];
  error: string | null;
}

export interface ComfyuiTestResult {
  ok: boolean;
  error: string | null;
}

export interface GenericTestResult {
  ok: boolean;
  status_code: number | null;
  error: string | null;
}

export interface KnowledgeVaultConfig {
  path: string;
  llmModel: string;
  embeddingModel: string;
}

export interface CanonicalThresholds {
  autoLexicalStrong: number;
  autoLexicalHigh: number;
  autoLexicalHighCooc: number;
  autoAbbreviationCooc: number;
  autoLexicalMid: number;
  autoLexicalMidCooc: number;
  reviewAbbreviationCooc: number;
  reviewCoocStrong: number;
  reviewLexical: number;
  reviewAbbreviationAlone: boolean;
}

export interface CanonicalThresholdsResponse {
  effective: CanonicalThresholds;
  defaults: CanonicalThresholds;
}
