import type { FlowKey } from "./domain.js";
/** Canonical flow ordering in SDLC sequence */
export declare const FLOW_KEYS: FlowKey[];
/** Flow key to numeric index (1-6) */
export declare const FLOW_INDEX: Record<FlowKey, number>;
/** Flow key to display title */
export declare const FLOW_TITLES: Record<FlowKey, string>;
/** Flow key to description */
export declare const FLOW_DESCRIPTIONS: Record<FlowKey, string>;
