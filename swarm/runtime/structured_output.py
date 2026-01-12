"""
structured_output.py - Structured output extraction with validation microloop.

For transports that don't support native output_format, this module provides
a microloop that validates responses against JSON schemas and reprompts
on validation failures.

The microloop pattern:
1. Send prompt requesting JSON output
2. Attempt to extract JSON from response (handles markdown fences)
3. Validate extracted JSON against provided schema
4. If invalid, build a reprompt with validation errors and retry
5. Return after success or max_attempts exhausted

This enables reliable structured output from CLI-based transports
(Gemini CLI, Claude CLI) that lack native schema enforcement.

Example usage:
    from swarm.runtime.structured_output import extract_with_microloop

    schema = {
        "type": "object",
        "required": ["status", "summary"],
        "properties": {
            "status": {"type": "string", "enum": ["VERIFIED", "UNVERIFIED", "BLOCKED"]},
            "summary": {"type": "string"},
        }
    }

    result = await extract_with_microloop(
        prompt="Analyze the code and return your assessment as JSON.",
        schema=schema,
        query_fn=my_llm_query_function,
        max_attempts=3,
    )

    if result.success:
        print(result.data)  # {"status": "VERIFIED", "summary": "..."}
    else:
        print(f"Failed after {result.attempts} attempts: {result.errors}")
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple, Union

logger = logging.getLogger(__name__)


@dataclass
class ValidationError:
    """A single validation error from schema validation.

    Attributes:
        path: JSON path to the error location, e.g., "$.status" or "$.items[0].name"
        message: Human-readable error message explaining what's wrong
        value: The invalid value that caused the error (if available)
    """

    path: str
    message: str
    value: Any = None

    def __str__(self) -> str:
        if self.value is not None:
            return f"{self.path}: {self.message} (got: {self.value!r})"
        return f"{self.path}: {self.message}"


@dataclass
class ExtractionResult:
    """Result of structured output extraction.

    Attributes:
        success: Whether extraction and validation succeeded
        data: The extracted and validated data (None if failed)
        errors: List of validation errors from the final attempt
        attempts: Number of extraction attempts made
        raw_responses: List of raw LLM responses for debugging
    """

    success: bool
    data: Optional[Dict[str, Any]] = None
    errors: List[ValidationError] = field(default_factory=list)
    attempts: int = 0
    raw_responses: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        # Ensure mutable defaults are properly initialized
        if self.errors is None:
            self.errors = []
        if self.raw_responses is None:
            self.raw_responses = []


def _find_json_candidates(text: str) -> List[str]:
    """Find potential JSON object substrings by tracking balanced braces.

    This function scans the text for opening braces and extracts substrings
    with balanced braces that could be valid JSON objects.

    Args:
        text: The text to scan for JSON objects.

    Returns:
        List of candidate JSON strings, in order of appearance.
    """
    candidates: List[str] = []
    i = 0
    n = len(text)

    while i < n:
        if text[i] == "{":
            # Found opening brace, try to find matching close
            depth = 0
            start = i
            in_string = False
            escape_next = False

            j = i
            while j < n:
                char = text[j]

                if escape_next:
                    escape_next = False
                    j += 1
                    continue

                if char == "\\":
                    escape_next = True
                    j += 1
                    continue

                if char == '"' and not escape_next:
                    in_string = not in_string
                elif not in_string:
                    if char == "{":
                        depth += 1
                    elif char == "}":
                        depth -= 1
                        if depth == 0:
                            # Found complete JSON object candidate
                            candidates.append(text[start : j + 1])
                            i = j  # Continue from here
                            break

                j += 1

            if depth != 0:
                # Unbalanced braces, skip this opening brace
                pass

        i += 1

    return candidates


def extract_json_from_text(text: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Extract JSON from text, handling markdown fences and raw JSON.

    Attempts extraction in order of preference:
    1. JSON inside ```json ... ``` fence
    2. JSON inside generic ``` ... ``` fence
    3. First { ... } block in the text
    4. Raw text as JSON (if it starts with { or [)

    Args:
        text: The text to extract JSON from.

    Returns:
        Tuple of (parsed_dict, error_message).
        If successful: (dict, None)
        If failed: (None, error_message)
    """
    if not text or not text.strip():
        return None, "Empty response received"

    text = text.strip()

    # Strategy 1: Look for ```json ... ``` fence
    json_fence_pattern = r"```json\s*([\s\S]*?)\s*```"
    json_fence_match = re.search(json_fence_pattern, text)
    if json_fence_match:
        json_str = json_fence_match.group(1).strip()
        try:
            data = json.loads(json_str)
            if isinstance(data, dict):
                return data, None
            return None, f"Expected JSON object, got {type(data).__name__}"
        except json.JSONDecodeError as e:
            # Continue to try other strategies
            pass

    # Strategy 2: Look for generic ``` ... ``` fence
    generic_fence_pattern = r"```\s*([\s\S]*?)\s*```"
    generic_fence_match = re.search(generic_fence_pattern, text)
    if generic_fence_match:
        json_str = generic_fence_match.group(1).strip()
        # Skip if it looks like code (common language markers)
        if not json_str.startswith(("def ", "class ", "function ", "import ", "const ", "let ", "var ")):
            try:
                data = json.loads(json_str)
                if isinstance(data, dict):
                    return data, None
            except json.JSONDecodeError:
                pass

    # Strategy 3: Find JSON objects by looking for balanced braces
    # This handles multiple JSON objects in text correctly
    json_candidates = _find_json_candidates(text)
    for candidate in json_candidates:
        try:
            data = json.loads(candidate)
            if isinstance(data, dict):
                return data, None
        except json.JSONDecodeError:
            continue

    # Strategy 4: Try raw text if it starts with { or [
    if text.startswith("{") or text.startswith("["):
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                return data, None
            return None, f"Expected JSON object, got {type(data).__name__}"
        except json.JSONDecodeError as e:
            return None, f"Invalid JSON: {e.msg} at position {e.pos}"

    return None, "No valid JSON found in response"


def validate_against_schema(
    data: Dict[str, Any],
    schema: Dict[str, Any],
    path_prefix: str = "$",
) -> List[ValidationError]:
    """Validate data against a JSON schema.

    Returns list of validation errors (empty if valid).

    Note: This is a simplified validator for common cases:
    - Required fields
    - Type checking (string, number, integer, boolean, array, object, null)
    - Enum validation
    - Nested object validation
    - Array item validation

    For full JSON Schema Draft-07 compliance, use the jsonschema library.

    Args:
        data: The data to validate.
        schema: The JSON schema to validate against.
        path_prefix: Path prefix for error reporting (default: "$").

    Returns:
        List of ValidationError instances (empty if validation passes).
    """
    errors: List[ValidationError] = []

    if not isinstance(data, dict):
        errors.append(
            ValidationError(
                path=path_prefix,
                message=f"Expected object, got {type(data).__name__}",
                value=data,
            )
        )
        return errors

    # Check required fields
    required = schema.get("required", [])
    for field_name in required:
        if field_name not in data:
            errors.append(
                ValidationError(
                    path=f"{path_prefix}.{field_name}",
                    message=f"Required field '{field_name}' is missing",
                )
            )

    # Check types and constraints for present fields
    properties = schema.get("properties", {})

    for field_name, value in data.items():
        field_path = f"{path_prefix}.{field_name}"

        if field_name not in properties:
            # Skip unknown fields (additionalProperties not enforced)
            continue

        prop_schema = properties[field_name]

        # Check null first (can be combined with other types)
        if value is None:
            nullable = prop_schema.get("nullable", False)
            prop_type = prop_schema.get("type")
            if prop_type == "null" or nullable:
                continue  # null is allowed
            if prop_type is not None:
                errors.append(
                    ValidationError(
                        path=field_path,
                        message=f"Value cannot be null (expected type '{prop_type}')",
                        value=value,
                    )
                )
            continue

        # Check enum constraint
        if "enum" in prop_schema:
            allowed_values = prop_schema["enum"]
            if value not in allowed_values:
                errors.append(
                    ValidationError(
                        path=field_path,
                        message=f"Value '{value}' not in allowed values: {allowed_values}",
                        value=value,
                    )
                )

        # Check type constraint
        expected_type = prop_schema.get("type")
        if expected_type:
            # Map JSON schema types to Python types
            type_map: Dict[str, Union[type, Tuple[type, ...]]] = {
                "string": str,
                "number": (int, float),
                "integer": int,
                "boolean": bool,
                "array": list,
                "object": dict,
                "null": type(None),
            }

            if expected_type in type_map:
                expected_python_type = type_map[expected_type]
                if not isinstance(value, expected_python_type):
                    # Special case: integer type accepts int but not float
                    if expected_type == "integer" and isinstance(value, float) and value.is_integer():
                        # Accept whole-number floats as integers
                        pass
                    else:
                        errors.append(
                            ValidationError(
                                path=field_path,
                                message=f"Expected type '{expected_type}', got '{type(value).__name__}'",
                                value=value,
                            )
                        )

        # Recursively validate nested objects
        if prop_schema.get("type") == "object" and isinstance(value, dict):
            nested_errors = validate_against_schema(value, prop_schema, field_path)
            errors.extend(nested_errors)

        # Validate array items
        if prop_schema.get("type") == "array" and isinstance(value, list):
            items_schema = prop_schema.get("items")
            if items_schema:
                for idx, item in enumerate(value):
                    item_path = f"{field_path}[{idx}]"
                    if items_schema.get("type") == "object" and isinstance(item, dict):
                        nested_errors = validate_against_schema(item, items_schema, item_path)
                        errors.extend(nested_errors)
                    elif "type" in items_schema:
                        item_type = items_schema["type"]
                        if item_type in type_map:
                            if not isinstance(item, type_map[item_type]):
                                errors.append(
                                    ValidationError(
                                        path=item_path,
                                        message=f"Expected array item type '{item_type}', got '{type(item).__name__}'",
                                        value=item,
                                    )
                                )
                    if "enum" in items_schema and item not in items_schema["enum"]:
                        errors.append(
                            ValidationError(
                                path=item_path,
                                message=f"Array item '{item}' not in allowed values: {items_schema['enum']}",
                                value=item,
                            )
                        )

        # Check string constraints
        if expected_type == "string" and isinstance(value, str):
            min_length = prop_schema.get("minLength")
            max_length = prop_schema.get("maxLength")
            pattern = prop_schema.get("pattern")

            if min_length is not None and len(value) < min_length:
                errors.append(
                    ValidationError(
                        path=field_path,
                        message=f"String length {len(value)} is less than minimum {min_length}",
                        value=value,
                    )
                )
            if max_length is not None and len(value) > max_length:
                errors.append(
                    ValidationError(
                        path=field_path,
                        message=f"String length {len(value)} exceeds maximum {max_length}",
                        value=value,
                    )
                )
            if pattern is not None:
                if not re.match(pattern, value):
                    errors.append(
                        ValidationError(
                            path=field_path,
                            message=f"String does not match pattern '{pattern}'",
                            value=value,
                        )
                    )

        # Check numeric constraints
        if expected_type in ("number", "integer") and isinstance(value, (int, float)):
            minimum = prop_schema.get("minimum")
            maximum = prop_schema.get("maximum")
            exclusive_minimum = prop_schema.get("exclusiveMinimum")
            exclusive_maximum = prop_schema.get("exclusiveMaximum")

            if minimum is not None and value < minimum:
                errors.append(
                    ValidationError(
                        path=field_path,
                        message=f"Value {value} is less than minimum {minimum}",
                        value=value,
                    )
                )
            if maximum is not None and value > maximum:
                errors.append(
                    ValidationError(
                        path=field_path,
                        message=f"Value {value} exceeds maximum {maximum}",
                        value=value,
                    )
                )
            if exclusive_minimum is not None and value <= exclusive_minimum:
                errors.append(
                    ValidationError(
                        path=field_path,
                        message=f"Value {value} must be greater than {exclusive_minimum}",
                        value=value,
                    )
                )
            if exclusive_maximum is not None and value >= exclusive_maximum:
                errors.append(
                    ValidationError(
                        path=field_path,
                        message=f"Value {value} must be less than {exclusive_maximum}",
                        value=value,
                    )
                )

    return errors


def build_reprompt(
    original_prompt: str,
    schema: Dict[str, Any],
    errors: List[ValidationError],
    previous_response: str,
) -> str:
    """Build a reprompt that includes validation errors.

    This helps the model understand what went wrong and fix it.
    The reprompt includes:
    - List of specific validation errors
    - Truncated previous response showing what was wrong
    - Schema requirements as a reminder
    - Clear instruction to respond with valid JSON only

    Args:
        original_prompt: The original prompt that was sent.
        schema: The JSON schema the response must conform to.
        errors: List of ValidationError instances from the failed attempt.
        previous_response: The raw response that failed validation.

    Returns:
        A formatted reprompt string.
    """
    # Format error list
    error_lines = []
    for err in errors:
        error_lines.append(f"  - {err}")

    # Truncate previous response for context
    max_response_preview = 500
    response_preview = previous_response[:max_response_preview]
    if len(previous_response) > max_response_preview:
        response_preview += "..."

    # Extract required fields from schema
    required_fields = schema.get("required", [])
    properties = schema.get("properties", {})

    # Build field hints
    field_hints = []
    for field_name in required_fields:
        prop = properties.get(field_name, {})
        hint = f"  - {field_name}"
        if "type" in prop:
            hint += f" ({prop['type']})"
        if "enum" in prop:
            hint += f" - one of: {prop['enum']}"
        field_hints.append(hint)

    reprompt = f"""Your previous response had validation errors:

{chr(10).join(error_lines)}

Previous response (invalid):
```
{response_preview}
```

Please provide a valid JSON response that matches the required schema.

Required fields:
{chr(10).join(field_hints) if field_hints else "  (see schema)"}

IMPORTANT: Respond with ONLY valid JSON. Do not include any explanation, markdown fences, or other text. Just the raw JSON object starting with {{ and ending with }}."""

    return reprompt


async def extract_with_microloop(
    prompt: str,
    schema: Dict[str, Any],
    query_fn: Callable[[str], Awaitable[str]],
    max_attempts: int = 3,
    log: Optional[logging.Logger] = None,
) -> ExtractionResult:
    """Extract structured output with validation microloop.

    This function implements a retry loop that:
    1. Sends the prompt to the LLM
    2. Extracts JSON from the response
    3. Validates against the schema
    4. If invalid, builds a reprompt with error details and retries
    5. Returns after success or max_attempts exhausted

    Args:
        prompt: The initial prompt to send (should request JSON output).
        schema: JSON schema to validate the response against.
        query_fn: Async function that sends a prompt and returns the response.
            Signature: async def query_fn(prompt: str) -> str
        max_attempts: Maximum number of retry attempts (default: 3).
        log: Optional logger instance (uses module logger if not provided).

    Returns:
        ExtractionResult with:
        - success: True if valid JSON was extracted
        - data: The validated JSON data (or None if failed)
        - errors: Validation errors from the final attempt
        - attempts: Number of attempts made
        - raw_responses: All raw responses for debugging

    Example:
        async def my_query(prompt: str) -> str:
            # Your LLM query implementation
            response = await llm.generate(prompt)
            return response.text

        result = await extract_with_microloop(
            prompt="Return a JSON object with 'name' and 'age' fields.",
            schema={
                "type": "object",
                "required": ["name", "age"],
                "properties": {
                    "name": {"type": "string"},
                    "age": {"type": "integer", "minimum": 0},
                }
            },
            query_fn=my_query,
        )
    """
    log = log or logger
    result = ExtractionResult(success=False)
    current_prompt = prompt

    for attempt in range(max_attempts):
        result.attempts = attempt + 1

        log.debug("Structured output extraction attempt %d/%d", attempt + 1, max_attempts)

        # Query the LLM
        try:
            response = await query_fn(current_prompt)
        except Exception as e:
            log.warning("Query failed on attempt %d: %s", attempt + 1, e)
            result.errors = [
                ValidationError(
                    path="$",
                    message=f"Query failed: {e}",
                )
            ]
            result.raw_responses.append(f"[QUERY_ERROR: {e}]")
            continue

        result.raw_responses.append(response)

        # Try to extract JSON
        data, parse_error = extract_json_from_text(response)

        if data is None:
            log.warning(
                "Attempt %d: Failed to parse JSON: %s",
                attempt + 1,
                parse_error,
            )
            result.errors = [
                ValidationError(
                    path="$",
                    message=parse_error or "Invalid JSON",
                )
            ]

            # Build reprompt for next attempt
            if attempt < max_attempts - 1:
                current_prompt = build_reprompt(prompt, schema, result.errors, response)
            continue

        # Validate against schema
        validation_errors = validate_against_schema(data, schema)

        if not validation_errors:
            # Success!
            result.success = True
            result.data = data
            result.errors = []
            log.info(
                "Structured output extracted successfully on attempt %d",
                attempt + 1,
            )
            return result

        # Validation failed, prepare reprompt
        log.warning(
            "Attempt %d: Validation failed with %d errors",
            attempt + 1,
            len(validation_errors),
        )
        result.errors = validation_errors

        # Build reprompt for next attempt
        if attempt < max_attempts - 1:
            current_prompt = build_reprompt(prompt, schema, validation_errors, response)

    # Max attempts exceeded
    log.error(
        "Failed to extract valid structured output after %d attempts",
        max_attempts,
    )

    return result


def extract_with_microloop_sync(
    prompt: str,
    schema: Dict[str, Any],
    query_fn: Callable[[str], str],
    max_attempts: int = 3,
    log: Optional[logging.Logger] = None,
) -> ExtractionResult:
    """Synchronous version of extract_with_microloop.

    Wraps a synchronous query function and runs the async microloop
    using asyncio.run().

    Args:
        prompt: The initial prompt to send (should request JSON output).
        schema: JSON schema to validate the response against.
        query_fn: Synchronous function that sends a prompt and returns the response.
            Signature: def query_fn(prompt: str) -> str
        max_attempts: Maximum number of retry attempts (default: 3).
        log: Optional logger instance (uses module logger if not provided).

    Returns:
        ExtractionResult with extraction status and data.

    Example:
        def my_sync_query(prompt: str) -> str:
            # Your synchronous LLM query
            return subprocess.run(["llm", prompt], capture_output=True).stdout

        result = extract_with_microloop_sync(
            prompt="Return JSON with status field.",
            schema={"type": "object", "required": ["status"]},
            query_fn=my_sync_query,
        )
    """
    import asyncio

    async def async_query_wrapper(p: str) -> str:
        return query_fn(p)

    return asyncio.run(
        extract_with_microloop(
            prompt=prompt,
            schema=schema,
            query_fn=async_query_wrapper,
            max_attempts=max_attempts,
            log=log,
        )
    )


# =============================================================================
# Schema Helpers
# =============================================================================


def create_enum_schema(
    field_name: str,
    allowed_values: List[str],
    description: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a simple schema for a single enum field.

    Convenience helper for common case of extracting a single choice.

    Args:
        field_name: Name of the field.
        allowed_values: List of allowed string values.
        description: Optional description for the field.

    Returns:
        JSON schema dict.

    Example:
        schema = create_enum_schema(
            "status",
            ["VERIFIED", "UNVERIFIED", "BLOCKED"],
            "The verification status"
        )
    """
    prop: Dict[str, Any] = {
        "type": "string",
        "enum": allowed_values,
    }
    if description:
        prop["description"] = description

    return {
        "type": "object",
        "required": [field_name],
        "properties": {
            field_name: prop,
        },
    }


def create_step_result_schema(
    additional_fields: Optional[Dict[str, Dict[str, Any]]] = None,
    additional_required: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Create a standard step result schema with optional extensions.

    The base schema includes common step output fields:
    - status: VERIFIED/UNVERIFIED/BLOCKED
    - summary: Brief description of what was done
    - next_action: Recommended next action (optional)

    Args:
        additional_fields: Additional properties to add to the schema.
        additional_required: Additional required field names.

    Returns:
        JSON schema dict for step results.
    """
    schema: Dict[str, Any] = {
        "type": "object",
        "required": ["status", "summary"],
        "properties": {
            "status": {
                "type": "string",
                "enum": ["VERIFIED", "UNVERIFIED", "BLOCKED"],
                "description": "Step completion status",
            },
            "summary": {
                "type": "string",
                "minLength": 1,
                "description": "Brief summary of what was accomplished",
            },
            "next_action": {
                "type": "string",
                "description": "Recommended next action (optional)",
            },
            "artifacts": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of artifact paths created/modified",
            },
            "concerns": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of concerns or issues noted",
            },
        },
    }

    if additional_fields:
        schema["properties"].update(additional_fields)

    if additional_required:
        schema["required"] = list(set(schema["required"]) | set(additional_required))

    return schema
