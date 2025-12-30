## Testing Patterns

Standard testing conventions for the build flow.

### Test Structure

Organize tests using the Arrange-Act-Assert pattern:

```
1. Arrange: Set up test fixtures and preconditions
2. Act: Execute the code under test
3. Assert: Verify expected outcomes
```

### Test Naming

Use descriptive names that explain the scenario:

```
test_<unit>_<scenario>_<expected_result>

Examples:
- test_login_valid_credentials_returns_jwt
- test_login_invalid_password_returns_401
- test_session_expired_token_returns_401
```

### Coverage Requirements

Each requirement should have tests covering:

| Path | Description | Priority |
|------|-------------|----------|
| Happy path | Normal successful operation | Required |
| Error paths | Expected failure cases | Required |
| Edge cases | Boundary conditions | Required |
| Security cases | Auth, validation, injection | Required for auth flows |

### Test Isolation

- Tests should not depend on each other
- Use fixtures and mocks to isolate external dependencies
- Clean up state after each test
- Avoid shared mutable state

### REQ/Scenario Tagging

Tag tests with their corresponding requirements:

```python
# Python example
@pytest.mark.req("REQ-001")
def test_login_returns_jwt():
    ...

# JavaScript example
describe("REQ-001: User Authentication", () => {
  it("should return JWT on valid login", () => {
    ...
  });
});
```

### Expected Failures

When tests are written before implementation:

- Mark tests as expected to fail (xfail, skip)
- Document why they're expected to fail
- Remove skip/xfail markers after implementation

```python
@pytest.mark.xfail(reason="Implementation pending - AC-001")
def test_feature_not_implemented():
    ...
```

### Test Fixtures

Create reusable fixtures for common setup:

```python
@pytest.fixture
def authenticated_user():
    """Create a test user with valid session."""
    user = create_test_user()
    token = generate_test_token(user)
    return {"user": user, "token": token}
```

### Assertion Quality

Assertions should verify specific behavior, not just status codes:

**Weak (avoid):**
```python
assert response.status_code == 200
```

**Strong (prefer):**
```python
assert response.status_code == 200
assert "token" in response.json()
assert response.json()["token"].count(".") == 2  # JWT format
assert response.json()["expires_in"] == 900  # 15 minutes
```

### Error Path Testing

Test all documented error conditions:

```python
def test_login_empty_password_returns_400():
    response = login(username="user", password="")
    assert response.status_code == 400
    assert response.json()["error_code"] == "INVALID_INPUT"
    assert "password" in response.json()["message"].lower()
```

### BDD Scenario Mapping

Map Gherkin scenarios to test functions:

```gherkin
# features/login.feature
Scenario: Successful login
  Given a registered user
  When they login with valid credentials
  Then they receive a JWT token
```

```python
# tests/test_login.py
def test_successful_login_returns_jwt():
    """Maps to: Scenario: Successful login"""
    user = create_registered_user()  # Given
    response = login(user.email, user.password)  # When
    assert "token" in response.json()  # Then
```
