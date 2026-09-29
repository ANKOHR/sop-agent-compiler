SOP: Synthetic Broken Reachability Procedure
Owner: Fictional Records Team
Trigger: A fictional archive request arrives.
Roles:
- operator: records.read
Steps:
## read_request [action]
Action: Read the fictional archive request.
Requires: records.read
Next: END

## unreachable_archive [action]
Action: Archive an unreachable fictional record.
Requires: records.archive.admin
Next: END
