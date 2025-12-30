import type { SearchResult, SearchCallbacks } from "./domain.js";
/**
 * Configure callbacks for the search module.
 * Call this before using other functions to wire up navigation.
 */
export declare function configure(callbacks?: SearchCallbacks): void;
/**
 * Perform search query against the API.
 */
export declare function performSearch(query: string): Promise<void>;
/**
 * Render search results in the dropdown.
 */
export declare function renderSearchResults(results: SearchResult[]): void;
/**
 * Close the search dropdown and reset state.
 */
export declare function closeSearchDropdown(): void;
/**
 * Select a search result by index and navigate to it.
 */
export declare function selectSearchResult(index: number): Promise<void>;
/**
 * Initialize search input handlers.
 */
export declare function initSearchHandlers(): void;
/**
 * Focus the search input.
 */
export declare function focusSearch(): void;
