import type { FlowEditor } from "./FlowEditor.js";
import type { FlowKey, FlowStep, NodeData } from "../domain.js";
/**
 * Form state for the step editor
 */
interface StepFormState {
    stepId: string;
    role: string;
    agents: string[];
    requiredArtifacts: string[];
    optionalArtifacts: string[];
    teachingNote: string;
    isDecisionPoint: boolean;
    stationId: string;
}
/**
 * Inspector options
 */
interface NodeInspectorOptions {
    /** Container element to render into */
    container: HTMLElement;
    /** Flow editor instance for save operations */
    flowEditor: FlowEditor;
    /** Current flow key */
    flowKey: FlowKey;
    /** Callback when save completes */
    onSave?: (step: FlowStep) => void;
    /** Callback when cancel is clicked */
    onCancel?: () => void;
    /** Callback on error */
    onError?: (error: Error) => void;
}
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
export declare class NodeInspector {
    private container;
    private flowEditor;
    private flowKey;
    private onSave?;
    private onCancel?;
    private onError?;
    private stepData;
    private originalStep;
    private formState;
    private stations;
    private availableAgents;
    private isLoading;
    private isSaving;
    private errorMessage;
    private validationErrors;
    constructor(options: NodeInspectorOptions);
    /**
     * Initialize the inspector with step data
     */
    init(stepData: NodeData): Promise<void>;
    /**
     * Load stations from the API
     */
    private loadStations;
    /**
     * Convert FlowStep to form state
     */
    private stepToFormState;
    /**
     * Create default form state for new step
     */
    private createDefaultFormState;
    /**
     * Render the inspector
     */
    private render;
    /**
     * Create header section
     */
    private createHeader;
    /**
     * Create loading state
     */
    private createLoadingState;
    /**
     * Create error state
     */
    private createErrorState;
    /**
     * Create the form
     */
    private createForm;
    /**
     * Create read-only field
     */
    private createReadOnlyField;
    /**
     * Create textarea field
     */
    private createTextareaField;
    /**
     * Create tag input field for multi-value selection
     */
    private createTagInputField;
    /**
     * Create list editor field
     */
    private createListEditorField;
    /**
     * Create checkbox field
     */
    private createCheckboxField;
    /**
     * Create dropdown field
     */
    private createDropdownField;
    /**
     * Create action buttons
     */
    private createActions;
    /**
     * Validate the form
     */
    private validate;
    /**
     * Clear a field error
     */
    private clearFieldError;
    /**
     * Handle save button click
     */
    private handleSave;
    /**
     * Get current form state
     */
    getFormState(): StepFormState | null;
    /**
     * Check if form has unsaved changes
     */
    isDirty(): boolean;
    /**
     * Reset form to original values
     */
    reset(): void;
    /**
     * Destroy the inspector and clean up
     */
    destroy(): void;
}
/**
 * Create and initialize a node inspector
 */
export declare function createNodeInspector(container: HTMLElement, stepData: NodeData, options: Omit<NodeInspectorOptions, "container">): Promise<NodeInspector>;
export {};
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
