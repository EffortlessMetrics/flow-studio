import type { Template, TemplateCategory } from "../api/client.js";
interface TemplatePaletteOptions {
    /** Container element to render into */
    container: HTMLElement;
    /** Callback when a template is dragged onto the canvas */
    onTemplateDrop?: (template: Template, position: {
        x: number;
        y: number;
    }) => void;
    /** Callback when a template is clicked (for keyboard/accessibility) */
    onTemplateSelect?: (template: Template) => void;
}
/**
 * Template palette for drag-and-drop flow editing.
 *
 * Features:
 * - Groups templates by category
 * - Search/filter functionality
 * - Drag-and-drop support
 * - Keyboard navigation
 */
export declare class TemplatePalette {
    private container;
    private templates;
    private filteredTemplates;
    private searchQuery;
    private selectedCategory;
    private onTemplateDrop?;
    private onTemplateSelect?;
    private isLoading;
    private error;
    constructor(options: TemplatePaletteOptions);
    /**
     * Initialize the palette by fetching templates and rendering
     */
    init(): Promise<void>;
    /**
     * Refresh templates from API
     */
    refresh(): Promise<void>;
    /**
     * Set search query and re-filter
     */
    setSearch(query: string): void;
    /**
     * Set category filter
     */
    setCategory(category: TemplateCategory | "all"): void;
    /**
     * Apply search and category filters
     */
    private applyFilters;
    /**
     * Render the complete palette
     */
    private render;
    /**
     * Create header with search input
     */
    private createHeader;
    /**
     * Create category tabs
     */
    private createCategoryTabs;
    /**
     * Create a single category tab
     */
    private createCategoryTab;
    /**
     * Render the template list (called on filter changes)
     */
    private renderTemplateList;
    /**
     * Group templates by category
     */
    private groupByCategory;
    /**
     * Create a category group with header and templates
     */
    private createCategoryGroup;
    /**
     * Create a grid of template cards
     */
    private createTemplateGrid;
    /**
     * Create a single template card
     */
    private createTemplateCard;
    /**
     * Destroy the palette and clean up
     */
    destroy(): void;
}
/**
 * Create and initialize a template palette
 */
export declare function createTemplatePalette(container: HTMLElement, options?: Omit<TemplatePaletteOptions, "container">): Promise<TemplatePalette>;
export {};
/**
 * CSS class names used by this component:
 *
 * .template-palette - Main container
 * .template-palette__header - Header with title and search
 * .template-palette__title - Palette title
 * .template-palette__search - Search container
 * .template-palette__search-input - Search input field
 * .template-palette__tabs - Category tabs container
 * .template-palette__tab - Individual tab
 * .template-palette__tab--active - Active tab
 * .template-palette__tab-icon - Tab icon
 * .template-palette__tab-label - Tab label
 * .template-palette__list - Template list container
 * .template-palette__loading - Loading state
 * .template-palette__spinner - Loading spinner
 * .template-palette__error - Error state
 * .template-palette__error-icon - Error icon
 * .template-palette__retry - Retry button
 * .template-palette__empty - Empty state
 * .template-palette__empty-icon - Empty state icon
 * .template-palette__group - Category group
 * .template-palette__group-header - Group header
 * .template-palette__group-icon - Group icon
 * .template-palette__group-label - Group label
 * .template-palette__group-count - Template count badge
 * .template-palette__grid - Template grid
 * .template-palette__card - Template card
 * .template-palette__card--dragging - Card being dragged
 * .template-palette__card-icon - Card icon
 * .template-palette__card-content - Card content area
 * .template-palette__card-name - Card title
 * .template-palette__card-desc - Card description
 */
