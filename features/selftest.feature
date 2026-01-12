Feature: Selftest Resilience and Decomposability

  # Features for selftest acceptance & governance
  # NOTE: This file serves dual purpose as both design spec AND executable test suite.
  #
  # Golden-path scenarios marked @executable are runnable via pytest-bdd:
  #   pytest tests/test_selftest_bdd.py -m executable -v
  #
  # Design-only scenarios (without @executable) provide context and coverage
  # but are not executed as tests. Instead, they guide implementation decisions.
  #
  # The acceptance criteria are implemented in two ways:
  # 1. Detailed pytest tests (see tests/test_selftest_acceptance.py) for
  #    comprehensive validation of each AC cluster
  # 2. Thin executable BDD spine (this file + tests/test_selftest_bdd.py) for
  #    golden-path narrative verification
  #
  # Step definitions are in tests/bdd/steps/selftest_steps.py

  Background:
    Given the repository is in a clean state
    And git status shows no uncommitted changes
    And the necessary build tools (cargo, python, uv) are available

  # AC-1: Kernel health check exists and is fast
  @AC-SELFTEST-KERNEL-FAST @cap:selftest.kernel_smoke @executable
  Scenario: Kernel smoke check is fast and reliable
    When I run `uv run swarm/tools/kernel_smoke.py`
    Then the exit code should be 0 or 1
    And the total time should be acceptable for inner-loop development (sub-second baseline)
    And the output should contain either "HEALTHY" or "BROKEN"
    And if exit code is 0, then output should indicate "HEALTHY"
    And if exit code is 1, then output should indicate "BROKEN"

  @AC-SELFTEST-KERNEL-FAST
  Scenario: Kernel smoke check reports exit code correctly
    When I run `uv run swarm/tools/kernel_smoke.py --verbose`
    Then the exit code should be 0 if kernel is healthy
    And the exit code should be 1 if kernel is broken
    And the output should show which components (ruff, compile checks) passed or failed

  # AC-2: Selftest is introspectable
  @AC-SELFTEST-INTROSPECTABLE @cap:selftest.introspectable_plan @executable
  Scenario: Selftest plan shows all steps with tiers
    Given the selftest system is properly installed
    When I run `uv run swarm/tools/selftest.py --plan`
    Then the exit code should be 0
    And the output should list at least 16 steps with clearly identified IDs
    And the output should contain "KERNEL"
    And the output should contain "GOVERNANCE"
    And the output should contain "OPTIONAL"
    And the total time should be acceptable for introspection (reasonable sub-second baseline)

  @AC-SELFTEST-INTROSPECTABLE @executable
  Scenario: Selftest plan output is machine-parseable
    When I run `uv run swarm/tools/selftest.py --plan --json`
    Then the exit code should be 0
    And the output should be valid JSON
    And the JSON should have a "steps" array with at least 16 items
    And each step in JSON should have: id, tier, description, depends_on

  @AC-SELFTEST-INTROSPECTABLE
  Scenario: Selftest plan shows dependencies
    When I run `uv run swarm/tools/selftest.py --plan`
    Then the output should show step IDs and dependency information
    And each step should be identifiable by its id field
    And steps with no dependencies should be identifiable as root steps

  # AC-3: Selftest can run individual steps
  @AC-SELFTEST-INDIVIDUAL-STEPS @cap:selftest.individual_steps @executable
  Scenario: Can run individual selftest steps
    When I run `uv run swarm/tools/selftest.py --step core-checks`
    Then the exit code should reflect only that step's status
    And the output should show step status (PASS or FAIL)
    And only that step should be executed

  @AC-SELFTEST-INDIVIDUAL-STEPS
  Scenario: Can run selftest steps up to a given step
    When I run `uv run swarm/tools/selftest.py --until skills-governance`
    Then the exit code should reflect the status of steps 1-2
    And the output should show:
      | step                |
      | core-checks         |
      | skills-governance   |

  @AC-SELFTEST-INDIVIDUAL-STEPS
  Scenario: Individual step failures are isolated
    When I run `uv run swarm/tools/selftest.py --step agents-governance`
    Then the exit code should reflect only that step's status
    And the output should show only that step's output

  @AC-SELFTEST-INDIVIDUAL-STEPS
  Scenario: Step output includes timing and error details
    When I run `uv run swarm/tools/selftest.py --step core-checks`
    Then the output should include:
      | field       | example          |
      | step_id     | core-checks      |
      | status      | PASS or FAIL     |
      | elapsed_ms  | (numeric, optional) |

  # AC-4: Selftest degraded mode
  @AC-SELFTEST-DEGRADED @cap:selftest.degraded_mode @executable
  Scenario: Degraded mode allows work around governance failures
    When I run `uv run swarm/tools/selftest.py --degraded`
    Then the exit code should be 0 or 1
    And degraded mode should be indicated in output

  @AC-SELFTEST-DEGRADED
  Scenario: Degraded mode treats OPTIONAL failures as warnings
    When I run `uv run swarm/tools/selftest.py --degraded`
    Then the exit code should be 0 or 1
    And OPTIONAL tier failures should not block merging in degraded mode

  @AC-SELFTEST-DEGRADED
  Scenario: Degraded mode still blocks KERNEL failures
    When I run `uv run swarm/tools/selftest.py --degraded --plan`
    Then the output should mention that KERNEL failures block merges even in degraded mode

  @AC-SELFTEST-DEGRADED
  Scenario: /platform/status reflects degraded state
    When selftest is run with `--degraded` flag
    Then the /platform/status endpoint should reflect degraded mode state
    And the response should indicate which steps failed

  # AC-5: Selftest failure hints
  @AC-SELFTEST-FAILURE-HINTS
  Scenario: Failed selftest provides actionable hints
    When I run `uv run swarm/tools/selftest.py`
    Then the output should include actionable hints
    And hints should reference how to run individual steps or the plan

  @AC-SELFTEST-FAILURE-HINTS
  Scenario: Failure output includes hints for debugging
    When I run `uv run swarm/tools/selftest.py`
    Then the output should be informative with hints to resolve issues
    And hints should reference documentation or alternative commands

  @AC-SELFTEST-FAILURE-HINTS
  Scenario: /platform/status includes failure hints in response
    When selftest is run
    Then the /platform/status endpoint should include hints about failures
    And hints should be actionable (commands or links)

  # AC-6: Governance degradation is tracked
  @AC-SELFTEST-DEGRADATION-TRACKED
  Scenario: Governance failures are logged to persistent log
    Given a temporary condition will cause GOVERNANCE failure
    When I run `uv run swarm/tools/selftest.py --degraded`
    Then a file `selftest_degradations.log` should be created or appended
    And the log should contain entries with:
      | field     | type   |
      | timestamp | string |
      | step_id   | string |
      | tier      | string |
      | message   | string |

  @AC-SELFTEST-DEGRADATION-TRACKED
  Scenario: Degradation log is machine-readable
    Given selftest_degradations.log exists
    When parsed as JSON Lines format
    Then each line should be valid JSON
    And each line should have timestamp, step_id, tier, and message fields

  @AC-SELFTEST-DEGRADATION-TRACKED
  Scenario: Degradation log is human-readable
    Given selftest_degradations.log exists
    When viewed as plain text
    Then it should be formatted with clear structure
    And each entry should include step id, error, and suggestions

  @AC-SELFTEST-DEGRADATION-TRACKED
  Scenario: Multiple degradations are tracked
    When selftest runs with --degraded and multiple GOVERNANCE steps fail
    Then selftest_degradations.log should contain multiple entries
    And each entry should have a distinct timestamp and step_id
    And entries should be ordered chronologically

  @AC-SELFTEST-DEGRADATION-TRACKED
  Scenario: Log persists across runs
    Given selftest_degradations.log already has entries
    When selftest runs again with --degraded
    Then new entries should be appended to the log
    And previous entries should remain visible
    And log should be ordered chronologically
