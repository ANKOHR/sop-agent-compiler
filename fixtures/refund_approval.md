SOP: Synthetic Refund Approval
Owner: Fictional Support Operations
Trigger: A fictional customer submits a refund request.
Roles:
- operator: refunds.read, refunds.issue, refunds.update, refunds.notify
Steps:
## inspect_request [action]
Action: Review the fictional order and refund request.
Requires: refunds.read
Preconditions: order exists; request is within the fictional policy window
Next: manager_approval

## manager_approval [checkpoint]
Human: true
Next: issue_refund
On reject: record_rejection
On edit: revise_request

## revise_request [action]
Action: Update the fictional request details using the approver's reason.
Requires: refunds.update
Next: manager_approval

## issue_refund [action]
Action: Issue the approved refund to the fictional payment method.
Consequence: payment
Requires: refunds.issue
Retry: attempts=3, backoff=200ms, factor=2, max=1s
Timeout: 8s
Postconditions: simulated refund receipt exists
Next: receipt_approval

## receipt_approval [checkpoint]
Human: true
Next: send_receipt
On reject: record_no_receipt

## send_receipt [action]
Action: Send the fictional refund receipt to the customer.
Consequence: external_send
Requires: refunds.notify
Next: END

## record_rejection [action]
Action: Record the fictional refund rejection.
Requires: refunds.update
Next: END

## record_no_receipt [action]
Action: Record that no external receipt was sent.
Requires: refunds.update
Next: END
