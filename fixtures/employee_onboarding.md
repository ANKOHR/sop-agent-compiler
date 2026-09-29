SOP: Synthetic Employee Onboarding
Owner: Fictional People Operations
Trigger: A fictional hiring record is marked ready for onboarding.
Roles:
- operator: employee.read, employee.create, device.provision, access.assign, training.assign
Steps:
## validate_request [action]
Action: Validate that the fictional hiring record is complete.
Preconditions: hiring record exists; start date is present
Postconditions: onboarding request is ready
Requires: employee.read
Next: prepare_workspace

## prepare_workspace [parallel]
Branches: create_profile, provision_device
Join: welcome_employee

## create_profile [action]
Action: Create a fictional employee directory profile.
Requires: employee.create
Next: welcome_employee

## provision_device [action]
Action: Provision a fictional laptop from the simulated inventory.
Requires: device.provision
Next: welcome_employee

## welcome_employee [action]
Action: Assign fictional onboarding training and record the welcome packet as ready.
Requires: training.assign
Next: END
