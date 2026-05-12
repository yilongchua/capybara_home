export interface UserMemory {
  version: string;
  scope?: "global" | "workspace";
  scopeId?: string;
  lastUpdated: string;
  user: {
    workContext: {
      summary: string;
      updatedAt: string;
    };
    personalContext: {
      summary: string;
      updatedAt: string;
    };
    topOfMind: {
      summary: string;
      updatedAt: string;
    };
  };
  history: {
    recentMonths: {
      summary: string;
      updatedAt: string;
    };
    earlierContext: {
      summary: string;
      updatedAt: string;
    };
    longTermBackground: {
      summary: string;
      updatedAt: string;
    };
  };
  facts: {
    id: string;
    content: string;
    category: string;
    confidence: number;
    createdAt: string;
    source: string;
  }[];
  behaviorRules?: {
    id: string;
    instruction: string;
    active: boolean;
    scope: string;
    scopeId: string;
    source: string;
    createdAt: string;
    updatedAt: string;
  }[];
}

export interface MemoryFactUpdate {
  content: string;
  category: string;
  confidence: number;
  source?: string;
}

export interface BehaviorRuleCreate {
  instruction: string;
  active?: boolean;
  source?: string;
}

export interface BehaviorRuleUpdate {
  instruction?: string;
  active?: boolean;
}
