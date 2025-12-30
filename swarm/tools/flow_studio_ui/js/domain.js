/**
 * Flow Studio Domain Types
 *
 * CANONICAL SOURCE: src/domain.ts
 * The js/domain.d.ts file is GENERATED from this file — do not edit it directly.
 * Run `make ts-build` to regenerate declaration files after editing this source.
 *
 * These types define the core data structures used throughout Flow Studio.
 * They serve as the contract between:
 * - Python backend (FastAPI endpoints)
 * - TypeScript frontend (browser modules)
 * - Tests and tooling
 */
/**
 * Query an element by its data-uiid attribute with type safety.
 * Returns null if not found.
 *
 * @example
 * const searchInput = qsByUiid("flow_studio.header.search.input");
 * if (searchInput) searchInput.focus();
 */
export function qsByUiid(id) {
    return document.querySelector(`[data-uiid="${id}"]`);
}
/**
 * Query all elements matching a data-uiid prefix.
 * Useful for dynamic IDs like "flow_studio.canvas.outline.step:*".
 *
 * @example
 * const steps = qsAllByUiidPrefix("flow_studio.canvas.outline.step:");
 */
export function qsAllByUiidPrefix(prefix) {
    return document.querySelectorAll(`[data-uiid^="${prefix}"]`);
}
/**
 * Check if the Flow Studio UI is ready for interaction.
 * @returns true if data-ui-ready="ready" on <html>
 */
export function isUIReady() {
    return document.documentElement.dataset.uiReady === "ready";
}
/**
 * Check if the Flow Studio UI failed to initialize.
 * @returns true if data-ui-ready="error" on <html>
 */
export function isUIError() {
    return document.documentElement.dataset.uiReady === "error";
}
/**
 * Get the current UI readiness state.
 * @returns "loading" | "ready" | "error"
 */
export function getUIReadyState() {
    return document.documentElement.dataset.uiReady || "loading";
}
/**
 * Wait for the Flow Studio UI to be ready.
 * Resolves when data-ui-ready="ready", rejects if "error" or timeout.
 *
 * @param timeoutMs - Maximum time to wait (default: 10000ms)
 * @returns Promise that resolves with the SDK when ready
 * @throws Error if UI fails to initialize or times out
 *
 * @example
 * // In test or automation code:
 * try {
 *   const sdk = await waitForUIReady();
 *   await sdk.setActiveFlow("build");
 * } catch (err) {
 *   console.error("Flow Studio failed to initialize", err);
 * }
 */
export async function waitForUIReady(timeoutMs = 10000) {
    const startTime = Date.now();
    return new Promise((resolve, reject) => {
        // Check immediately
        const state = getUIReadyState();
        if (state === "ready" && window.__flowStudio) {
            return resolve(window.__flowStudio);
        }
        if (state === "error") {
            return reject(new Error("Flow Studio initialization failed"));
        }
        // Set up polling
        const checkInterval = 100;
        const check = () => {
            const elapsed = Date.now() - startTime;
            const currentState = getUIReadyState();
            if (currentState === "ready" && window.__flowStudio) {
                resolve(window.__flowStudio);
                return;
            }
            if (currentState === "error") {
                reject(new Error("Flow Studio initialization failed"));
                return;
            }
            if (elapsed >= timeoutMs) {
                reject(new Error(`Flow Studio initialization timed out after ${timeoutMs}ms (state: ${currentState})`));
                return;
            }
            setTimeout(check, checkInterval);
        };
        setTimeout(check, checkInterval);
    });
}
/**
 * Safely get the Flow Studio SDK, returning null if not ready.
 * Use this for code that should gracefully handle the SDK being unavailable.
 *
 * @returns The SDK if ready, null otherwise
 *
 * @example
 * const sdk = getSDKIfReady();
 * if (sdk) {
 *   // Use SDK
 * } else {
 *   // Graceful fallback
 * }
 */
export function getSDKIfReady() {
    return isUIReady() ? window.__flowStudio || null : null;
}
