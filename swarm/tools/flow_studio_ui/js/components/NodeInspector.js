// swarm/tools/flow_studio_ui/src/components/NodeInspector.ts
// Node inspector component for editing flow step properties
//
// Provides an editing form with:
// - Step metadata (ID, role/description, teaching note)
// - Agent assignment (multi-select/tag input)
// - Artifact configuration (required/optional lists)
// - Station assignment (dropdown from station library)
// - Decision point toggle
// - Save/Cancel with validation
//
// NO filesystem operations - all data flows through API.
import { flowStudioApi } from "../api/client.js";
import { escapeHtml } from "../utils.js";
import { getTeachingMode } from "../teaching_mode.js";
// ============================================================================
// Node Inspector Component
// ============================================================================
/**
 * Node inspector for editing flow step properties.
 *
 * Features:
 * - Form-based editing of step properties
 * - Multi-value inputs for agents and artifacts
 * - Station dropdown populated from station library
 * - Validation before save
 * - Loading/error states
 */
export class NodeInspector {
    constructor(options) {
        this.stepData = null;
        this.originalStep = null;
        this.formState = null;
        this.stations = [];
        this.availableAgents = [];
        this.isLoading = false;
        this.isSaving = false;
        this.errorMessage = null;
        this.validationErrors = {};
        this.container = options.container;
        this.flowEditor = options.flowEditor;
        this.flowKey = options.flowKey;
        this.onSave = options.onSave;
        this.onCancel = options.onCancel;
        this.onError = options.onError;
    }
    // ==========================================================================
    // Initialization
    // ==========================================================================
    /**
     * Initialize the inspector with step data
     */
    async init(stepData) {
        this.stepData = stepData;
        this.isLoading = true;
        this.errorMessage = null;
        this.validationErrors = {};
        this.render();
        try {
            // Load stations and flow detail in parallel
            const [stationsResult, flowDetail] = await Promise.all([
                this.loadStations(),
                flowStudioApi.getFlowDetail(this.flowKey),
            ]);
            this.stations = stationsResult;
            // Find the step in the flow detail
            const step = flowDetail.data.steps?.find(s => s.id === stepData.step_id);
            if (step) {
                this.originalStep = step;
                this.formState = this.stepToFormState(step);
            }
            else {
                // Create default form state for new step
                this.formState = this.createDefaultFormState(stepData);
            }
            // Extract available agents from flow
            this.availableAgents = flowDetail.data.agents || [];
            this.isLoading = false;
            this.render();
        }
        catch (err) {
            this.isLoading = false;
            this.errorMessage = err instanceof Error ? err.message : "Failed to load step data";
            if (this.onError && err instanceof Error) {
                this.onError(err);
            }
            this.render();
        }
    }
    /**
     * Load stations from the API
     */
    async loadStations() {
        try {
            // Fetch stations from API
            const response = await fetch("/api/stations");
            if (!response.ok) {
                console.warn("Stations API not available, using empty list");
                return [];
            }
            const data = await response.json();
            return data.stations || [];
        }
        catch (err) {
            console.warn("Failed to load stations:", err);
            return [];
        }
    }
    /**
     * Convert FlowStep to form state
     */
    stepToFormState(step) {
        // Extract required and optional artifacts from the artifacts array
        const requiredArtifacts = [];
        const optionalArtifacts = [];
        // For now, treat all artifacts as required (we can enhance this later)
        if (step.artifacts) {
            step.artifacts.forEach(a => requiredArtifacts.push(a));
        }
        return {
            stepId: step.id,
            role: step.role || "",
            agents: [...(step.agents || [])],
            requiredArtifacts,
            optionalArtifacts,
            teachingNote: step.teaching_note || "",
            isDecisionPoint: false, // Will need to be determined from node data
            stationId: "", // Will need to be loaded from step data
        };
    }
    /**
     * Create default form state for new step
     */
    createDefaultFormState(nodeData) {
        return {
            stepId: nodeData.step_id || "",
            role: "",
            agents: [],
            requiredArtifacts: [],
            optionalArtifacts: [],
            teachingNote: "",
            isDecisionPoint: nodeData.is_decision || false,
            stationId: "",
        };
    }
    // ==========================================================================
    // Rendering
    // ==========================================================================
    /**
     * Render the inspector
     */
    render() {
        this.container.innerHTML = "";
        this.container.className = "node-inspector";
        this.container.setAttribute("data-uiid", "flow_studio.inspector.node_editor");
        // Header
        const header = this.createHeader();
        this.container.appendChild(header);
        // Main content
        if (this.isLoading) {
            this.container.appendChild(this.createLoadingState());
        }
        else if (this.errorMessage) {
            this.container.appendChild(this.createErrorState());
        }
        else if (this.formState) {
            this.container.appendChild(this.createForm());
        }
        // Actions (save/cancel)
        if (!this.isLoading && !this.errorMessage && this.formState) {
            this.container.appendChild(this.createActions());
        }
    }
    /**
     * Create header section
     */
    createHeader() {
        const header = document.createElement("div");
        header.className = "node-inspector__header";
        const title = document.createElement("h3");
        title.className = "node-inspector__title";
        title.textContent = `Edit Step: ${this.stepData?.step_id || ""}`;
        header.appendChild(title);
        return header;
    }
    /**
     * Create loading state
     */
    createLoadingState() {
        const loading = document.createElement("div");
        loading.className = "node-inspector__loading";
        loading.innerHTML = `
      <div class="node-inspector__spinner"></div>
      <span>Loading step data...</span>
    `;
        return loading;
    }
    /**
     * Create error state
     */
    createErrorState() {
        const error = document.createElement("div");
        error.className = "node-inspector__error";
        error.innerHTML = `
      <div class="node-inspector__error-icon">\u26A0</div>
      <div class="node-inspector__error-message">${escapeHtml(this.errorMessage || "Unknown error")}</div>
      <button class="node-inspector__retry-btn">Retry</button>
    `;
        const retryBtn = error.querySelector(".node-inspector__retry-btn");
        if (retryBtn && this.stepData) {
            retryBtn.addEventListener("click", () => this.init(this.stepData));
        }
        return error;
    }
    /**
     * Create the form
     */
    createForm() {
        const form = document.createElement("div");
        form.className = "node-inspector__form";
        // Step ID (read-only)
        form.appendChild(this.createReadOnlyField("Step ID", this.formState.stepId, "step-id"));
        // Role/Description
        form.appendChild(this.createTextareaField("Role / Description", this.formState.role, "role", "What this step does...", (value) => { this.formState.role = value; this.clearFieldError("role"); }));
        // Assigned Agents (tag input)
        form.appendChild(this.createTagInputField("Assigned Agents", this.formState.agents, "agents", this.availableAgents, (agents) => { this.formState.agents = agents; this.clearFieldError("agents"); }));
        // Required Artifacts
        form.appendChild(this.createListEditorField("Required Artifacts", this.formState.requiredArtifacts, "required-artifacts", "artifact_name.md", (artifacts) => { this.formState.requiredArtifacts = artifacts; }));
        // Optional Artifacts
        form.appendChild(this.createListEditorField("Optional Artifacts", this.formState.optionalArtifacts, "optional-artifacts", "optional_artifact.md", (artifacts) => { this.formState.optionalArtifacts = artifacts; }));
        // Teaching Note (only shown in teaching mode or always for editing)
        const teachingNoteSection = this.createTextareaField("Teaching Note", this.formState.teachingNote, "teaching-note", "Explain what to look for in this step...", (value) => { this.formState.teachingNote = value; });
        if (!getTeachingMode()) {
            teachingNoteSection.classList.add("node-inspector__field--collapsed");
        }
        form.appendChild(teachingNoteSection);
        // Is Decision Point
        form.appendChild(this.createCheckboxField("Is Decision Point", this.formState.isDecisionPoint, "is-decision", "Mark this step as a decision point in the flow", (checked) => { this.formState.isDecisionPoint = checked; }));
        // Station ID (dropdown)
        form.appendChild(this.createDropdownField("Station ID", this.formState.stationId, "station-id", this.stations.map(s => ({
            value: s.station_id,
            label: `${s.name} (${s.category})`,
            description: s.description
        })), (value) => { this.formState.stationId = value; this.clearFieldError("stationId"); }));
        return form;
    }
    /**
     * Create read-only field
     */
    createReadOnlyField(label, value, id) {
        const field = document.createElement("div");
        field.className = "node-inspector__field";
        field.innerHTML = `
      <label class="node-inspector__label">${escapeHtml(label)}</label>
      <div class="node-inspector__readonly mono" data-field="${id}">${escapeHtml(value)}</div>
    `;
        return field;
    }
    /**
     * Create textarea field
     */
    createTextareaField(label, value, id, placeholder, onChange) {
        const field = document.createElement("div");
        field.className = "node-inspector__field";
        const errorHtml = this.validationErrors[id]
            ? `<div class="node-inspector__field-error">${escapeHtml(this.validationErrors[id])}</div>`
            : "";
        field.innerHTML = `
      <label class="node-inspector__label" for="inspector-${id}">${escapeHtml(label)}</label>
      <textarea
        id="inspector-${id}"
        class="node-inspector__textarea ${this.validationErrors[id] ? "node-inspector__input--error" : ""}"
        placeholder="${escapeHtml(placeholder)}"
        rows="3"
      >${escapeHtml(value)}</textarea>
      ${errorHtml}
    `;
        const textarea = field.querySelector("textarea");
        if (textarea) {
            textarea.addEventListener("input", (e) => {
                onChange(e.target.value);
            });
        }
        return field;
    }
    /**
     * Create tag input field for multi-value selection
     */
    createTagInputField(label, values, id, suggestions, onChange) {
        const field = document.createElement("div");
        field.className = "node-inspector__field";
        const errorHtml = this.validationErrors[id]
            ? `<div class="node-inspector__field-error">${escapeHtml(this.validationErrors[id])}</div>`
            : "";
        field.innerHTML = `
      <label class="node-inspector__label">${escapeHtml(label)}</label>
      <div class="node-inspector__tag-input ${this.validationErrors[id] ? "node-inspector__input--error" : ""}" data-field="${id}">
        <div class="node-inspector__tags"></div>
        <input
          type="text"
          class="node-inspector__tag-input-field"
          placeholder="Add agent..."
          list="suggestions-${id}"
        />
        <datalist id="suggestions-${id}">
          ${suggestions.map(s => `<option value="${escapeHtml(s)}">`).join("")}
        </datalist>
      </div>
      ${errorHtml}
    `;
        const tagsContainer = field.querySelector(".node-inspector__tags");
        const input = field.querySelector(".node-inspector__tag-input-field");
        // Render existing tags
        const renderTags = () => {
            tagsContainer.innerHTML = values.map(v => `
        <span class="node-inspector__tag">
          ${escapeHtml(v)}
          <button type="button" class="node-inspector__tag-remove" data-value="${escapeHtml(v)}">\u00D7</button>
        </span>
      `).join("");
            // Add remove handlers
            tagsContainer.querySelectorAll(".node-inspector__tag-remove").forEach(btn => {
                btn.addEventListener("click", (e) => {
                    const value = e.target.dataset.value;
                    if (value) {
                        const idx = values.indexOf(value);
                        if (idx >= 0) {
                            values.splice(idx, 1);
                            onChange([...values]);
                            renderTags();
                        }
                    }
                });
            });
        };
        renderTags();
        // Handle input
        input.addEventListener("keydown", (e) => {
            if (e.key === "Enter" || e.key === ",") {
                e.preventDefault();
                const newValue = input.value.trim();
                if (newValue && !values.includes(newValue)) {
                    values.push(newValue);
                    onChange([...values]);
                    renderTags();
                }
                input.value = "";
            }
            else if (e.key === "Backspace" && !input.value && values.length > 0) {
                values.pop();
                onChange([...values]);
                renderTags();
            }
        });
        return field;
    }
    /**
     * Create list editor field
     */
    createListEditorField(label, values, id, placeholder, onChange) {
        const field = document.createElement("div");
        field.className = "node-inspector__field";
        field.innerHTML = `
      <label class="node-inspector__label">${escapeHtml(label)}</label>
      <div class="node-inspector__list-editor" data-field="${id}">
        <div class="node-inspector__list-items"></div>
        <div class="node-inspector__list-add">
          <input type="text" class="node-inspector__list-add-input" placeholder="${escapeHtml(placeholder)}" />
          <button type="button" class="node-inspector__list-add-btn">+</button>
        </div>
      </div>
    `;
        const itemsContainer = field.querySelector(".node-inspector__list-items");
        const addInput = field.querySelector(".node-inspector__list-add-input");
        const addBtn = field.querySelector(".node-inspector__list-add-btn");
        // Render items
        const renderItems = () => {
            itemsContainer.innerHTML = values.map((v, i) => `
        <div class="node-inspector__list-item">
          <span class="node-inspector__list-item-text mono">${escapeHtml(v)}</span>
          <button type="button" class="node-inspector__list-item-remove" data-index="${i}">\u00D7</button>
        </div>
      `).join("");
            // Add remove handlers
            itemsContainer.querySelectorAll(".node-inspector__list-item-remove").forEach(btn => {
                btn.addEventListener("click", (e) => {
                    const index = parseInt(e.target.dataset.index || "0", 10);
                    values.splice(index, 1);
                    onChange([...values]);
                    renderItems();
                });
            });
        };
        renderItems();
        // Add new item
        const addItem = () => {
            const newValue = addInput.value.trim();
            if (newValue && !values.includes(newValue)) {
                values.push(newValue);
                onChange([...values]);
                renderItems();
            }
            addInput.value = "";
        };
        addBtn.addEventListener("click", addItem);
        addInput.addEventListener("keydown", (e) => {
            if (e.key === "Enter") {
                e.preventDefault();
                addItem();
            }
        });
        return field;
    }
    /**
     * Create checkbox field
     */
    createCheckboxField(label, checked, id, description, onChange) {
        const field = document.createElement("div");
        field.className = "node-inspector__field node-inspector__field--checkbox";
        field.innerHTML = `
      <label class="node-inspector__checkbox-label">
        <input type="checkbox" id="inspector-${id}" ${checked ? "checked" : ""} />
        <span class="node-inspector__checkbox-text">${escapeHtml(label)}</span>
      </label>
      <div class="node-inspector__field-description">${escapeHtml(description)}</div>
    `;
        const checkbox = field.querySelector("input");
        if (checkbox) {
            checkbox.addEventListener("change", (e) => {
                onChange(e.target.checked);
            });
        }
        return field;
    }
    /**
     * Create dropdown field
     */
    createDropdownField(label, value, id, options, onChange) {
        const field = document.createElement("div");
        field.className = "node-inspector__field";
        const errorHtml = this.validationErrors[id]
            ? `<div class="node-inspector__field-error">${escapeHtml(this.validationErrors[id])}</div>`
            : "";
        field.innerHTML = `
      <label class="node-inspector__label" for="inspector-${id}">${escapeHtml(label)}</label>
      <select
        id="inspector-${id}"
        class="node-inspector__select ${this.validationErrors[id] ? "node-inspector__input--error" : ""}"
      >
        <option value="">-- Select station --</option>
        ${options.map(opt => `
          <option value="${escapeHtml(opt.value)}" ${opt.value === value ? "selected" : ""}>
            ${escapeHtml(opt.label)}
          </option>
        `).join("")}
      </select>
      ${errorHtml}
    `;
        const select = field.querySelector("select");
        if (select) {
            select.addEventListener("change", (e) => {
                onChange(e.target.value);
            });
        }
        return field;
    }
    /**
     * Create action buttons
     */
    createActions() {
        const actions = document.createElement("div");
        actions.className = "node-inspector__actions";
        const cancelBtn = document.createElement("button");
        cancelBtn.className = "node-inspector__btn node-inspector__btn--secondary";
        cancelBtn.textContent = "Cancel";
        cancelBtn.disabled = this.isSaving;
        cancelBtn.addEventListener("click", () => {
            if (this.onCancel) {
                this.onCancel();
            }
        });
        const saveBtn = document.createElement("button");
        saveBtn.className = "node-inspector__btn node-inspector__btn--primary";
        saveBtn.innerHTML = this.isSaving
            ? '<span class="node-inspector__btn-spinner"></span> Saving...'
            : "Save Changes";
        saveBtn.disabled = this.isSaving;
        saveBtn.addEventListener("click", () => this.handleSave());
        actions.appendChild(cancelBtn);
        actions.appendChild(saveBtn);
        return actions;
    }
    // ==========================================================================
    // Validation
    // ==========================================================================
    /**
     * Validate the form
     */
    validate() {
        const errors = {};
        if (!this.formState) {
            return { valid: false, errors: { form: "Form not initialized" } };
        }
        // Role is required
        if (!this.formState.role.trim()) {
            errors.role = "Role/Description is required";
        }
        // At least one agent should be assigned
        if (this.formState.agents.length === 0) {
            errors.agents = "At least one agent must be assigned";
        }
        // Validate station_id if provided
        if (this.formState.stationId) {
            const stationExists = this.stations.some(s => s.station_id === this.formState.stationId);
            if (!stationExists && this.stations.length > 0) {
                errors.stationId = "Invalid station ID";
            }
        }
        return {
            valid: Object.keys(errors).length === 0,
            errors
        };
    }
    /**
     * Clear a field error
     */
    clearFieldError(field) {
        delete this.validationErrors[field];
    }
    // ==========================================================================
    // Save
    // ==========================================================================
    /**
     * Handle save button click
     */
    async handleSave() {
        if (!this.formState || !this.stepData)
            return;
        // Validate
        const validation = this.validate();
        if (!validation.valid) {
            this.validationErrors = validation.errors;
            this.render();
            return;
        }
        this.isSaving = true;
        this.errorMessage = null;
        this.render();
        try {
            // Prepare update object
            const updates = {
                role: this.formState.role,
                agents: this.formState.agents,
                artifacts: [
                    ...this.formState.requiredArtifacts,
                    ...this.formState.optionalArtifacts
                ],
                teaching_note: this.formState.teachingNote || undefined,
            };
            // Call FlowEditor.updateStep()
            const result = await this.flowEditor.updateStep(this.formState.stepId, updates);
            this.isSaving = false;
            // Find the updated step
            const updatedStep = result.steps?.find(s => s.id === this.formState.stepId);
            if (updatedStep && this.onSave) {
                this.onSave(updatedStep);
            }
            this.render();
        }
        catch (err) {
            this.isSaving = false;
            this.errorMessage = err instanceof Error ? err.message : "Failed to save changes";
            if (this.onError && err instanceof Error) {
                this.onError(err);
            }
            this.render();
        }
    }
    // ==========================================================================
    // Public API
    // ==========================================================================
    /**
     * Get current form state
     */
    getFormState() {
        return this.formState ? { ...this.formState } : null;
    }
    /**
     * Check if form has unsaved changes
     */
    isDirty() {
        if (!this.formState || !this.originalStep)
            return false;
        return (this.formState.role !== (this.originalStep.role || "") ||
            JSON.stringify(this.formState.agents) !== JSON.stringify(this.originalStep.agents || []) ||
            this.formState.teachingNote !== (this.originalStep.teaching_note || ""));
    }
    /**
     * Reset form to original values
     */
    reset() {
        if (this.originalStep) {
            this.formState = this.stepToFormState(this.originalStep);
            this.validationErrors = {};
            this.errorMessage = null;
            this.render();
        }
    }
    /**
     * Destroy the inspector and clean up
     */
    destroy() {
        this.container.innerHTML = "";
        this.stepData = null;
        this.originalStep = null;
        this.formState = null;
        this.stations = [];
        this.availableAgents = [];
    }
}
// ============================================================================
// Factory Function
// ============================================================================
/**
 * Create and initialize a node inspector
 */
export async function createNodeInspector(container, stepData, options) {
    const inspector = new NodeInspector({
        container,
        ...options,
    });
    await inspector.init(stepData);
    return inspector;
}
// ============================================================================
// CSS Class Names Reference
// ============================================================================
/**
 * CSS class names used by this component:
 *
 * .node-inspector - Main container
 * .node-inspector__header - Header section
 * .node-inspector__title - Title text
 * .node-inspector__loading - Loading state container
 * .node-inspector__spinner - Loading spinner
 * .node-inspector__error - Error state container
 * .node-inspector__error-icon - Error icon
 * .node-inspector__error-message - Error message text
 * .node-inspector__retry-btn - Retry button
 * .node-inspector__form - Form container
 * .node-inspector__field - Form field wrapper
 * .node-inspector__field--checkbox - Checkbox field variant
 * .node-inspector__field--collapsed - Collapsed field (hidden by default)
 * .node-inspector__label - Field label
 * .node-inspector__readonly - Read-only field display
 * .node-inspector__textarea - Textarea input
 * .node-inspector__select - Select dropdown
 * .node-inspector__input--error - Input with error
 * .node-inspector__field-error - Error message for field
 * .node-inspector__field-description - Field helper text
 * .node-inspector__tag-input - Tag input container
 * .node-inspector__tags - Tags display area
 * .node-inspector__tag - Individual tag
 * .node-inspector__tag-remove - Tag remove button
 * .node-inspector__tag-input-field - Tag input field
 * .node-inspector__list-editor - List editor container
 * .node-inspector__list-items - List items container
 * .node-inspector__list-item - Individual list item
 * .node-inspector__list-item-text - List item text
 * .node-inspector__list-item-remove - List item remove button
 * .node-inspector__list-add - Add item row
 * .node-inspector__list-add-input - Add item input
 * .node-inspector__list-add-btn - Add item button
 * .node-inspector__checkbox-label - Checkbox label wrapper
 * .node-inspector__checkbox-text - Checkbox label text
 * .node-inspector__actions - Action buttons container
 * .node-inspector__btn - Button base
 * .node-inspector__btn--primary - Primary button
 * .node-inspector__btn--secondary - Secondary button
 * .node-inspector__btn-spinner - Button loading spinner
 */
