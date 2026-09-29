SOP: Synthetic Broken Payment Procedure
Owner: Fictional Support Operations
Trigger: A fictional payment request arrives.
Roles:
- operator: payments.issue
Steps:
## issue_payment [action]
Action: Charge the fictional customer's payment method.
Consequence: payment
Requires: payments.issue
Next: END
