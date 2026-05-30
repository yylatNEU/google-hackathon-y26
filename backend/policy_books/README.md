# ParkPulse Policybook Authoring Contract

Policybooks are ground truth for ParkPulse action generation, policy citations, and runtime gates. A generated or dispatched action is considered policy-grounded only when its `policy_compliance.policy_refs` match the refs resolved from these files for the active `target/action/scenario`.

## Rule Metadata

Every executable `decision_rules` entry should define:

```json
{
  "id": "PARK-AREA-001",
  "name": "Human-readable rule name",
  "applies_to": {
    "targets": ["ride"],
    "actions": ["reroute"],
    "scenarios": ["ride_down"]
  },
  "allowed_action": "What the agent may do.",
  "blocked_action": "What the agent must not do."
}
```

`applies_to` is the citation contract. The policy engine resolves expected refs from it.

- `targets`: ParkPulse target domains such as `ride`, `traffic`, `staff`, `food`, `energy`, `event`, or `guest`.
- `actions`: executable operation names such as `reroute`, `route_all`, `redeploy`, or `reduce_hvac`.
- `scenarios`: optional active scenario keys such as `ride_down`, `staff_shortage`, `food_spike`, or `storm_response`.

If `scenarios` is present, the rule applies only when that active scenario is supplied. It must not leak into generic action refs.

## Conditions

Use `block_conditions` when a matching action must be stopped. Use `review_conditions` when a matching action requires operator approval.

```json
{
  "block_conditions": [
    {
      "targets": ["ride"],
      "actions": ["reopen"],
      "state": {"any_ride_status": "down"},
      "message": "Ride action requires certified maintenance clearance before execution."
    }
  ],
  "review_conditions": [
    {
      "targets": ["guest"],
      "actions": ["recovery_offer"],
      "unless_policy_status": ["approved"],
      "message": "Recovery offers require guest-care approval before dispatch."
    }
  ]
}
```

Each condition must include a non-empty `message`. Supported condition keys are:

- `targets`: list of target domains.
- `actions`: list of executable operations.
- `text_contains`: list of lowercase text fragments to match against action title, impact, owner, target, and action.
- `state`: supported state predicates are `any_ride_status`, `any_zone_density_gte`, and `weather_storm_risk_gte`.
- `unless_policy_status`: statuses that exempt the condition.
- `message`: operator-facing policy finding.

## Validation Expectations

Before merging policy changes, run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=backend backend/venv/bin/python -m pytest backend/test_policy_loader.py backend/test_policy_engine.py -q
```

The tests verify:

- policy refs are known and active governance refs exist;
- `applies_to`, `block_conditions`, and `review_conditions` use supported shapes;
- scenario-scoped rules do not apply without an active matching scenario;
- generated plans and runtime actions cite the exact expected policy refs.
