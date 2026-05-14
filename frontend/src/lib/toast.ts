import type { AgentKey } from "./data";

export type ToastInput = {
  title: string;
  app: string;
  msg: string;
  agent: AgentKey;
};
