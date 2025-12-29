"""
swarm/spec - Spec-first architecture for stepwise execution.

This package provides the specification layer for the industrialized SDLC:
- StationSpec: Contract + runtime profile for execution roles
- FlowSpec: Orchestrator spine with routing configuration
- Fragments: Reusable prompt components
- Compiler: Assembles specs + context into SDK inputs
- Manager: Central authority for spec file operations (ADR-001)

Usage:
    from swarm.spec import (
        # Types
        StationSpec,
        FlowSpec,
        PromptPlan,
        FlowGraph,
        StepTemplate,
        # Loader
        load_station,
        load_flow,
        # Compiler
        compile_prompt,
        # Manager (central authority for spec writes)
        SpecManager,
        get_manager,
    )

    # Use SpecManager for all spec file operations
    manager = get_manager()
    graph = manager.get_flow_graph("build-flow")
    errors = manager.validate_spec("flow_graph", graph_data)
    new_etag = manager.save_flow_graph("build-flow", data, etag=old_etag)
"""

from .types import (
    StationSpec,
    StationSDK,
    StationIdentity,
    StationIO,
    StationHandoff,
    StationRuntimePrompt,
    FlowSpec,
    FlowStep,
    FlowDefaults,
    RoutingConfig,
    PromptPlan,
)

from .loader import (
    load_station,
    load_flow,
    load_fragment,
    list_stations,
    list_flows,
    validate_specs,
)

from .compiler import (
    compile_prompt,
    SpecCompiler,
    # Template library functions (WP2)
    list_templates,
    load_template,
    expand_template,
    expand_flow_graph,
    get_template_categories,
    TemplateMetadata,
    ExpandedTemplate,
)

from .manager import (
    # Main class
    SpecManager,
    # FlowGraph Manager (WP3)
    FlowSpecManager,
    # Data types
    FlowGraph,
    StepTemplate,
    ValidationError,
    ValidationResult,
    # Errors
    SpecError,
    SpecNotFoundError,
    SpecValidationError,
    ConcurrencyError,
    # Convenience functions
    get_manager,
    reset_manager,
    # FlowGraph merge/shred functions (WP3)
    get_flow_manager,
    merge_flow_with_overlay,
    shred_flow_update,
    load_flow_graph,
    load_ui_overlay,
    list_flows as list_flow_graphs,  # Alias for WP3 API
)

__all__ = [
    # Types (dataclasses)
    "StationSpec",
    "StationSDK",
    "StationIdentity",
    "StationIO",
    "StationHandoff",
    "StationRuntimePrompt",
    "FlowSpec",
    "FlowStep",
    "FlowDefaults",
    "RoutingConfig",
    "PromptPlan",
    # Loader
    "load_station",
    "load_flow",
    "load_fragment",
    "list_stations",
    "list_flows",
    "validate_specs",
    # Compiler
    "compile_prompt",
    "SpecCompiler",
    # Template library functions (WP2)
    "list_templates",
    "load_template",
    "expand_template",
    "expand_flow_graph",
    "get_template_categories",
    "TemplateMetadata",
    "ExpandedTemplate",
    # Manager (ADR-001: central authority for spec writes)
    "SpecManager",
    "FlowGraph",
    "StepTemplate",
    "ValidationError",
    "ValidationResult",
    "SpecError",
    "SpecNotFoundError",
    "SpecValidationError",
    "ConcurrencyError",
    "get_manager",
    "reset_manager",
    # FlowGraph Manager (WP3)
    "FlowSpecManager",
    "get_flow_manager",
    "merge_flow_with_overlay",
    "shred_flow_update",
    "load_flow_graph",
    "load_ui_overlay",
    "list_flow_graphs",
]
