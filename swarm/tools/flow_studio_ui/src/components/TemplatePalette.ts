// swarm/tools/flow_studio_ui/src/components/TemplatePalette.ts
// Template palette component for drag-and-drop flow editing
//
// Displays draggable template cards grouped by category with search/filter.
// NO filesystem operations - templates are fetched from API.

import { flowStudioApi } from "../api/client.js";
import type { Template, TemplateCategory } from "../api/client.js";

// ============================================================================
// Types
// ============================================================================

interface TemplatePaletteOptions {
  /** Container element to render into */
  container: HTMLElement;
  /** Callback when a template is dragged onto the canvas */
  onTemplateDrop?: (template: Template, position: { x: number; y: number }) => void;
  /** Callback when a template is clicked (for keyboard/accessibility) */
  onTemplateSelect?: (template: Template) => void;
}

interface CategoryMeta {
  label: string;
  icon: string;
  description: string;
}

// ============================================================================
// Category Metadata
// ============================================================================

const CATEGORY_META: Record<TemplateCategory, CategoryMeta> = {
  "flow-control": {
    label: "Flow Control",
    icon: "\u2192",
    description: "Control flow and sequencing",
  },
  agent: {
    label: "Agents",
    icon: "\u{1F916}",
    description: "Agent nodes for task execution",
  },
  decision: {
    label: "Decisions",
    icon: "\u2753",
    description: "Decision points and branching",
  },
  artifact: {
    label: "Artifacts",
    icon: "\u{1F4C4}",
    description: "Output artifacts and files",
  },
  gate: {
    label: "Gates",
    icon: "\u{1F6A7}",
    description: "Validation and gate checks",
  },
  custom: {
    label: "Custom",
    icon: "\u2728",
    description: "Custom templates",
  },
};

const CATEGORY_ORDER: TemplateCategory[] = [
  "flow-control",
  "agent",
  "decision",
  "artifact",
  "gate",
  "custom",
];

// ============================================================================
// Template Palette Component
// ============================================================================

/**
 * Template palette for drag-and-drop flow editing.
 *
 * Features:
 * - Groups templates by category
 * - Search/filter functionality
 * - Drag-and-drop support
 * - Keyboard navigation
 */
export class TemplatePalette {
  private container: HTMLElement;
  private templates: Template[] = [];
  private filteredTemplates: Template[] = [];
  private searchQuery = "";
  private selectedCategory: TemplateCategory | "all" = "all";
  private onTemplateDrop?: (template: Template, position: { x: number; y: number }) => void;
  private onTemplateSelect?: (template: Template) => void;
  private isLoading = false;
  private error: string | null = null;

  constructor(options: TemplatePaletteOptions) {
    this.container = options.container;
    this.onTemplateDrop = options.onTemplateDrop;
    this.onTemplateSelect = options.onTemplateSelect;
  }

  /**
   * Initialize the palette by fetching templates and rendering
   */
  async init(): Promise<void> {
    this.isLoading = true;
    this.render();

    try {
      this.templates = await flowStudioApi.getTemplates();
      this.filteredTemplates = this.templates;
      this.error = null;
    } catch (err) {
      console.error("Failed to load templates", err);
      this.error = "Failed to load templates";
      this.templates = [];
      this.filteredTemplates = [];
    } finally {
      this.isLoading = false;
      this.render();
    }
  }

  /**
   * Refresh templates from API
   */
  async refresh(): Promise<void> {
    await this.init();
  }

  /**
   * Set search query and re-filter
   */
  setSearch(query: string): void {
    this.searchQuery = query.toLowerCase().trim();
    this.applyFilters();
    this.renderTemplateList();
  }

  /**
   * Set category filter
   */
  setCategory(category: TemplateCategory | "all"): void {
    this.selectedCategory = category;
    this.applyFilters();
    this.render();
  }

  /**
   * Apply search and category filters
   */
  private applyFilters(): void {
    this.filteredTemplates = this.templates.filter((template) => {
      // Category filter
      if (this.selectedCategory !== "all" && template.category !== this.selectedCategory) {
        return false;
      }

      // Search filter
      if (this.searchQuery) {
        const searchText = `${template.name} ${template.description} ${template.category}`.toLowerCase();
        if (!searchText.includes(this.searchQuery)) {
          return false;
        }
      }

      return true;
    });
  }

  /**
   * Render the complete palette
   */
  private render(): void {
    this.container.innerHTML = "";
    this.container.className = "template-palette";
    this.container.setAttribute("data-uiid", "flow_studio.palette");

    // Header with search
    const header = this.createHeader();
    this.container.appendChild(header);

    // Category tabs
    const tabs = this.createCategoryTabs();
    this.container.appendChild(tabs);

    // Template list container
    const listContainer = document.createElement("div");
    listContainer.className = "template-palette__list";
    listContainer.setAttribute("data-uiid", "flow_studio.palette.list");
    this.container.appendChild(listContainer);

    this.renderTemplateList();
  }

  /**
   * Create header with search input
   */
  private createHeader(): HTMLElement {
    const header = document.createElement("div");
    header.className = "template-palette__header";

    const title = document.createElement("h3");
    title.className = "template-palette__title";
    title.textContent = "Templates";

    const searchContainer = document.createElement("div");
    searchContainer.className = "template-palette__search";

    const searchInput = document.createElement("input");
    searchInput.type = "text";
    searchInput.placeholder = "Search templates...";
    searchInput.className = "template-palette__search-input";
    searchInput.setAttribute("data-uiid", "flow_studio.palette.search");
    searchInput.value = this.searchQuery;

    // Debounced search
    let debounceTimer: ReturnType<typeof setTimeout> | null = null;
    searchInput.addEventListener("input", (e) => {
      if (debounceTimer) clearTimeout(debounceTimer);
      debounceTimer = setTimeout(() => {
        this.setSearch((e.target as HTMLInputElement).value);
      }, 150);
    });

    searchContainer.appendChild(searchInput);
    header.appendChild(title);
    header.appendChild(searchContainer);

    return header;
  }

  /**
   * Create category tabs
   */
  private createCategoryTabs(): HTMLElement {
    const tabsContainer = document.createElement("div");
    tabsContainer.className = "template-palette__tabs";
    tabsContainer.setAttribute("role", "tablist");

    // "All" tab
    const allTab = this.createCategoryTab("all", "All", "\u{1F4CB}");
    tabsContainer.appendChild(allTab);

    // Category tabs
    for (const category of CATEGORY_ORDER) {
      const meta = CATEGORY_META[category];
      // Only show categories that have templates
      const hasTemplates = this.templates.some((t) => t.category === category);
      if (hasTemplates || this.isLoading) {
        const tab = this.createCategoryTab(category, meta.label, meta.icon);
        tabsContainer.appendChild(tab);
      }
    }

    return tabsContainer;
  }

  /**
   * Create a single category tab
   */
  private createCategoryTab(
    category: TemplateCategory | "all",
    label: string,
    icon: string
  ): HTMLElement {
    const tab = document.createElement("button");
    tab.className = "template-palette__tab";
    tab.setAttribute("role", "tab");
    tab.setAttribute("aria-selected", (this.selectedCategory === category).toString());
    tab.dataset.category = category;

    if (this.selectedCategory === category) {
      tab.classList.add("template-palette__tab--active");
    }

    tab.innerHTML = `<span class="template-palette__tab-icon">${icon}</span><span class="template-palette__tab-label">${label}</span>`;

    tab.addEventListener("click", () => {
      this.setCategory(category);
    });

    return tab;
  }

  /**
   * Render the template list (called on filter changes)
   */
  private renderTemplateList(): void {
    const listContainer = this.container.querySelector(".template-palette__list");
    if (!listContainer) return;

    listContainer.innerHTML = "";

    // Loading state
    if (this.isLoading) {
      listContainer.innerHTML = `
        <div class="template-palette__loading">
          <span class="template-palette__spinner"></span>
          <span>Loading templates...</span>
        </div>
      `;
      return;
    }

    // Error state
    if (this.error) {
      listContainer.innerHTML = `
        <div class="template-palette__error">
          <span class="template-palette__error-icon">\u26A0</span>
          <span>${this.error}</span>
          <button class="template-palette__retry" data-action="retry">Retry</button>
        </div>
      `;
      listContainer.querySelector('[data-action="retry"]')?.addEventListener("click", () => {
        this.init();
      });
      return;
    }

    // Empty state
    if (this.filteredTemplates.length === 0) {
      const emptyMessage = this.searchQuery
        ? `No templates match "${this.searchQuery}"`
        : "No templates available";
      listContainer.innerHTML = `
        <div class="template-palette__empty">
          <span class="template-palette__empty-icon">\u{1F4ED}</span>
          <span>${emptyMessage}</span>
        </div>
      `;
      return;
    }

    // Group by category if showing all
    if (this.selectedCategory === "all") {
      const grouped = this.groupByCategory(this.filteredTemplates);
      for (const category of CATEGORY_ORDER) {
        const templates = grouped.get(category);
        if (templates && templates.length > 0) {
          const group = this.createCategoryGroup(category, templates);
          listContainer.appendChild(group);
        }
      }
    } else {
      // Show flat list for single category
      const grid = this.createTemplateGrid(this.filteredTemplates);
      listContainer.appendChild(grid);
    }
  }

  /**
   * Group templates by category
   */
  private groupByCategory(templates: Template[]): Map<TemplateCategory, Template[]> {
    const groups = new Map<TemplateCategory, Template[]>();

    for (const template of templates) {
      const existing = groups.get(template.category) || [];
      existing.push(template);
      groups.set(template.category, existing);
    }

    return groups;
  }

  /**
   * Create a category group with header and templates
   */
  private createCategoryGroup(category: TemplateCategory, templates: Template[]): HTMLElement {
    const meta = CATEGORY_META[category];
    const group = document.createElement("div");
    group.className = "template-palette__group";
    group.dataset.category = category;

    const header = document.createElement("div");
    header.className = "template-palette__group-header";
    header.innerHTML = `
      <span class="template-palette__group-icon">${meta.icon}</span>
      <span class="template-palette__group-label">${meta.label}</span>
      <span class="template-palette__group-count">${templates.length}</span>
    `;

    const grid = this.createTemplateGrid(templates);

    group.appendChild(header);
    group.appendChild(grid);

    return group;
  }

  /**
   * Create a grid of template cards
   */
  private createTemplateGrid(templates: Template[]): HTMLElement {
    const grid = document.createElement("div");
    grid.className = "template-palette__grid";

    for (const template of templates) {
      const card = this.createTemplateCard(template);
      grid.appendChild(card);
    }

    return grid;
  }

  /**
   * Create a single template card
   */
  private createTemplateCard(template: Template): HTMLElement {
    const card = document.createElement("div");
    card.className = "template-palette__card";
    card.setAttribute("draggable", "true");
    card.setAttribute("role", "button");
    card.setAttribute("tabindex", "0");
    card.setAttribute("aria-label", `Template: ${template.name}`);
    card.dataset.templateId = template.id;

    const meta = CATEGORY_META[template.category];
    const icon = template.icon || meta.icon;

    card.innerHTML = `
      <div class="template-palette__card-icon">${icon}</div>
      <div class="template-palette__card-content">
        <div class="template-palette__card-name">${template.name}</div>
        <div class="template-palette__card-desc">${template.description}</div>
      </div>
    `;

    // Drag start
    card.addEventListener("dragstart", (e) => {
      e.dataTransfer?.setData("application/x-flow-template", JSON.stringify(template));
      e.dataTransfer?.setData("text/plain", template.name);
      card.classList.add("template-palette__card--dragging");
    });

    // Drag end
    card.addEventListener("dragend", () => {
      card.classList.remove("template-palette__card--dragging");
    });

    // Click handler (for accessibility)
    card.addEventListener("click", () => {
      if (this.onTemplateSelect) {
        this.onTemplateSelect(template);
      }
    });

    // Keyboard support
    card.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        if (this.onTemplateSelect) {
          this.onTemplateSelect(template);
        }
      }
    });

    return card;
  }

  /**
   * Destroy the palette and clean up
   */
  destroy(): void {
    this.container.innerHTML = "";
    this.templates = [];
    this.filteredTemplates = [];
  }
}

// ============================================================================
// Factory Function
// ============================================================================

/**
 * Create and initialize a template palette
 */
export async function createTemplatePalette(
  container: HTMLElement,
  options?: Omit<TemplatePaletteOptions, "container">
): Promise<TemplatePalette> {
  const palette = new TemplatePalette({
    container,
    ...options,
  });
  await palette.init();
  return palette;
}

// ============================================================================
// CSS Styles (to be added to flow_studio.css)
// ============================================================================

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
