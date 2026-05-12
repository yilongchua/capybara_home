export interface Model {
  id?: string;
  name: string;
  display_name?: string | null;
  description?: string | null;
  supports_thinking?: boolean;
  supports_reasoning_effort?: boolean;
  context_window?: number | null;
}
